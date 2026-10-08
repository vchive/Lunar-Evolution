"""Offline Feature189 build-plan emitter (never runs a compiler or target)."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .profile import (
    BUILTINS,
    CPYTHON_ARCHIVE,
    FROZEN,
    MAX_IMAGE_BYTES,
    TARGET,
    ZIG_ARCHIVE,
    manifest,
)


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


def _build_script() -> str:
    return """#!/bin/sh
set -eu
umask 022
: \"${LUNAR_STATIC_SOURCE:?set to verified extracted CPython root}\"
: \"${LUNAR_STATIC_ZIG:?set to verified Zig 0.16.0 root}\"
: \"${LUNAR_STATIC_OUT:?set to an empty output directory}\"
case \"$LUNAR_STATIC_SOURCE\" in /*) ;; *) echo 'source must be absolute' >&2; exit 64;; esac
case \"$LUNAR_STATIC_ZIG\" in /*) ;; *) echo 'zig must be absolute' >&2; exit 64;; esac
case \"$LUNAR_STATIC_OUT\" in /*) ;; *) echo 'out must be absolute' >&2; exit 64;; esac
test -d \"$LUNAR_STATIC_SOURCE\" && test -x \"$LUNAR_STATIC_ZIG/zig\"
test ! -e \"$LUNAR_STATIC_OUT\"; mkdir \"$LUNAR_STATIC_OUT\"
exec env -i PATH=/usr/bin:/bin LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=0 CONFIG_SITE=/dev/null \\
  LUNAR_STATIC_SOURCE=\"$LUNAR_STATIC_SOURCE\" LUNAR_STATIC_ZIG=\"$LUNAR_STATIC_ZIG\" \\
  LUNAR_STATIC_OUT=\"$LUNAR_STATIC_OUT\" LUNAR_STATIC_RECIPE_DIR=\"$LUNAR_STATIC_RECIPE_DIR\" \\
  ac_cv_func_dlopen=no LUNAR_STATIC_CLEAN_ENV=1 \\
  sh \"$LUNAR_STATIC_RECIPE_DIR/linux-build-commands.sh\"
"""


def _commands() -> str:
    generated = []
    for name, generator_id, source, _package in FROZEN:
        input_path = "$LUNAR_STATIC_RECIPE_DIR/assets/frozen_main.py" if name == "_lunar_static_main" else (
            f"$LUNAR_STATIC_SOURCE/{source}"
        )
        output_name = generator_id + ".h"
        generated.append(
            f"./Programs/_freeze_module '{generator_id}' '{input_path}' "
            f"'$LUNAR_STATIC_OUT/generated/{output_name}'"
        )
    generator_lines = "\n".join(generated)
    return f"""#!/bin/sh
set -eu
cd \"$LUNAR_STATIC_SOURCE\"
export CC=\"$LUNAR_STATIC_ZIG/zig cc -target {TARGET}\"
export AR=\"$LUNAR_STATIC_ZIG/zig ar\"
export RANLIB=\"$LUNAR_STATIC_ZIG/zig ranlib\"
./configure --host={TARGET} --build={TARGET} --without-shared --disable-test-modules \\
  --with-ensurepip=no --with-computed-gotos --with-pymalloc
# Do not run regen-frozen. Build Programs/_freeze_module from the same object set.
make Programs/_freeze_module
mkdir -p "$LUNAR_STATIC_OUT/generated"
{generator_lines}
# Apply reviewed exact patches, compile emitted assets, and direct-link the manifest map.
# A later verifier must inspect DT_NEEDED/PT_INTERP and enforce image <= {MAX_IMAGE_BYTES} bytes.
echo 'PLAN ONLY: compile/link requires explicit Linux CI opt-in' >&2
exit 78
"""


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
    (destination / "manifest.json").write_text(
        json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    recipe = destination / "build.sh"
    recipe.write_text(_build_script().replace("$LUNAR_STATIC_RECIPE_DIR", str(destination)),
                      encoding="utf-8", newline="\n")
    commands = destination / "linux-build-commands.sh"
    commands.write_text(_commands(), encoding="utf-8", newline="\n")
    for path in (recipe, commands):
        os.chmod(path, 0o555)
    return destination
