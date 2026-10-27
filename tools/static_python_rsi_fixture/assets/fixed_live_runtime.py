"""Pinned supplement: capture this interpreter's runtime facts before solver entry."""
# Appended only by the separately selected runtime-observation source composer.
# ruff: noqa: F821


def _lunar_live_runtime_facts(sys, posix):
    streams = (sys.stdin, sys.stdout, sys.stderr)
    wrapper = sys.modules["_io"].TextIOWrapper
    if any(type(stream) is not wrapper for stream in streams):
        raise RuntimeError("fixed_live_runtime_stdio")
    if (type(sys.argv) is not list or type(sys.orig_argv) is not list
            or len(sys.argv) > 32 or len(sys.orig_argv) > 32
            or any(type(value) is not str or not 0 < len(value) <= 512
                   for value in (*sys.argv, *sys.orig_argv))):
        raise RuntimeError("fixed_live_runtime_argv")
    version = [sys.version_info.major, sys.version_info.minor, sys.version_info.micro]
    facts = {
        "version": version,
        "releaselevel": sys.version_info.releaselevel,
        "serial": sys.version_info.serial,
        "implementation": sys.implementation.name,
        "cache_tag": sys.implementation.cache_tag,
        "abiflags": sys.abiflags,
        "debug_build": hasattr(sys, "gettotalrefcount"),
        "gil_enabled": sys._is_gil_enabled(),
        "platform": sys.platform,
        "architecture": posix.uname().machine,
        "maxsize": sys.maxsize,
        "argv": list(sys.argv),
        "orig_argv": list(sys.orig_argv),
        "hash_randomization": sys.flags.hash_randomization,
        "filesystem_encoding": sys.getfilesystemencoding(),
        "filesystem_errors": sys.getfilesystemencodeerrors(),
        "stdio": [{"encoding": stream.encoding, "errors": stream.errors}
                  for stream in streams],
    }
    # Encode now as well as at return so unrepresentable actual facts refuse;
    # nothing is substituted from the selected expected installation/config.
    _lunar_live_json(facts)
    return facts


def _lunar_collect_live_modules(manifest_sha256):
    # isort: off
    import _imp
    import _sha2
    import posix
    import sys
    # isort: on

    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64
            or any(char not in "0123456789abcdef" for char in manifest_sha256)):
        raise RuntimeError("fixed_live_modules_marker")
    if sys.platform != "linux":
        raise RuntimeError("fixed_live_modules_platform")
    runtime = _lunar_live_runtime_facts(sys, posix)
    original = tuple(sys.modules.items())
    image = _lunar_live_image(posix, _sha2.sha256)
    modules, flags = _lunar_live_snapshot(sys, _imp)
    if (runtime != _lunar_live_runtime_facts(sys, posix)
            or tuple(sys.modules) != tuple(name for name, _module in original)
            or any(sys.modules[name] is not module for name, module in original)):
        raise RuntimeError("fixed_live_runtime_drift")
    payload = {
        "schema": "lunar-static-python-fixed-live-runtime-v1",
        "profile_version": "fixed-" + _LUNAR_LIVE_SOLVER + "-v1",
        "collector_source_sha256": _LUNAR_LIVE_COLLECTOR_SHA256,
        "runtime_source_sha256": _LUNAR_LIVE_RUNTIME_SHA256,
        "collector_profile": "fixed-live-runtime-v1",
        "phase": "explicit-in-image-call", "manifest_sha256": manifest_sha256,
        "pid": posix.getpid(), "image": image, "modules": modules,
        "builtin_names": _LUNAR_LIVE_BUILTINS, "frozen_names": _LUNAR_LIVE_FROZEN,
        "flags": flags, "sys_path": sys.path, "runtime": runtime,
        "claims": {"immutable_custody_verified": False, "production_admission": False,
                   "general_code_origin_protection": False},
    }
    raw = (_lunar_live_json(payload) + "\n").encode("ascii")
    if len(raw) > 128 * 1024:
        raise RuntimeError("fixed_live_modules_size")
    return raw
