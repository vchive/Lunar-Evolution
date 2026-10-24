"""Finite create-only source plan; never a build, installation or runtime gate."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

PROFILE = "rsi-marker-launch-v1"
_ROOT = Path(__file__).resolve().parents[2]
# Reviewed constants, not digests derived from whichever source happens to exist.
_SOURCE_PINS = (
    ("tools/static_python_fixture/assets/frozen_main.py", 7329,
     "6d1f3aaf075b62c7d5c36128e6cfff8dce6f449a9086fc12dcd65b83b6ce8825"),
    ("tools/static_python_fixture/assets/getpath.c", 1288,
     "a067fe6dc9a2bd63d5847e29b14c9b7c30d42432dcf1f505bb461feae6b2d722"),
    ("tools/static_python_fixture/assets/launcher.c", 1546,
     "79a4462386f54dfe36ea87838523fe652bbc59e72db4505175fd3b6870837735"),
    ("tools/static_python_fixture/assets/lunar_fixture_profile.h", 179,
     "f07987ceb32941684d75236910676b53f60e39ec78bfb4f9d34cd6ba7f79095e"),
    ("tools/static_python_fixture/assets/pipe.c", 3030,
     "60af02a3f3a5e5dbfab6926a968acefa41ff2054e6fa0f38e53f4ec883f69cd2"),
    ("tools/static_python_fixture/assets/profile.c", 3452,
     "3a4b2cbdb57322820aef04aaf55b92a9e085db52818f7cee4e48c33bb5ae98db"),
    ("tools/static_python_fixture/reviewed-build-inputs.json", 80050,
     "6e2d35188aadc5e00f2d6eb98e90b2f9e34f3a425c8f3575b759f52c3e38ba5c"),
    ("tools/static_python_fixture/profile.py", 6432,
     "6af684014adb22b2619e51bfcae68a5ffb87e56006f965fca3f0fd1f5f1695b4"),
    ("tools/static_python_fixture/recipe.py", 12853,
     "9cb6474c9f06de8c13d9168bbaa7c3a4bed5c9b7ddfb4b652001ebe340221f9c"),
    ("tools/static_python_rsi_fixture/assets/frozen_main.py", 432,
     "fc6f3b4908d284a57b26a9434018f8394d9f566958081d77d509da010eda5069"),
    ("tools/static_python_rsi_fixture/assets/launcher.c", 1740,
     "3a81211b2869727469c1de3bfad79144d11f17c99ccc100c3c48015c0398a0e0"),
)
_ASSETS = (
    "launcher.c", "pipe.c", "profile.c", "getpath.c", "lunar_fixture_profile.h", "frozen_main.py",
)
_FALSE_CLAIMS = (
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
)


class RSILaunchSourceError(ValueError):
    """Fixed source preparation refusal, without caller path disclosure."""

    def __init__(self, reason: str) -> None:
        super().__init__("static_python_rsi_launch_" + reason)


def _no_symlink(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise RSILaunchSourceError("symlink")


def _record(path: str, raw: bytes) -> dict[str, object]:
    return {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _read_sources() -> tuple[dict[str, bytes], list[dict[str, object]]]:
    sources: dict[str, bytes] = {}
    records: list[dict[str, object]] = []
    for name, size, digest in _SOURCE_PINS:
        path = _ROOT / name
        _no_symlink(path)
        if not path.is_file():
            raise RSILaunchSourceError("source_missing")
        with path.open("rb") as stream:
            raw = stream.read(size + 1)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise RSILaunchSourceError("source_drift")
        sources[name] = raw
        records.append({**_record(name, raw), "origin": (
            "owned" if name.startswith("tools/static_python_rsi_fixture/") else "original"
        )})
    return sources, records


def _literal_profile(raw: bytes) -> tuple[dict[str, object], dict[str, object]]:
    # Read only literal assignments from the independently pinned snapshot. Never
    # import/execute a profile whose disk bytes have not passed the source gate.
    names = {
        "PRECONFIG", "CONFIG", "FROZEN", "ALIASES", "CORE_BUILTINS", "STATIC_ADDITIONS",
        "CODEC_ALIASES", "EXPECTED_STARTUP_MODULES",
    }
    values = {}
    for node in ast.parse(raw.decode("utf-8")).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names):
            values[node.targets[0].id] = ast.literal_eval(node.value)
    if set(values) != names:
        raise RSILaunchSourceError("source_drift")
    values["BUILTINS"] = values["CORE_BUILTINS"] + tuple(values["STATIC_ADDITIONS"])
    initialization = {
        "preconfig": values["PRECONFIG"], "config": values["CONFIG"],
        "builtins": sorted(values["BUILTINS"]),
        "frozen": [{"name": n, "generator_id": g, "source": s, "package": p}
                   for n, g, s, p in sorted(values["FROZEN"])],
        "aliases": [list(item) for item in values["ALIASES"]],
        "codec_aliases": list(values["CODEC_ALIASES"]),
        "startup_module_expectation": sorted(values["EXPECTED_STARTUP_MODULES"]),
    }
    return initialization, values


def _expand_encoder(raw: bytes, values: dict[str, object]) -> bytes:
    replacements = {
        "__LUNAR_EXPECTED_BUILTINS__": repr(list(values["BUILTINS"])),
        "__LUNAR_EXPECTED_FROZEN__": repr([item[0] for item in values["FROZEN"]]),
        "__LUNAR_EXPECTED_MODULES__": repr(list(values["EXPECTED_STARTUP_MODULES"])),
    }
    text = raw.decode("utf-8")
    for name, replacement in replacements.items():
        if text.count(name) != 1:
            raise RSILaunchSourceError("source_drift")
        text = text.replace(name, replacement)
    return text.encode("utf-8")


def _write_readback(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        os.fchmod(stream.fileno(), 0o444)
    _no_symlink(path)
    if path.read_bytes() != raw:
        raise RSILaunchSourceError("readback_drift")


def emit_rsi_launch_source_plan(destination: Path) -> Path:
    """Return a source-only manifest; output is create-only and has no build driver.

    Source digests do not establish frozen bytecode, ELF, installation acceptance,
    execution, input consumption or any protection/admission authority.
    """
    try:
        sources, records = _read_sources()
        initialization, values = _literal_profile(sources["tools/static_python_fixture/profile.py"])
        destination = Path(os.path.abspath(destination))
        _no_symlink(destination)
        if destination.exists():
            raise RSILaunchSourceError("destination_exists")
        old = "tools/static_python_fixture/assets/"
        owned = "tools/static_python_rsi_fixture/assets/"
        assets = {name: sources[old + name] for name in _ASSETS}
        assets["launcher.c"] = sources[owned + "launcher.c"]
        assets["frozen_main.py"] = (
            _expand_encoder(sources[old + "frozen_main.py"], values)
            + b"\n" + sources[owned + "frozen_main.py"]
        )
        facts = {
            "schema": "lunar-static-python-rsi-launch-source-plan-v1", "profile": PROFILE,
            "launch_policy": {
                "argc": 3, "marker": "--lunar-rsi-input-v1", "marker_index": 1,
                "manifest_digest_index": 2, "manifest_digest_syntax": "[0-9a-f]{64}",
                "frozen_entrypoint": "_rsi_launch", "baseline_case": "baseline",
                "environment_selector": False, "input_reads": [],
            },
            "initialization_profile": initialization, "source_inputs": records,
            "emitted_sources": [_record("assets/" + name, raw) for name, raw in assets.items()],
            "claims": dict.fromkeys(_FALSE_CLAIMS, False),
            "artifact_state": "pending-builder", "startup_state": "not-executed",
        }
        manifest_bytes = (json.dumps(facts, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "assets").mkdir()
        for name, raw in assets.items():
            _write_readback(destination / "assets" / name, raw)
        manifest_path = destination / "manifest.json"
        _write_readback(manifest_path, manifest_bytes)
        # Recheck every source and the whole output set before reporting completion.
        final_sources, final_records = _read_sources()
        if final_sources != sources or final_records != records:
            raise RSILaunchSourceError("source_drift")
        if (sorted(path.name for path in destination.iterdir()) != ["assets", "manifest.json"]
                or sorted(path.name for path in (destination / "assets").iterdir()) != sorted(_ASSETS)):
            raise RSILaunchSourceError("output_drift")
        for name, raw in assets.items():
            path = destination / "assets" / name
            _no_symlink(path)
            if path.read_bytes() != raw:
                raise RSILaunchSourceError("readback_drift")
        _no_symlink(manifest_path)
        if manifest_path.read_bytes() != manifest_bytes:
            raise RSILaunchSourceError("readback_drift")
        return manifest_path
    except RSILaunchSourceError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise RSILaunchSourceError("preparation_failed") from exc
