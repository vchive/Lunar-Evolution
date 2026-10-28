"""Expanded in-image module collector source and detached observation comparison.

Only the opt-in frozen callable observes a live interpreter. This host-side
consumer compares supplied bytes; it never authenticates who supplied them or
grants build, custody, process, runtime or production authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import static_python_fixed_profile as profile
from .static_python_installation import STATIC_PYTHON_STARTUP_MODULES
from .static_python_runtime_startup import (
    StaticPythonRuntimeStartupError,
    parse_static_python_runtime_startup,
)

FIXED_LIVE_MODULES_PROFILE = "fixed-live-modules-v1"
FIXED_LIVE_PRIVATE_SINK_PROFILE = "fixed-live-modules-private-sink-v1"
FIXED_LIVE_RUNTIME_SINK_PROFILE = "fixed-live-runtime-private-sink-v1"
FIXED_LIVE_RUNTIME_PROFILE = "fixed-live-runtime-v1"
FIXED_LIVE_RUNTIME_SCHEMA = "lunar-static-python-fixed-live-runtime-v1"
FIXED_LIVE_RUNTIME_SOURCE_BYTES = 3776
FIXED_LIVE_RUNTIME_SOURCE_SHA256 = "0fbe050a70987bf78fe61e2d8d3ebf67c3d830c5502916e1b8192cc055f01a9d"
FIXED_LIVE_SINK_LAUNCHER_PATH = "runtime/launcher_live_sink.c"
FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES = 4552
FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256 = "b48a93c5f862cf9621f70ec124a012060ba8944c33ea5745be56829a51e0fb53"
FIXED_LIVE_MODULES_SCHEMA = "lunar-static-python-fixed-live-modules-v1"
FIXED_LIVE_COLLECTOR_SOURCE_BYTES = 11551
FIXED_LIVE_COLLECTOR_SOURCE_SHA256 = "c209366db5706c95e749f7c112ea5d8a547b2512e61629bce049196508c1bd38"
MAX_FIXED_LIVE_MODULES_BYTES = 128 * 1024
_FLAGS = {"isolated": 1, "ignore_environment": 1, "no_site": 1,
          "no_user_site": 1, "utf8_mode": 1, "dont_write_bytecode": 1,
          "safe_path": True, "dev_mode": False, "optimize": 0}
_FIELDS = frozenset({"schema", "profile_version", "collector_profile", "collector_source_sha256",
                     "phase", "manifest_sha256", "pid", "image", "modules", "builtin_names",
                     "frozen_names", "flags", "sys_path", "claims"})
_REASONS = frozenset({"invalid", "source", "pin", "image", "runtime", "inventory", "module",
                      "startup", "claims", "json", "profile", "owner", "schema"})


class FixedPythonLiveModulesError(ValueError):
    """A fixed refusal code, without caller bytes or chained exception context."""

    def __init__(self, reason: str) -> None:
        reason = reason if type(reason) is str and reason in _REASONS else "invalid"
        self.reason = "static_python_fixed_live_modules_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    pass


def _fail(reason: str) -> None:
    raise _Refusal(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _compose(solver: str, frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
             aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...],
             collector_source: bytes, runtime_observation_source: bytes | None = None) -> bytes:
    if type(solver) is not str or solver not in {"openevolve", "shinka"}:
        _fail("profile")
    if (type(collector_source) is not bytes or len(collector_source) != FIXED_LIVE_COLLECTOR_SOURCE_BYTES
            or _sha(collector_source) != FIXED_LIVE_COLLECTOR_SOURCE_SHA256):
        _fail("source")
    if runtime_observation_source is not None and (
        type(runtime_observation_source) is not bytes
        or len(runtime_observation_source) != FIXED_LIVE_RUNTIME_SOURCE_BYTES
        or _sha(runtime_observation_source) != FIXED_LIVE_RUNTIME_SOURCE_SHA256
    ):
        _fail("source")
    for names, maximum in ((frozen_names, 256), (builtin_names, 128)):
        if type(names) is not tuple or not 0 < len(names) <= maximum:
            _fail("inventory")
        for name in names:
            profile._label(name)
        if names != tuple(sorted(set(names))):
            _fail("inventory")
    if type(aliases) is not tuple or len(aliases) > 32:
        _fail("inventory")
    for alias in aliases:
        if type(alias) is not tuple or len(alias) != 2:
            _fail("inventory")
        for name in alias:
            profile._label(name)
        if alias[1] not in frozen_names or alias[0] in frozen_names + builtin_names:
            _fail("inventory")
    if (aliases != tuple(sorted(set(aliases)))
            or len({name for name, _target in aliases}) != len(aliases)):
        _fail("inventory")
    if (type(frozen_packages) is not tuple or frozen_packages != tuple(sorted(set(frozen_packages)))
            or not set(frozen_packages) <= set(frozen_names)):
        _fail("inventory")
    prefix = (
        'def _rsi_launch(manifest_sha256):\n'
        '    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64\n'
        '            or any(c not in "0123456789abcdef" for c in manifest_sha256)):\n'
        '        raise ValueError("invalid RSI manifest digest syntax")\n'
        f'    from {solver}.lunar_fixed import main\n'
        '    return main(["--lunar-rsi-input-v1", manifest_sha256])\n'
        '\n'
        f'_LUNAR_LIVE_SOLVER = {solver!r}\n'
        f'_LUNAR_LIVE_FROZEN = {frozen_names!r}\n'
        f'_LUNAR_LIVE_BUILTINS = {builtin_names!r}\n'
        f'_LUNAR_LIVE_ALIASES = {aliases!r}\n'
        f'_LUNAR_LIVE_PACKAGES = {frozen_packages!r}\n'
        f'_LUNAR_LIVE_COLLECTOR_SHA256 = {FIXED_LIVE_COLLECTOR_SOURCE_SHA256!r}\n'
        '\n'
    ).encode("ascii")
    if runtime_observation_source is None:
        return prefix + collector_source
    return (prefix + collector_source
            + f'\n_LUNAR_LIVE_RUNTIME_SHA256 = {FIXED_LIVE_RUNTIME_SOURCE_SHA256!r}\n\n'.encode("ascii")
            + runtime_observation_source)


def compose_fixed_python_live_main(
    solver: str, *, frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
    aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...], collector_source: bytes,
    runtime_observation_source: bytes | None = None,
) -> bytes:
    """Compose a separately selected frozen source; never import or execute it."""
    try:
        return _compose(solver, frozen_names, builtin_names, aliases, frozen_packages,
                        collector_source, runtime_observation_source)
    except _Refusal as exc:
        reason = str(exc)
    except profile._Refusal:
        reason = "schema"
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        reason = "source"
    raise FixedPythonLiveModulesError(reason) from None


@dataclass(frozen=True, slots=True)
class FixedPythonLiveModuleComparison:
    """Compared observations, not authenticated runtime or immutable custody."""

    canonical_bytes: bytes
    observation_sha256: str
    installation_sha256: str
    startup_sha256: str
    module_names: tuple[str, ...]
    live_runtime_authenticated: bool = False
    immutable_custody_verified: bool = False
    production_admission: bool = False


def _compare_live_payload(
    installation: profile.FixedPythonInstallation, raw: bytes, *, image: bytes,
    runtime_main_source: bytes, expected_installation_sha256: str,
    expected_observation_sha256: str, runtime_observation: bool = False,
    producer_lifecycle: bool = False,
) -> tuple[profile.FixedPythonInstallation, dict, tuple[str, ...]]:
    installed = profile._reparse(installation, expected_installation_sha256)
    profile.verify_fixed_python_image(installed, image, expected_installation_sha256=expected_installation_sha256)
    if (type(runtime_main_source) is not bytes
            or not FIXED_LIVE_COLLECTOR_SOURCE_BYTES < len(runtime_main_source) <= 64 * 1024):
        _fail("source")
    source = next(record for record in installed.to_dict()["frozen_modules"]
                  if record["name"] == "_lunar_static_main")["source"]
    if source != {"path": "runtime/frozen_main.py", "size": len(runtime_main_source),
                  "sha256": _sha(runtime_main_source)}:
        _fail("source")
    if (type(runtime_observation) is not bool or type(producer_lifecycle) is not bool
            or producer_lifecycle and not runtime_observation):
        _fail("profile")
    collector_offset = FIXED_LIVE_COLLECTOR_SOURCE_BYTES
    supplement = None
    if runtime_observation:
        supplement = runtime_main_source[-FIXED_LIVE_RUNTIME_SOURCE_BYTES:]
        separator = f'\n_LUNAR_LIVE_RUNTIME_SHA256 = {FIXED_LIVE_RUNTIME_SOURCE_SHA256!r}\n\n'.encode("ascii")
        collector_offset += len(separator) + FIXED_LIVE_RUNTIME_SOURCE_BYTES
    solver = installed.profile_version.removeprefix("fixed-").removesuffix("-v1")
    expected_main = _compose(
        solver, tuple(sorted(installed.frozen_names)), installed.builtin_names,
        installed.aliases,
        tuple(sorted(record["name"] for record in installed.to_dict()["frozen_modules"] if record["package"])),
        runtime_main_source[-collector_offset:][:FIXED_LIVE_COLLECTOR_SOURCE_BYTES], supplement,
    )
    if producer_lifecycle:
        from .static_python_producer_completion_source import (
            FIXED_PRODUCER_LIFECYCLE_PROFILE,
            compose_fixed_producer_completion_main,
        )

        expected_main = compose_fixed_producer_completion_main(
            solver, startup_main_source=expected_main,
            frozen_names=tuple(sorted(installed.frozen_names)), builtin_names=installed.builtin_names,
            aliases=installed.aliases,
            frozen_packages=tuple(sorted(record["name"] for record in installed.to_dict()["frozen_modules"]
                                         if record["package"])),
            profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
        )
    if runtime_main_source != expected_main:
        _fail("source")
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_FIXED_LIVE_MODULES_BYTES
            or not raw.endswith(b"\n") or _sha(raw) != expected_observation_sha256):
        _fail("pin")
    fields = _FIELDS | {"runtime", "runtime_source_sha256"} if runtime_observation else _FIELDS
    payload = profile._object(profile._json(raw[:-1], MAX_FIXED_LIVE_MODULES_BYTES), fields)
    if runtime_observation and payload["runtime_source_sha256"] != FIXED_LIVE_RUNTIME_SOURCE_SHA256:
        _fail("source")
    schema = FIXED_LIVE_RUNTIME_SCHEMA if runtime_observation else FIXED_LIVE_MODULES_SCHEMA
    collector_profile = FIXED_LIVE_RUNTIME_PROFILE if runtime_observation else FIXED_LIVE_MODULES_PROFILE
    if (payload["schema"] != schema
            or payload["collector_profile"] != collector_profile
            or payload["profile_version"] != installed.profile_version
            or payload["collector_source_sha256"] != FIXED_LIVE_COLLECTOR_SOURCE_SHA256
            or payload["phase"] != "explicit-in-image-call"):
        _fail("profile")
    claims = profile._object(payload["claims"], {"immutable_custody_verified", "production_admission",
                                                 "general_code_origin_protection"})
    if any(value is not False for value in claims.values()):
        _fail("claims")
    if (profile._canonical(payload["flags"]) != profile._canonical(_FLAGS)
            or payload["sys_path"] != []):
        _fail("runtime")
    if (payload["builtin_names"] != list(installed.builtin_names)
            or payload["frozen_names"] != sorted(installed.frozen_names)):
        _fail("inventory")
    observed_image = profile._object(payload["image"], {"device", "inode", "mode", "size", "sha256"})
    for field, minimum in (("device", 0), ("inode", 1), ("pid", 1)):
        value = payload[field] if field == "pid" else observed_image[field]
        if type(value) is not int or not minimum <= value < 2**63:
            _fail("owner")
    declared = installed.to_dict()["image"]
    if any(observed_image[field] != declared[field] or type(observed_image[field]) is not type(declared[field])
           for field in ("mode", "size", "sha256")):
        _fail("image")
    origins = {name: ("frozen", name, "FrozenImporter") for name in installed.frozen_names}
    origins.update({name: ("built-in", name, "BuiltinImporter") for name in installed.builtin_names})
    origins["__main__"] = ("interpreter", "__main__", "interpreter")
    for alias, target in installed.aliases:
        origins[alias] = origins[target]
    packages = {record["name"] for record in installed.to_dict()["frozen_modules"] if record["package"]}
    raw_modules = profile._vector(payload["modules"], 512)
    bootstrap_alias = any(type(item) is dict and item.get("name") == "importlib._bootstrap" for item in raw_modules)
    names = []
    for module in raw_modules:
        profile._object(module, {"name", "origin", "canonical_name", "file", "loader", "loader_state", "package_paths"})
        name = profile._label(module["name"])
        if name not in origins or (module["origin"], module["canonical_name"], module["loader"]) != origins[name]:
            _fail("module")
        origin, canonical, _loader = origins[name]
        filename = state_record = package_paths = None
        if origin == "frozen":
            original = {"_frozen_importlib": "importlib._bootstrap",
                        "_frozen_importlib_external": "importlib._bootstrap_external"}.get(canonical, canonical)
            stem = "/lunar-static-fixture/" + original.replace(".", "/")
            package_paths = [stem] if canonical in packages else None
            filename = stem + ("/__init__.py" if canonical in packages else ".py")
            state_record = {"filename": filename, "origname": original}
            if canonical == "_frozen_importlib":
                state_record["filename"] = None
                if not bootstrap_alias:
                    filename = None
        if (module["file"] != filename or module["loader_state"] != state_record
                or module["package_paths"] != package_paths):
            _fail("module")
        names.append(name)
    if (names != sorted(set(names))
            or not set(STATIC_PYTHON_STARTUP_MODULES) | {"_imp", "_sha2", "posix", "sys"} <= set(names)):
        _fail("inventory")
    return installed, payload, tuple(names)


def compare_fixed_python_live_modules(
    installation: profile.FixedPythonInstallation, raw: bytes, *, image: bytes,
    runtime_main_source: bytes, startup_raw: bytes, expected_installation_sha256: str,
    expected_observation_sha256: str, expected_startup_sha256: str,
    expected_build_closure_sha256: str, expected_binding_sha256: str,
    expected_launch_intent_sha256: str, expected_sealed_material_sha256: str,
) -> FixedPythonLiveModuleComparison:
    """Compare full captured-table wire and actual image bytes; no live authentication.

    A complete table is collected by the in-image callable, never by choosing an
    available-module subset. Supplied JSON alone cannot prove that callable ran;
    accepted custody, a trusted launch/sink and lifecycle evidence remain needed.
    """
    try:
        for pin in (expected_observation_sha256, expected_startup_sha256,
                    expected_build_closure_sha256, expected_binding_sha256,
                    expected_launch_intent_sha256, expected_sealed_material_sha256):
            profile._digest(pin)
        installed, payload, names = _compare_live_payload(
            installation, raw, image=image, runtime_main_source=runtime_main_source,
            expected_installation_sha256=expected_installation_sha256,
            expected_observation_sha256=expected_observation_sha256,
        )
        observed_image = payload["image"]
        declared = installed.to_dict()["image"]
        if type(startup_raw) is not bytes or len(startup_raw) > 256 * 1024 or _sha(startup_raw) != expected_startup_sha256:
            _fail("pin")
        startup = parse_static_python_runtime_startup(
            startup_raw, expected_build_closure_sha256=expected_build_closure_sha256,
            expected_binding_sha256=expected_binding_sha256,
            expected_launch_intent_sha256=expected_launch_intent_sha256,
        ).to_dict()
        if (startup["fixture_case"] != "baseline"
                or startup["installation_version"] != installed.installation_version
                or startup["owner"] != {
                    "device": observed_image["device"], "inode": observed_image["inode"],
                    "mode": declared["mode"],
                    "executable": {key: declared[key] for key in ("path", "size", "sha256")},
                }
                or startup["marker"]["value"] != payload["manifest_sha256"]
                or startup["loader"]["sealed_material_sha256"] != expected_sealed_material_sha256):
            _fail("startup")
        return FixedPythonLiveModuleComparison(
            raw, expected_observation_sha256, expected_installation_sha256,
            expected_startup_sha256, tuple(names),
        )
    except _Refusal as exc:
        reason = str(exc)
    except profile._Refusal:
        reason = "schema"
    except profile.FixedPythonProfileError:
        reason = "image"
    except StaticPythonRuntimeStartupError:
        reason = "startup"
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError, StopIteration):
        reason = "json"
    raise FixedPythonLiveModulesError(reason) from None


@dataclass(frozen=True, slots=True)
class FixedPythonBoundLiveModules:
    """Original private-pipe comparison, without custody/admission authority."""

    canonical_bytes: bytes
    observation_sha256: str
    installation_sha256: str
    image_device: int
    image_inode: int
    target_pid: int
    manifest_sha256: str
    module_names: tuple[str, ...]
    live_runtime_authenticated: bool = False
    immutable_custody_verified: bool = False
    production_admission: bool = False


def compare_fixed_python_bound_live_modules(
    installation: profile.FixedPythonInstallation, raw: bytes, *, image: bytes,
    runtime_main_source: bytes, expected_installation_sha256: str,
    expected_image_device: int, expected_image_inode: int, expected_target_pid: int,
    expected_manifest_sha256: str, runtime_observation: bool = False,
    producer_lifecycle: bool = False,
) -> FixedPythonBoundLiveModules:
    """Compare an original native sink against its original sealed target/argv.

    This does not fabricate startup observations or inherit startup authority.
    Callers retain process ownership and must supply the original held image
    identity and native target PID, rather than values parsed from this wire.
    """
    try:
        profile._digest(expected_manifest_sha256)
        for value, minimum in ((expected_image_device, 0), (expected_image_inode, 1),
                               (expected_target_pid, 1)):
            if type(value) is not int or not minimum <= value < 2**63:
                _fail("owner")
        observed_sha256 = _sha(raw)
        _installed, payload, names = _compare_live_payload(
            installation, raw, image=image, runtime_main_source=runtime_main_source,
            expected_installation_sha256=expected_installation_sha256,
            expected_observation_sha256=observed_sha256, runtime_observation=runtime_observation,
            producer_lifecycle=producer_lifecycle,
        )
        if (payload["image"]["device"] != expected_image_device
                or payload["image"]["inode"] != expected_image_inode
                or payload["pid"] != expected_target_pid):
            _fail("owner")
        if payload["manifest_sha256"] != expected_manifest_sha256:
            _fail("startup")
        return FixedPythonBoundLiveModules(
            raw, observed_sha256, expected_installation_sha256,
            expected_image_device, expected_image_inode, expected_target_pid,
            expected_manifest_sha256, names,
        )
    except _Refusal as exc:
        reason = str(exc)
    except profile._Refusal:
        reason = "schema"
    except profile.FixedPythonProfileError:
        reason = "image"
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError, StopIteration):
        reason = "json"
    raise FixedPythonLiveModulesError(reason) from None
