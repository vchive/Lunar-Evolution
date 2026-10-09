"""Offline Feature189 build-plan emitter (never runs a compiler or target)."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .build_inputs import emit_static_python_build_inputs
from .profile import (
    BUILTINS,
    CPYTHON_ARCHIVE,
    FROZEN,
    ZIG_ARCHIVE,
    manifest,
)
from .source_patches import source_patch_manifest
from .tables import emit_static_python_tables


class RecipeError(ValueError):
    """Installation input cannot be admitted to the fixed recipe."""


@dataclass(frozen=True, slots=True)
class ExactPatch:
    path: str
    preimage_sha256: str
    old: bytes
    new: bytes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(path: Path, pin: dict[str, object]) -> dict[str, object]:
    """Verify archive bytes before extraction or mutation."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise RecipeError("archive is not a regular file")
    size = path.stat().st_size
    if size != pin["size"]:
        raise RecipeError(f"archive size mismatch: {size}")
    digest = _sha256(path)
    if digest != pin["sha256"]:
        raise RecipeError("archive sha256 mismatch")
    return {"path": str(path), "bytes": size, "sha256": digest, "url": pin["url"]}


def extract_source(archive: Path, destination: Path,
                   pin: dict[str, object] = CPYTHON_ARCHIVE) -> Path:
    """Containment-only extraction; links, devices, duplicates and traversal fail."""
    verify_archive(archive, pin)
    requested = Path(destination)
    parent = requested.parent
    while True:
        if parent.is_symlink():
            raise RecipeError("destination parent is a symlink")
        if parent == parent.parent:
            break
        parent = parent.parent
    destination = requested.resolve()
    if destination.exists() or destination.is_symlink():
        raise RecipeError("destination must not exist")
    destination.mkdir(parents=True)
    root_name = str(pin["root"])
    seen: set[str] = set()
    root = destination / root_name
    try:
        with tarfile.open(archive, mode="r:xz") as stream:
            for member in stream.getmembers():
                name = member.name
                if not name or name.startswith("/") or "\\" in name:
                    raise RecipeError("archive member path is not canonical")
                parts = Path(name).parts
                if not parts or parts[0] != root_name or ".." in parts:
                    raise RecipeError("archive member escapes pinned root")
                canonical = "/".join(parts)
                if canonical in seen:
                    raise RecipeError("duplicate archive member")
                seen.add(canonical)
                if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    raise RecipeError("archive links/devices are not permitted")
                target = destination.joinpath(*parts)
                resolved_parent = target.parent.resolve()
                if destination.resolve() not in resolved_parent.parents and resolved_parent != destination.resolve():
                    raise RecipeError("archive member parent escapes destination")
                if member.isdir():
                    if target.exists():
                        if not target.is_dir() or target.is_symlink():
                            raise RecipeError("archive directory collides with a file")
                    else:
                        target.mkdir(parents=True, exist_ok=False)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = stream.extractfile(member)
                    if source is None:
                        raise RecipeError("archive file has no content")
                    with target.open("xb") as output:
                        while block := source.read(1024 * 1024):
                            output.write(block)
                    os.chmod(target, stat.S_IMODE(member.mode) & 0o777)
    except (tarfile.TarError, OSError) as exc:
        raise RecipeError(f"source extraction failed: {exc}") from exc
    if not root.is_dir() or root.is_symlink():
        raise RecipeError("pinned source root missing")
    return root


def apply_exact_patch(root: Path, patch: ExactPatch) -> str:
    """Apply one byte-exact patch only after checking its declared preimage."""
    path = Path(root) / patch.path
    if not path.is_file() or path.is_symlink():
        raise RecipeError(f"patch input is not a regular file: {patch.path}")
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != patch.preimage_sha256:
        raise RecipeError(f"patch preimage hash mismatch: {patch.path}")
    if original.count(patch.old) != 1:
        raise RecipeError(f"patch preimage occurrence mismatch: {patch.path}")
    replacement = original.replace(patch.old, patch.new, 1)
    temporary = path.with_name(path.name + ".lunar-new")
    temporary.write_bytes(replacement)
    os.replace(temporary, path)
    return hashlib.sha256(replacement).hexdigest()


def _assets() -> dict[str, str]:
    base = Path(__file__).with_name("assets")
    return {name: (base / name).read_text(encoding="utf-8") for name in
            ("launcher.c", "pipe.c", "profile.c", "getpath.c", "lunar_fixture_profile.h", "frozen_main.py")}


