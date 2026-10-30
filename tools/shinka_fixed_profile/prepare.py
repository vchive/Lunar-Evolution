"""Deterministic source preparation for one pinned, unaccepted Shinka profile.

Explicit input bytes and fixed pinned assets are parsed/copied without imports,
execution or filesystem writes. The result is preparation evidence, never runtime or publication authority.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.openevolve_fixed_profile import prepare as _shared

BROKER_BYTES = _shared.BROKER_BYTES
TRANSPORT_BYTES = _shared.TRANSPORT_BYTES

PROFILE = "lunar-shinka-v007-one-diff-source-v1"
ARCHIVE_BYTES = 9_450_712
ARCHIVE_SHA256 = "4a9c242de0b2b316013ed7ee1b3ebc8a94a6bf6098e7e370fadd5b94201e1d67"
ARCHIVE_ROOT = "SakanaAI-ShinkaEvolve-c4568ad"
ARCHIVE_FILES = 287
ARCHIVE_CONTENT_BYTES = 12_837_527
_ASSETS = Path(__file__).parent / "assets"
_ASSET_PINS = {
    "fixed_entrypoint.py": (20_091, "b42fe9f7876888784332ec9605e332a043db4ec6be380a5dd0a87ed901cdfeb9"),
    "LICENSE.lunar": (1_063, "360689238ecd6c5940cb7abc450a749cbe4d8556e3bcac1a97694ccfce2d11c8"),
    "package_init.py": (93, "28eefe5781ab97cf758e8b9d10eca2c10dd96a59d110e016ba7f29c6dc9cd1d5"),
}
_ORIGINAL_PINS = {
    "LICENSE": (10_237, "c3e5b1c26607caf7208d5a105c113fe240630bb873fdb8ca5b4c2e32c721ddaf"),
    "shinka/__init__.py": (113, "36b299fcca12a27c6d72b9705616ebf08d4cadca0e5f0e5f52667c387c10ccf1"),
    "shinka/edit/__init__.py": (331, "b2ec3a6b6990382a03bba4e32a78e7e199dd5d1b27783c918c3672bbb66e8d26"),
    "shinka/prompts/__init__.py": (2_298, "fa2f66681436f46299f654ec8db42c2edf62e882ea9a1b533797cbdc6de2e977"),
    "shinka/utils/__init__.py": (755, "5d55aba3799f7c929d17e50513b5c7c1d3d60f84c6e59397b37c4966aee2213e"),
    "shinka/edit/apply_diff.py": (27_931, "452be70d934df4493ca2e6ce113556193df345b358ca546df7766ba062a264d6"),
    "shinka/edit/marker_validation.py": (3_545, "c876c6f87804c7f135a55781c6f62fef276bf345956f30a2e1842391df960027"),
    "shinka/prompts/prompts_diff.py": (2_457, "a2b1c13289bed12c1edc40392c8585dd3e5fbc89149423737648a8846df744a4"),
    "shinka/utils/languages.py": (7_591, "64988c1a54cedb3377fee80d26f46c21201af2b399cf09e1942ed679850294ce"),
}
PREPARED_PATHS = frozenset({
    "LICENSE", "LICENSE.lunar", "shinka/__init__.py", "shinka/lunar_fixed.py",
    "shinka/lunar_fixed_broker.py", "shinka/edit/__init__.py", "shinka/edit/apply_diff.py",
    "shinka/edit/marker_validation.py", "shinka/prompts/__init__.py",
    "shinka/prompts/prompts_diff.py", "shinka/utils/__init__.py", "shinka/utils/languages.py",
})


class ShinkaPreparationError(ValueError):
    """Fixed code without source bytes, caller paths or original error prose."""


def _fail(code: str) -> None:
    raise ShinkaPreparationError("shinka_source_" + code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(raw: bytes) -> dict[str, object]:
    return {"bytes": len(raw), "sha256": _sha(raw)}


def _pinned(raw: bytes, size: int, digest: str, code: str) -> None:
    if type(raw) is not bytes or len(raw) != size or _sha(raw) != digest:
        _fail(code)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PreparedSource:
    path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ShinkaPreparedProfile:
    sources: tuple[PreparedSource, ...]
    manifest: bytes

    @property
    def manifest_sha256(self) -> str:
        return _sha(self.manifest)


def _read_archive_members(
    archive: bytes, *, expected_files: int, expected_bytes: int, selected: set[str],
) -> dict[str, bytes]:
    """Bounded all-member walk, with no filesystem extraction or code execution.

    Caller must verify the complete archive pin first. The separate arguments
    permit synthetic malformed-archive fixtures without loosening that public pin.
    """
    seen: set[str] = set()
    found: dict[str, bytes] = {}
    files = total = members = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            for member in source:
                members += 1
                if members > 1024:
                    _fail("archive_bounds")
                name = member.name.rstrip("/") if member.isdir() else member.name
                parts = name.split("/")
                if (not name or "\\" in name or "\x00" in name or name.startswith("/")
                        or any(part in {"", ".", ".."} for part in parts)
                        or parts[0] != ARCHIVE_ROOT or name in seen):
                    _fail("archive_path_invalid")
                seen.add(name)
                if member.isdir():
                    if member.size != 0 or member.mode not in {0o755, 0o775}:
                        _fail("archive_member_invalid")
                    continue
                # The pinned GitHub tar keeps group-write bits (0664/0775);
                # the reviewed Git tree projects only the executable bit.
                if (not member.isreg() or len(parts) < 2
                        or member.mode not in {0o644, 0o664, 0o755, 0o775}
                        or not 0 <= member.size <= expected_bytes):
                    _fail("archive_member_invalid")
                files += 1
                total += member.size
                if files > expected_files or total > expected_bytes:
                    _fail("archive_bounds")
                path = str(PurePosixPath(*parts[1:]))
                handle = source.extractfile(member)
                if handle is None:
                    _fail("archive_member_invalid")
                with handle:
                    data = handle.read(member.size + 1)
                if len(data) != member.size:
                    _fail("archive_truncated")
                if path in selected:
                    found[path] = data
    except ShinkaPreparationError:
        raise
    except (tarfile.TarError, OSError, EOFError, ValueError, OverflowError):
        _fail("archive_invalid")
    if files != expected_files or total != expected_bytes or set(found) != selected:
        _fail("archive_inventory_mismatch")
    return found


def _asset(name: str) -> bytes:
    size, digest = _ASSET_PINS[name]
    try:
        with (_ASSETS / name).open("rb") as source:
            raw = source.read(size + 1)
    except OSError:
        _fail("asset_unavailable")
    _pinned(raw, size, digest, "asset_drift")
    return raw


_SHARED_BOUNDARY_NAMES = (
    "_REQUEST_FIELDS", "_MEMORY_FIELDS", "_MEMORY_ITEM_REQUIRED", "_MEMORY_ITEM_OPTIONAL",
    "_HEX", "_MODEL", "MAX_RECORD_BYTES", "MAX_PROGRAM_BYTES", "MAX_TASK_BYTES",
    "MAX_MEMORY_PROMPT_BYTES", "MAX_PROMPT_BYTES", "MAX_REPLY_BYTES", "MAX_LINES",
    "MAX_DIFFS", "MAX_ATTEMPT_SECONDS", "FixedProfileError", "_fail", "_canonical",
    "_shape", "_decode", "_text", "_digest", "_identifier", "_memory_item", "_inputs",
    "_memory_history", "_read_at", "_write_at",
)


def _boundary_nodes(raw: bytes) -> dict[str, ast.AST]:
    nodes = {}
    for node in ast.parse(raw).body:
        name = None
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            name = node.name
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
        if name in _SHARED_BOUNDARY_NAMES:
            nodes[name] = node
    if set(nodes) != set(_SHARED_BOUNDARY_NAMES):
        _fail("shared_boundary_drift")
    return nodes


def _shared_boundary_guard(entrypoint: bytes) -> dict[str, object]:
    """Refuse an unchecked second input/memory/file boundary implementation.

    The two checked assets differ only by fixed solver/error labels and the
    additional single-region validation call in the Shinka request parser.
    AST comparison is local to one interpreter, not a cross-version AST hash.
    """
    try:
        baseline = _shared._asset("fixed_entrypoint.py")
    except _shared.OpenEvolvePreparationError:
        _fail("shared_boundary_drift")
    original = _boundary_nodes(baseline)
    observed = _boundary_nodes(entrypoint)
    inputs = observed["_inputs"]
    calls = [
        node for node in inputs.body
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name) and node.value.func.id == "_region"
            and len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == "program" and not node.value.keywords)
    ]
    if len(calls) != 1:
        _fail("shared_boundary_drift")
    inputs.body.remove(calls[0])
    for node in observed.values():
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and child.value == "shinka":
                child.value = "openevolve"
            elif isinstance(child, ast.Constant) and child.value == "shinka_fixed_":
                child.value = "openevolve_fixed_"
    for name in _SHARED_BOUNDARY_NAMES:
        if ast.dump(original[name], include_attributes=False) != ast.dump(observed[name], include_attributes=False):
            _fail("shared_boundary_drift")
    return {
        "baseline": {"path": "tools/openevolve_fixed_profile/assets/fixed_entrypoint.py", **_identity(baseline)},
        "definitions": list(_SHARED_BOUNDARY_NAMES), "ast_equivalent": True,
        "allowed_differences": ["fixed_solver_and_error_label", "single_python_region_validation"],
    }


def _stdlib_imports(sources: tuple[PreparedSource, ...]) -> list[str]:
    imports = set()
    for source in sources:
        if not source.path.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(source.data)):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.add(node.module.split(".")[0])
    return sorted(imports - {"__future__", "shinka"})


def prepare_shinka_sources(
    archive_bytes: bytes, *, broker_source_bytes: bytes, transport_source_bytes: bytes,
) -> ShinkaPreparedProfile:
    """Prepare exactly ten modules and two license notices, never importing them."""
    _pinned(archive_bytes, ARCHIVE_BYTES, ARCHIVE_SHA256, "archive_pin_mismatch")
    original = _read_archive_members(
        archive_bytes, expected_files=ARCHIVE_FILES, expected_bytes=ARCHIVE_CONTENT_BYTES,
        selected=set(_ORIGINAL_PINS),
    )
    for path, (size, digest) in _ORIGINAL_PINS.items():
        _pinned(original[path], size, digest, "upstream_source_mismatch")
    try:
        broker, segments = _shared.generate_target_broker(broker_source_bytes, transport_source_bytes)
    except _shared.OpenEvolvePreparationError:
        _fail("broker_source_drift")
    initializer = _asset("package_init.py")
    entrypoint = _asset("fixed_entrypoint.py")
    shared_boundary = _shared_boundary_guard(entrypoint)
    lunar_license = _asset("LICENSE.lunar")
    added = {
        "shinka/lunar_fixed.py": entrypoint, "shinka/lunar_fixed_broker.py": broker,
        "LICENSE.lunar": lunar_license,
    }
    replaced = {path for path in original if path.endswith("/__init__.py")}
    prepared = {**original, **dict.fromkeys(replaced, initializer), **added}
    sources = tuple(PreparedSource(path, prepared[path]) for path in sorted(prepared))
    source_records = []
    for source in sources:
        if source.path in {"LICENSE", "LICENSE.lunar"}:
            continue
        old = original.get(source.path)
        source_records.append({
            "path": source.path,
            "module": (source.path.removesuffix("/__init__.py") if source.path.endswith("/__init__.py")
                       else source.path.removesuffix(".py")).replace("/", "."),
            "package": source.path.endswith("/__init__.py"),
            "kind": "added" if old is None else "replaced" if source.path in replaced else "unchanged",
            "original": None if old is None else {"path": source.path, **_identity(old)},
            "result": _identity(source.data),
            "asset": ({"path": "assets/fixed_entrypoint.py", **_identity(entrypoint)}
                      if source.path == "shinka/lunar_fixed.py" else
                      {"path": "assets/package_init.py", **_identity(initializer)}
                      if source.path in replaced else None),
        })
    manifest = {
        "schema": "lunar-shinka-fixed-source-v1", "profile": PROFILE,
        "upstream": {
            "release": "v0.0.7", "commit": "c4568adde253cacf185be3a8412c3c2142761ebe",
            "tree": "02eeb82bf432c312f0c87d9379a4d96c65870b08",
            "archive": _identity(archive_bytes), "archive_regular_files": ARCHIVE_FILES,
            "archive_content_bytes": ARCHIVE_CONTENT_BYTES,
        },
        "broker": {
            "generator": "tools.openevolve_fixed_profile.prepare.generate_target_broker",
            "source": {"path": "src/lunar_evolution/producer_broker_ipc.py", **_identity(broker_source_bytes)},
            "transport": {"path": "src/lunar_evolution/http_transport.py", **_identity(transport_source_bytes)},
            "segments": list(segments),
            "environment": ["LUNAR_PRODUCER_REQUEST_FD", "LUNAR_PRODUCER_RESPONSE_FD"],
        },
        "entrypoint": {
            "module": "shinka.lunar_fixed", "function": "main",
            "marker": "--lunar-rsi-input-v1", "inputs": ["request.json", "memory.json"],
            "settings": ["initial_program", "model", "task"], "max_requests": 1,
            "outputs": ["gen_0/main.py", "programs.sqlite"], "new_grants": [],
            "result_kind": "quiescent_shinka_sqlite_unevaluated_explicit_id",
            "selection": {"program_ids": ["proposal"], "top_k": None},
            "evaluation_performed": False, "correct": False, "combined_score": None,
            "generation": 0,
            "shared_boundary": shared_boundary,
            "sqlite": {"required": True, "serialization_required": True, "runtime_accepted": False},
        },
        "sources": source_records,
        "license": {
            "upstream": {"path": "LICENSE", "kind": "unchanged", "spdx": "Apache-2.0",
                         "original": _identity(original["LICENSE"]), "result": _identity(prepared["LICENSE"])},
            "lunar": {"path": "LICENSE.lunar", "kind": "unchanged", "spdx": "MIT",
                      "source": {"path": "LICENSE", **_identity(lunar_license)},
                      "asset": {"path": "assets/LICENSE.lunar", **_identity(lunar_license)},
                      "result": _identity(lunar_license)},
        },
        "resources": [], "stdlib_direct_imports": _stdlib_imports(sources),
        "claims": {
            "source_only": True, "closure_verified": False, "upstream_imported": False,
            "source_execution_performed": False, "build_performed": False,
            "runtime_execution_performed": False, "production_admission": False,
            "online_publication": False,
        },
    }
    return ShinkaPreparedProfile(sources, _canonical(manifest))
