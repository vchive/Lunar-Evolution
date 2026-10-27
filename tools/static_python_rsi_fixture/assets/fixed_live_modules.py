"""Embedded in the expanded frozen main; never executed by source preparation."""
# The source composer supplies the finite, hash-bound profile globals.
# ruff: noqa: F821


def _lunar_live_json(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        # All observed names must pass the finite ASCII name gate below.
        if any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise RuntimeError("fixed_live_modules_text")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if type(value) in (tuple, list):
        return "[" + ",".join(_lunar_live_json(item) for item in value) + "]"
    if type(value) is dict:
        return "{" + ",".join(_lunar_live_json(key) + ":" + _lunar_live_json(value[key])
                              for key in sorted(value)) + "}"
    raise RuntimeError("fixed_live_modules_json")


def _lunar_live_name(value):
    if (type(value) is not str or not 0 < len(value) <= 128
            or any(not (char.isascii() and (char.isalnum() or char in "_.")) for char in value)
            or any(not part or part[0].isdigit() for part in value.split("."))):
        raise RuntimeError("fixed_live_modules_name")
    return value


def _lunar_live_image(posix, sha256):
    # This fixed kernel route identifies this executing process, not argv[0],
    # sys.executable, a caller filename or a supplied description. O_NOFOLLOW
    # cannot open the Linux proc executable magic link; no other link is used.
    descriptor = posix.open("/proc/self/exe", posix.O_RDONLY | posix.O_CLOEXEC)
    try:
        before = posix.fstat(descriptor)
        def identity(item):
            return (item.st_dev, item.st_ino, item.st_mode, item.st_size,
                    item.st_mtime_ns, item.st_ctime_ns)
        if (before.st_mode & 0o170000 != 0o100000
                or not 0 < before.st_size <= 128 * 1024 * 1024
                or not before.st_mode & 0o111 or before.st_mode & 0o6000):
            raise RuntimeError("fixed_live_modules_image")
        digest = sha256()
        consumed = 0
        while consumed < before.st_size:
            chunk = posix.read(descriptor, min(65536, before.st_size - consumed))
            if type(chunk) is not bytes or not chunk:
                raise RuntimeError("fixed_live_modules_image")
            consumed += len(chunk)
            digest.update(chunk)
        if (posix.read(descriptor, 1) or identity(posix.fstat(descriptor)) != identity(before)
                or identity(posix.stat("/proc/self/exe")) != identity(before)):
            raise RuntimeError("fixed_live_modules_image_drift")
        return {"device": before.st_dev, "inode": before.st_ino,
                "mode": before.st_mode & 0o7777, "size": consumed,
                "sha256": digest.hexdigest()}
    finally:
        posix.close(descriptor)


def _lunar_live_snapshot(sys, imp):
    if (type(sys.modules) is not dict or not 0 < len(sys.modules) <= 512
            or sys.path != [] or sys.path_hooks != [] or imp.extension_suffixes() != []
            or hasattr(imp, "create_dynamic") or hasattr(imp, "exec_dynamic")
            or sys._stdlib_dir != "/lunar-static-fixture"):
        raise RuntimeError("fixed_live_modules_runtime")
    if (tuple(sorted(sys.builtin_module_names)) != _LUNAR_LIVE_BUILTINS
            or tuple(sorted(imp._frozen_module_names())) != _LUNAR_LIVE_FROZEN):
        raise RuntimeError("fixed_live_modules_inventory")
    expected_flags = {"isolated": 1, "ignore_environment": 1, "no_site": 1,
                      "no_user_site": 1, "utf8_mode": 1, "dont_write_bytecode": 1,
                      "safe_path": True, "dev_mode": False, "optimize": 0}
    flags = {name: getattr(sys.flags, name) for name in expected_flags}
    if flags != expected_flags:
        raise RuntimeError("fixed_live_modules_flags")
    original = tuple(sys.modules.items())
    if any(type(name) is not str for name, _module in original):
        raise RuntimeError("fixed_live_modules_name")
    modules = dict(original)
    bootstrap = modules.get("_frozen_importlib")
    if type(bootstrap) is not type(sys):
        raise RuntimeError("fixed_live_modules_bootstrap")
    namespace = bootstrap.__dict__
    spec_type = namespace.get("ModuleSpec")
    builtin_loader = namespace.get("BuiltinImporter")
    frozen_loader = namespace.get("FrozenImporter")
    if not all(type(value) is type for value in (spec_type, builtin_loader, frozen_loader)):
        raise RuntimeError("fixed_live_modules_bootstrap")
    aliases = dict(_LUNAR_LIVE_ALIASES)
    observed = []
    for name in sorted(modules):
        _lunar_live_name(name)
        module = modules[name]
        if type(module) is not type(sys):
            raise RuntimeError("fixed_live_modules_module")
        values = module.__dict__
        spec = values.get("__spec__")
        canonical = aliases.get(name, name)
        if name != canonical and modules.get(canonical) is not module:
            raise RuntimeError("fixed_live_modules_alias")
        filename = None
        state_record = None
        package_paths = None
        if name == "__main__":
            if spec is not None or values.get("__name__") != "__main__":
                raise RuntimeError("fixed_live_modules_main")
            origin, loader_name = "interpreter", "interpreter"
        else:
            if type(spec) is not spec_type:
                raise RuntimeError("fixed_live_modules_origin")
            facts = spec.__dict__
            module_name = values.get("__name__")
            if (type(facts.get("name")) is not str or type(module_name) is not str
                    or facts.get("name") != canonical
                    or module_name not in {canonical, *(a for a, target in _LUNAR_LIVE_ALIASES
                                                       if target == canonical)}):
                raise RuntimeError("fixed_live_modules_alias")
            origin = facts.get("origin")
            loader = facts.get("loader")
            if values.get("__loader__") is not loader or facts.get("_set_fileattr") is not False:
                raise RuntimeError("fixed_live_modules_origin")
            if (origin == "built-in" and canonical in _LUNAR_LIVE_BUILTINS
                    and loader is builtin_loader and imp.is_builtin(canonical)):
                loader_name = "BuiltinImporter"
                if (facts.get("loader_state") is not None
                        or facts.get("submodule_search_locations") is not None):
                    raise RuntimeError("fixed_live_modules_origin")
            elif (origin == "frozen" and canonical in _LUNAR_LIVE_FROZEN
                  and loader is frozen_loader and imp.is_frozen(canonical)):
                loader_name = "FrozenImporter"
                # CPython's fixed table supplies an original name for every
                # entry. FrozenImporter synthesizes metadata; it does not read
                # this .py pathname. Bootstrap aliases use their original name.
                original_name = {"_frozen_importlib": "importlib._bootstrap",
                                 "_frozen_importlib_external": "importlib._bootstrap_external"}.get(
                                     canonical, canonical)
                package = canonical in _LUNAR_LIVE_PACKAGES
                info = imp.find_frozen(canonical)
                if (type(info) is not tuple or len(info) != 3
                        or info[1] is not package or info[2] != original_name):
                    raise RuntimeError("fixed_live_modules_origin")
                stem = "/lunar-static-fixture/" + original_name.replace(".", "/")
                package_paths = [stem] if package else None
                filename = stem + ("/__init__.py" if package else ".py")
                state = facts.get("loader_state")
                state_record = {"filename": filename, "origname": original_name}
                # Core bootstrap precedes _PySys_UpdateConfig/_stdlib_dir.
                # importlib.__init__ later sets only its public __file__ alias,
                # leaving the bootstrap loader state's filename as None.
                if canonical == "_frozen_importlib":
                    state_record["filename"] = None
                    if "importlib._bootstrap" not in modules:
                        filename = None
                if (type(state) is not type(sys.implementation)
                        or state.__dict__ != state_record
                        or facts.get("submodule_search_locations") != package_paths):
                    raise RuntimeError("fixed_live_modules_origin")
            else:
                raise RuntimeError("fixed_live_modules_origin")
        if (values.get("__file__") != filename
                or values.get("__path__") != package_paths):
            raise RuntimeError("fixed_live_modules_external")
        observed.append({"name": name, "origin": origin, "canonical_name": canonical,
                         "file": filename, "loader": loader_name,
                         "loader_state": state_record, "package_paths": package_paths})
    # No selected subset is accepted. The entire table's keys and original
    # object identities must still match at the end of this observation window.
    if (tuple(sys.modules) != tuple(name for name, _module in original)
            or any(sys.modules[name] is not module for name, module in original)):
        raise RuntimeError("fixed_live_modules_table_drift")
    return observed, flags


def _lunar_collect_live_modules(manifest_sha256):
    # _sha2 is a builtin in this fixed image; keep the native imports together.
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
    # Collector imports occur before the complete table snapshot, so they are
    # included rather than hidden by a caller-supplied module list.
    image = _lunar_live_image(posix, _sha2.sha256)
    modules, flags = _lunar_live_snapshot(sys, _imp)
    payload = {"schema": "lunar-static-python-fixed-live-modules-v1",
               "profile_version": "fixed-" + _LUNAR_LIVE_SOLVER + "-v1",
               "collector_source_sha256": _LUNAR_LIVE_COLLECTOR_SHA256,
               "collector_profile": "fixed-live-modules-v1",
               "phase": "explicit-in-image-call", "manifest_sha256": manifest_sha256,
               "pid": posix.getpid(), "image": image, "modules": modules,
               "builtin_names": _LUNAR_LIVE_BUILTINS, "frozen_names": _LUNAR_LIVE_FROZEN,
               "flags": flags, "sys_path": sys.path,
               "claims": {"immutable_custody_verified": False, "production_admission": False,
                          "general_code_origin_protection": False}}
    raw = (_lunar_live_json(payload) + "\n").encode("ascii")
    if len(raw) > 128 * 1024:
        raise RuntimeError("fixed_live_modules_size")
    # No new sink is authorized by this source profile. A trusted in-image
    # caller receives bytes; stdout, broker requests and solver output remain
    # untouched. A future launcher must bind its separately granted sink.
    return raw
