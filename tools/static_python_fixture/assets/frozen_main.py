"""Fixed inert Python work; observation bytes are produced by this Python code."""

import _imp
import sys

import _lunar_fixture_pipe

# Filled from the reviewed finite manifest before same-source C freezing.
_EXPECTED_BUILTINS = __LUNAR_EXPECTED_BUILTINS__  # noqa: F821
_EXPECTED_FROZEN = __LUNAR_EXPECTED_FROZEN__  # noqa: F821
_EXPECTED_MODULES = __LUNAR_EXPECTED_MODULES__  # noqa: F821


def _json(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        escaped = []
        for character in value:
            number = ord(character)
            if character in ('"', "\\"):
                escaped.append("\\" + character)
            elif number < 32 or number > 126:
                escaped.append(f"\\u{number:04x}")
            else:
                escaped.append(character)
        return '"' + "".join(escaped) + '"'
    if type(value) in (list, tuple):
        return "[" + ",".join(_json(item) for item in value) + "]"
    if type(value) is dict:
        return "{" + ",".join(_json(key) + ":" + _json(value[key])
                              for key in sorted(value)) + "}"
    raise TypeError("unsupported fixture observation")


def _refused(operation):
    try:
        operation()
    except ImportError:
        return True
    raise RuntimeError("non-inventory loader was admitted")


def _loader_negative():
    external = sys.modules["_frozen_importlib_external"]
    bootstrap = sys.modules["_frozen_importlib"]
    source = external.SourceFileLoader("lunar_decoy_source", "./readable-decoys/decoy.py")
    bytecode = external.SourcelessFileLoader("lunar_decoy_bytecode", "./readable-decoys/decoy.pyc")
    extension = external.ExtensionFileLoader("lunar_decoy_extension", "./readable-decoys/decoy.so")
    spec = bootstrap.ModuleSpec("lunar_decoy_extension", extension)
    direct = [
        _refused(lambda: source.get_code("lunar_decoy_source")),
        _refused(lambda: source.exec_module(sys.modules["__main__"])),
        _refused(lambda: bytecode.get_code("lunar_decoy_bytecode")),
        _refused(lambda: bytecode.exec_module(sys.modules["__main__"])),
        _refused(lambda: extension.create_module(spec)),
        _refused(lambda: extension.exec_module(sys.modules["__main__"])),
        _refused(lambda: external.PathFinder.find_spec("lunar_decoy_source")),
        _refused(lambda: external.FileFinder("./readable-decoys").find_spec("lunar_decoy_source")),
    ]
    before = list(sys.path)
    try:
        sys.path[:] = ["./readable-decoys", "./readable-decoys/decoy.zip"]
        ordinary = [_refused(lambda name=name: __import__(name)) for name in
                    ("lunar_decoy_source", "lunar_decoy_bytecode", "lunar_decoy_extension",
                     "lunar_decoy_zip", "zipimport", "site", "runpy")]
    finally:
        sys.path[:] = before
    return {"direct": direct, "ordinary": ordinary}


def _main(fixture_case):
    if fixture_case not in ("baseline", "loader-negative"):
        raise ValueError("unknown fixed fixture case")
    builtin_names = tuple(sorted(sys.builtin_module_names))
    frozen_names = tuple(sorted(_imp._frozen_module_names()))
    module_names = tuple(sorted(sys.modules))
    if builtin_names != tuple(sorted(_EXPECTED_BUILTINS)):
        raise RuntimeError("builtin inventory drift")
    if frozen_names != tuple(sorted(_EXPECTED_FROZEN)):
        raise RuntimeError("frozen inventory drift")
    if module_names != tuple(sorted(_EXPECTED_MODULES)):
        raise RuntimeError("startup closure drift")
    if sys.path or sys.path_hooks or _imp.extension_suffixes():
        raise RuntimeError("external loader configuration drift")
    if hasattr(_imp, "create_dynamic") or hasattr(_imp, "exec_dynamic"):
        raise RuntimeError("dynamic extension entry point retained")
    origins = {}
    for name in module_names:
        module = sys.modules[name]
        spec = getattr(module, "__spec__", None)
        origins[name] = {
            "origin": getattr(spec, "origin", None),
            "file": getattr(module, "__file__", None),
        }
    computed = sum(number * number for number in range(1, 10))
    if computed != 285:
        raise RuntimeError("Python computation failed")
    flags = {name: getattr(sys.flags, name) for name in
             ("isolated", "ignore_environment", "no_site", "no_user_site", "utf8_mode",
              "dont_write_bytecode", "safe_path", "dev_mode", "optimize", "hash_randomization")}
    negative = _loader_negative() if fixture_case == "loader-negative" else None
    request = (b'{"protocol":"lunar-producer-broker-ipc-v1","request_id":"req-1",'
               b'"body_base64":"aGVsbG8="}\n')
    response = _lunar_fixture_pipe.exchange(request)
    if (b'"status":"completed"' not in response or b'"request_id":"req-1"' not in response
            or b'"protocol":"lunar-producer-broker-ipc-v1"' not in response):
        raise RuntimeError("broker response did not complete fixed request")
    observation = {
        "schema": "lunar-static-python-observation-v1", "fixture_case": fixture_case,
        "computed": computed, "version_info": list(sys.version_info),
        "cache_tag": sys.implementation.cache_tag, "flags": flags, "origins": origins,
        "builtin_names": builtin_names, "frozen_names": frozen_names, "sys_path": sys.path,
        "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "exec_prefix": sys.exec_prefix, "base_exec_prefix": sys.base_exec_prefix,
        "stdlib_dir": sys._stdlib_dir, "argv": sys.argv, "orig_argv": sys.orig_argv,
        "filesystem_encoding": sys.getfilesystemencoding(),
        "filesystem_errors": sys.getfilesystemencodeerrors(),
        "stdio_encoding": sys.stdout.encoding, "stdio_errors": sys.stdout.errors,
        "stderr_errors": sys.stderr.errors, "loader_negative": negative,
        "broker_response_bytes": len(response), "runtime_load_protection": False,
        "production_admission": False, "general_code_origin_protection": False,
    }
    sys.stdout.write(_json(observation) + "\n")
    sys.stdout.flush()