def emit_assets(destination: Path) -> tuple[str, ...]:
    """Emit deterministic fixture inputs; does not compile them."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    replacements = {
        "__LUNAR_EXPECTED_BUILTINS__": repr(list(BUILTINS)),
        "__LUNAR_EXPECTED_FROZEN__": repr([item[0] for item in FROZEN]),
        "__LUNAR_EXPECTED_MODULES__": repr([
            "sys", "builtins", "_frozen_importlib", "_imp", "_thread", "_warnings", "_weakref",
            "_frozen_importlib_external", "_io", "marshal", "posix", "encodings", "codecs",
            "_codecs", "encodings.aliases", "encodings.utf_8", "io", "abc", "_abc", "__main__",
            "_lunar_static_main", "_lunar_fixture_pipe",
        ]),
    }
    emitted = []
    for name, source in _assets().items():
        for old, new in replacements.items():
            source = source.replace(old, new)
        path = destination / name
        path.write_text(source, encoding="utf-8", newline="\n")
        os.chmod(path, 0o444)
        emitted.append(name)
    return tuple(emitted)


def _build_script(destination: Path) -> str:
    # No opt-in can authorize an incomplete configure/object/archive closure.
    return """#!/bin/sh
set -eu
umask 022
__LUNAR_RECIPE_ASSIGNMENT__
if [ "${LUNAR_STATIC_EXECUTE:-0}" != 1 ]; then
  echo 'PLAN ONLY: static Python build inputs are not admitted for execution' >&2
  exit 78
fi
echo 'PLAN ONLY: configured object/archive closure remains unverified; configure, compiler and freezer are disabled' >&2
exit 78
""".replace("__LUNAR_RECIPE_ASSIGNMENT__",
            "LUNAR_STATIC_RECIPE_DIR=" + shlex.quote(str(destination)))


def _commands() -> str:
    return """#!/bin/sh
set -eu
# The exact candidate inputs and nine pending freezer tasks are in build-inputs.json.
# They are source-review facts, not an observed configured object/archive closure.
# Stock make, configure and a host Python freezer cannot substitute for that gate.
echo 'PLAN ONLY: configure, compiler, linker and freezer remain disabled' >&2
exit 78
"""


def _verify_emitted_source_assets(destination: Path, inputs: dict[str, object]) -> None:
    """Check local emitted bytes against the separately pinned candidate plan.

    Upstream and prepared CPython inputs have not been acquired here. Only
    installation-owned source assets actually written by this emitter are read.
    """
    records = [*inputs["shared_units"], *inputs["target_units"], *inputs["freeze_tasks"]]
    for item in records:
        origin = item["origin"]
        if origin == "fixture-asset":
            relative = "assets/" + Path(item["source"]).name
        elif origin in {"installation-owned-table", "expanded-fixture-asset"}:
            relative = item["source"]
        else:
            continue
        raw = (destination / relative).read_bytes()
        if len(raw) != item["source_size"] or hashlib.sha256(raw).hexdigest() != item["source_sha256"]:
            raise RecipeError(f"emitted source asset drift: {relative}")
    for item in [*inputs["generated_sources"], *inputs["fixture_headers"]]:
        raw = (destination / item["path"]).read_bytes()
        if len(raw) != item["source_size"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise RecipeError(f"emitted source asset drift: {item['path']}")


def emit_build_plan(destination: Path, *, source_archive: Path | None = None,
                    zig_archive: Path | None = None) -> Path:
    """Write a plan and assets; supplied archives are verified but never extracted."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise RecipeError("plan destination must not exist")
    destination.mkdir(parents=True)
    facts = manifest()
    if source_archive is not None:
        facts["source_archive"] = verify_archive(Path(source_archive), CPYTHON_ARCHIVE)
    if zig_archive is not None:
        facts["toolchain_archive"] = verify_archive(Path(zig_archive), ZIG_ARCHIVE)
    facts["emitted_assets"] = list(emit_assets(destination / "assets"))
    reviewed_inputs = Path(__file__).with_name("reviewed-build-inputs.json").read_bytes()
    build_inputs = emit_static_python_build_inputs(reviewed_inputs)
    input_bytes = json.dumps(build_inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    (destination / "build-inputs.json").write_bytes(input_bytes)
    facts["build_inputs"] = {
        "path": "build-inputs.json", "sha256": hashlib.sha256(input_bytes).hexdigest(),
        "size": len(input_bytes), "state": "source-reviewed-candidate-only",
        "configured_closure_verified": False, "execution_enabled": False,
    }
    facts["source_preparation"] = source_patch_manifest()
    facts["generated_source_assets"] = []
    for relative, content in sorted(emit_static_python_tables().items()):
        path = destination / "generated-sources" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.chmod(path, 0o444)
        facts["generated_source_assets"].append({
            "path": relative, "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        })
    _verify_emitted_source_assets(destination, build_inputs)
    facts["source_preparation_applied"] = False
    facts["frozen_header_state"] = "requires-pinned-freezer"
    facts["link_state"] = "not-executed"
    (destination / "manifest.json").write_text(
        json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    recipe = destination / "build.sh"
    recipe.write_text(_build_script(destination),
                      encoding="utf-8", newline="\n")
    commands = destination / "linux-build-commands.sh"
    commands.write_text(_commands(), encoding="utf-8", newline="\n")
    for path in (recipe, commands):
        os.chmod(path, 0o555)
    return destination
