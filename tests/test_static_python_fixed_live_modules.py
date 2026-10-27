"""Local synthetic metadata/image vectors; never a live static-runtime acceptance."""

from __future__ import annotations

import ast
import copy
import hashlib
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import test_static_python_fixed_runtime_closure as closure_fixtures
from test_static_python_fixed_profile import (
    _closure_raw,
    _image,
    _parse,
    _pins,
    _raw,
    _sha,
    _startup,
    _vector,
)

from lunar_evolution import static_python_fixed_live_modules as live
from lunar_evolution.static_python_installation import STATIC_PYTHON_STARTUP_MODULES
from tools.static_python_rsi_fixture import runtime_closure as closure

ASSET = Path(__file__).parents[1] / "tools/static_python_rsi_fixture/assets/fixed_live_modules.py"
closure_inputs = closure_fixtures.closure_inputs


def _asset_namespace():
    # Execute only our reviewed observer functions against explicit synthetic
    # objects. No upstream source, real /proc read or real-runtime claim occurs.
    namespace = {}
    exec(compile(ASSET.read_bytes(), str(ASSET), "exec"), namespace)  # noqa: S102
    return namespace


def _runtime_fixture():
    namespace = _asset_namespace()

    class Spec:
        def __init__(self, name, loader, origin):
            self.name, self.loader, self.origin = name, loader, origin
            self._set_fileattr = False
            self.loader_state = self.submodule_search_locations = None

    class Builtin:
        pass

    class Frozen:
        pass

    sys = ModuleType("sys")
    frozen = ("_frozen_importlib", "_frozen_importlib_external", "_lunar_static_main", "encodings",
              "openevolve", "openevolve.lunar_fixed", "optional_frozen", "posixpath")
    packages = ("encodings", "openevolve")
    builtins = ("_imp", "_sha2", "builtins", "posix", "sys")
    namespace.update(_LUNAR_LIVE_FROZEN=frozen, _LUNAR_LIVE_BUILTINS=builtins,
                     _LUNAR_LIVE_PACKAGES=packages,
                     _LUNAR_LIVE_ALIASES=(("importlib._bootstrap", "_frozen_importlib"),
                                          ("os.path", "posixpath"),
                                          ("synthetic.alias", "optional_frozen")))
    sys.modules = {name: ModuleType(name) for name in (*builtins, *frozen, "__main__")}
    sys.modules["sys"] = sys
    for name, module in sys.modules.items():
        if name != "__main__":
            origin = "frozen" if name in frozen else "built-in"
            module.__loader__ = Frozen if name in frozen else Builtin
            module.__spec__ = Spec(name, module.__loader__, origin)
            if name in frozen:
                _origin, filename, state, paths = _frozen_metadata(name, name in packages)
                module.__file__ = filename
                module.__spec__.loader_state = SimpleNamespace(**state)
                module.__spec__.submodule_search_locations = paths
                if paths is not None:
                    module.__path__ = paths
    bootstrap = sys.modules["_frozen_importlib"]
    bootstrap.ModuleSpec, bootstrap.BuiltinImporter, bootstrap.FrozenImporter = Spec, Builtin, Frozen
    for alias, canonical in namespace["_LUNAR_LIVE_ALIASES"]:
        sys.modules[alias] = sys.modules[canonical]
    bootstrap.__name__ = "importlib._bootstrap"
    sys.builtin_module_names, sys.path, sys.path_hooks = builtins, [], []
    sys.flags = SimpleNamespace(**live._FLAGS)
    sys.implementation = SimpleNamespace(name="cpython")
    sys._stdlib_dir = "/lunar-static-fixture"
    imp = SimpleNamespace(extension_suffixes=list, _frozen_module_names=lambda: frozen,
                          is_builtin=lambda name: int(name in builtins),
                          is_frozen=lambda name: name in frozen,
                          find_frozen=lambda name: (None, name in packages, _frozen_metadata(name, name in packages)[0]))
    return namespace, sys, imp


def _frozen_metadata(name, package, bootstrap_alias=True):
    original = {"_frozen_importlib": "importlib._bootstrap",
                "_frozen_importlib_external": "importlib._bootstrap_external"}.get(name, name)
    stem = "/lunar-static-fixture/" + original.replace(".", "/")
    filename = stem + ("/__init__.py" if package else ".py")
    state = {"filename": filename, "origname": original}
    if name == "_frozen_importlib":
        state["filename"] = None
        if not bootstrap_alias:
            filename = None
    return original, filename, state, [stem] if package else None


def test_in_image_snapshot_observes_entire_table_including_aliases():
    namespace, sys, imp = _runtime_fixture()
    observed, flags = namespace["_lunar_live_snapshot"](sys, imp)
    assert [item["name"] for item in observed] == sorted(sys.modules)
    assert flags == live._FLAGS
    assert next(item for item in observed if item["name"] == "synthetic.alias") == {
        "name": "synthetic.alias", "origin": "frozen", "canonical_name": "optional_frozen",
        "loader": "FrozenImporter", "file": "/lunar-static-fixture/optional_frozen.py",
        "loader_state": {"filename": "/lunar-static-fixture/optional_frozen.py", "origname": "optional_frozen"},
        "package_paths": None,
    }
    del sys.modules["optional_frozen"], sys.modules["synthetic.alias"]
    observed, _ = namespace["_lunar_live_snapshot"](sys, imp)
    assert "optional_frozen" not in {item["name"] for item in observed}
    assert "optional_frozen" in imp._frozen_module_names()


def test_official_frozen_importer_metadata_shapes_are_not_external_source_evidence():
    namespace, sys, imp = _runtime_fixture()
    observed = {item["name"]: item for item in namespace["_lunar_live_snapshot"](sys, imp)[0]}
    assert observed["_frozen_importlib"]["file"] == "/lunar-static-fixture/importlib/_bootstrap.py"
    assert observed["importlib._bootstrap"]["loader_state"]["origname"] == "importlib._bootstrap"
    assert observed["_frozen_importlib"]["loader_state"]["filename"] is None
    assert observed["encodings"]["file"] == "/lunar-static-fixture/encodings/__init__.py"
    assert observed["encodings"]["package_paths"] == ["/lunar-static-fixture/encodings"]
    assert observed["openevolve"]["file"] == "/lunar-static-fixture/openevolve/__init__.py"
    assert observed["openevolve.lunar_fixed"]["file"] == "/lunar-static-fixture/openevolve/lunar_fixed.py"
    assert observed["_lunar_static_main"]["file"] == "/lunar-static-fixture/_lunar_static_main.py"
    assert observed["os.path"]["loader_state"]["origname"] == "posixpath"
    assert observed["sys"]["loader_state"] is None and observed["sys"]["file"] is None


def test_core_bootstrap_before_public_importlib_alias_retains_no_synthetic_file():
    namespace, sys, imp = _runtime_fixture()
    del sys.modules["importlib._bootstrap"]
    bootstrap = sys.modules["_frozen_importlib"]
    bootstrap.__name__ = "_frozen_importlib"
    del bootstrap.__file__
    observed = {item["name"]: item for item in namespace["_lunar_live_snapshot"](sys, imp)[0]}
    assert observed["_frozen_importlib"]["file"] is None
    assert observed["_frozen_importlib"]["loader_state"] == {"filename": None, "origname": "importlib._bootstrap"}


@pytest.mark.parametrize("fault", [
    "none", "foreign", "file", "source-origin", "no-spec", "wrong-loader", "unknown-alias",
    "path", "hooks", "extension", "dynamic", "roster", "flags", "name", "too-many",
    "frozen-state", "frozen-package", "frozen-info", "stdlib-root", "builtin-file", "alias-copy",
])
def test_live_snapshot_refuses_unknown_or_external_module_sources(fault):
    namespace, sys, imp = _runtime_fixture()
    module = sys.modules["optional_frozen"]
    if fault == "none":
        sys.modules["optional_frozen"] = None
    elif fault == "foreign":
        sys.modules["optional_frozen"] = object()
    elif fault == "file":
        module.__file__ = "/host/decoy.py"
    elif fault == "source-origin":
        module.__spec__.origin = "/host/decoy.py"
    elif fault == "no-spec":
        module.__spec__ = None
    elif fault == "wrong-loader":
        module.__spec__.loader = object()
    elif fault == "unknown-alias":
        sys.modules["unreviewed_alias"] = module
    elif fault == "path":
        sys.path = ["/host"]
    elif fault == "hooks":
        sys.path_hooks = [object()]
    elif fault == "extension":
        imp.extension_suffixes = lambda: [".so"]
    elif fault == "dynamic":
        imp.create_dynamic = object()
    elif fault == "roster":
        sys.builtin_module_names += ("extra",)
    elif fault == "flags":
        sys.flags.isolated = 0
    elif fault == "name":
        sys.modules["unbounded\nname"] = module
    elif fault == "frozen-state":
        module.__spec__.loader_state.origname = "different"
    elif fault == "frozen-package":
        sys.modules["encodings"].__path__ = ["/host/encodings"]
    elif fault == "frozen-info":
        imp.find_frozen = lambda name: (None, False, None)
    elif fault == "stdlib-root":
        sys._stdlib_dir = "/host"
    elif fault == "builtin-file":
        sys.__file__ = "/lunar-static-fixture/sys.py"
    elif fault == "alias-copy":
        clone = ModuleType("optional_frozen")
        clone.__dict__.update(module.__dict__)
        sys.modules["synthetic.alias"] = clone
    else:
        sys.modules.update({"extra_" + str(index): module for index in range(513)})
    with pytest.raises(RuntimeError, match="^fixed_live_modules_"):
        namespace["_lunar_live_snapshot"](sys, imp)


def test_table_drift_during_whole_snapshot_refuses():
    namespace, sys, imp = _runtime_fixture()
    original = imp.is_frozen

    def changed(name):
        sys.modules["late_module"] = sys.modules["optional_frozen"]
        return original(name)

    imp.is_frozen = changed
    with pytest.raises(RuntimeError, match="fixed_live_modules_table_drift"):
        namespace["_lunar_live_snapshot"](sys, imp)


class _ImageFD:
    O_RDONLY, O_CLOEXEC = 0, 1

    def __init__(self):
        self.raw, self.offset, self.closed, self.opened = _image(), 0, [], []
        self.identity = SimpleNamespace(st_dev=19, st_ino=77, st_mode=0o100755,
                                        st_size=len(self.raw), st_mtime_ns=1, st_ctime_ns=1)

    def open(self, path, flags):
        self.opened.append((path, flags))
        return 31

    def fstat(self, descriptor):
        assert descriptor == 31
        return self.identity

    def stat(self, path):
        assert path == "/proc/self/exe"
        return self.identity

    def read(self, descriptor, maximum):
        assert descriptor == 31 and 0 < maximum <= 65536
        raw = self.raw[self.offset:self.offset + maximum]
        self.offset += len(raw)
        return raw

    def close(self, descriptor):
        self.closed.append(descriptor)


def test_self_image_observation_uses_real_fd_bytes_and_always_closes():
    namespace, posix = _asset_namespace(), _ImageFD()
    image = namespace["_lunar_live_image"](posix, hashlib.sha256)
    assert image == {"device": 19, "inode": 77, "mode": 0o755, "size": len(_image()), "sha256": _sha(_image())}
    assert posix.opened == [("/proc/self/exe", 1)] and posix.closed == [31]


@pytest.mark.parametrize("fault", ["short", "directory", "suid", "large", "named-inode", "fd-drift"])
def test_self_image_observer_refuses_read_identity_and_mode_failures(fault):
    namespace, posix = _asset_namespace(), _ImageFD()
    if fault == "short":
        posix.raw = b""
    elif fault == "directory":
        posix.identity.st_mode = 0o040755
    elif fault == "suid":
        posix.identity.st_mode = 0o104755
    elif fault == "large":
        posix.identity.st_size = 128 * 1024 * 1024 + 1
    elif fault == "named-inode":
        posix.stat = lambda path: SimpleNamespace(**{**vars(posix.identity), "st_ino": 78})
    else:
        original = posix.read

        def changed(descriptor, maximum):
            raw = original(descriptor, maximum)
            posix.identity = SimpleNamespace(**{**vars(posix.identity), "st_ctime_ns": 2})
            return raw

        posix.read = changed
    with pytest.raises(RuntimeError, match="^fixed_live_modules_image"):
        namespace["_lunar_live_image"](posix, hashlib.sha256)
    assert posix.closed == [31]


def _comparison_vector(solver="openevolve", count=93):
    description, source_closure, _ = _vector(solver, count)
    next(item for item in description["frozen_modules"] if item["name"] == "encodings")["package"] = True
    next(item for item in source_closure["frozen"] if item["name"] == "encodings")["package"] = True
    # Replace one synthetic native module with the actual collector prerequisite.
    description["native_units"][0]["module"] = source_closure["native_units"][0]["module"] = "_sha2"
    description["runtime_closure_sha256"] = _sha(_closure_raw(source_closure))
    parsed = _parse(description, source_closure, _pins(description, source_closure))
    main = live.compose_fixed_python_live_main(
        solver, frozen_names=tuple(sorted(parsed.frozen_names)), builtin_names=parsed.builtin_names,
        aliases=parsed.aliases,
        frozen_packages=tuple(sorted(record["name"] for record in parsed.to_dict()["frozen_modules"] if record["package"])),
        collector_source=ASSET.read_bytes(),
    )
    source_record = {"path": "runtime/frozen_main.py", "size": len(main), "sha256": _sha(main)}
    next(item for item in description["frozen_modules"] if item["name"] == "_lunar_static_main")["source"] = source_record
    next(item for item in source_closure["frozen"] if item["name"] == "_lunar_static_main").update(
        source_size=len(main), source_sha256=_sha(main),
    )
    next(item for item in source_closure["sources"] if item["path"] == "runtime/frozen_main.py").update(source_record)
    description["runtime_closure_sha256"] = _sha(_closure_raw(source_closure))
    installed = _parse(description, source_closure, _pins(description, source_closure))
    startup, _ = _startup(installed)
    names = sorted(set(STATIC_PYTHON_STARTUP_MODULES) | {"_sha2", "synthetic_module_000"})
    observed = []
    packages = {record["name"] for record in installed.to_dict()["frozen_modules"] if record["package"]}
    for name in names:
        origin = "interpreter" if name == "__main__" else "frozen" if name in installed.frozen_names else "built-in"
        filename = state = paths = None
        if origin == "frozen":
            _original, filename, state, paths = _frozen_metadata(name, name in packages, bootstrap_alias=False)
        observed.append({"name": name, "canonical_name": name, "origin": origin, "file": filename,
                         "loader_state": state, "package_paths": paths,
                         "loader": {"interpreter": "interpreter", "frozen": "FrozenImporter",
                                    "built-in": "BuiltinImporter"}[origin]})
    raw = {"schema": live.FIXED_LIVE_MODULES_SCHEMA, "collector_profile": live.FIXED_LIVE_MODULES_PROFILE,
           "profile_version": installed.profile_version, "collector_source_sha256": live.FIXED_LIVE_COLLECTOR_SOURCE_SHA256,
           "phase": "explicit-in-image-call", "manifest_sha256": startup["marker"]["value"],
           "pid": 123, "image": {"device": 19, "inode": 77, **{key: description["image"][key]
                                  for key in ("mode", "size", "sha256")}},
           "modules": observed, "builtin_names": list(installed.builtin_names),
           "frozen_names": sorted(installed.frozen_names), "flags": dict(live._FLAGS), "sys_path": [],
           "claims": {"immutable_custody_verified": False, "production_admission": False,
                      "general_code_origin_protection": False}}
    return installed, main, startup, raw


def _compare(installed, main, startup, payload, **overrides):
    raw, startup_raw = _raw(payload) + b"\n", _raw(startup)
    arguments = {"image": _image(), "runtime_main_source": main, "startup_raw": startup_raw,
                 "expected_installation_sha256": installed.installation_sha256,
                 "expected_observation_sha256": _sha(raw), "expected_startup_sha256": _sha(startup_raw),
                 "expected_build_closure_sha256": startup["build_closure_sha256"],
                 "expected_binding_sha256": startup["binding_sha256"],
                 "expected_launch_intent_sha256": startup["launch_intent_sha256"],
                 "expected_sealed_material_sha256": startup["loader"]["sealed_material_sha256"], **overrides}
    return live.compare_fixed_python_live_modules(installed, raw, **arguments)


@pytest.mark.parametrize("solver,count", [("openevolve", 93), ("shinka", 103)])
def test_expanded_observation_compares_image_source_startup_without_admission(solver, count):
    vector = _comparison_vector(solver, count)
    result = _compare(*vector)
    assert result.module_names == tuple(item["name"] for item in vector[-1]["modules"])
    assert not result.live_runtime_authenticated and not result.immutable_custody_verified and not result.production_admission


@pytest.mark.parametrize("change", [
    lambda p: p["image"].update(inode=78),
    lambda p: p["image"].update(sha256=_sha("different-image")),
    lambda p: p.update(manifest_sha256=_sha("different-task")),
    lambda p: p.update(pid=True),
    lambda p: p["flags"].update(isolated=True),
    lambda p: p["sys_path"].append("/host"),
    lambda p: p["claims"].update(immutable_custody_verified=True),
    lambda p: p["frozen_names"].pop(),
    lambda p: p["builtin_names"].append("unreviewed"),
    lambda p: p["modules"][0].update(file="/host/decoy.py"),
    lambda p: p["modules"][0].update(origin="source"),
    lambda p: p["modules"][0].update(loader="SourceFileLoader"),
    lambda p: next(m for m in p["modules"] if m["name"] == "encodings").update(file=None),
    lambda p: next(m for m in p["modules"] if m["name"] == "encodings")["loader_state"].update(origname="other"),
    lambda p: next(m for m in p["modules"] if m["name"] == "encodings")["package_paths"].append("/host"),
    lambda p: p["modules"].append(copy.deepcopy(p["modules"][-1])),
    lambda p: p["modules"].reverse(),
    lambda p: p["modules"].__setitem__(slice(None), [m for m in p["modules"] if m["name"] != "_sha2"]),
    lambda p: p.update(extra="unknown"),
])
def test_resigned_runtime_description_cannot_change_bound_identity_or_origins(change):
    installed, main, startup, payload = _comparison_vector()
    change(payload)
    with pytest.raises(live.FixedPythonLiveModulesError):
        _compare(installed, main, startup, payload)


@pytest.mark.parametrize("argument", [
    "expected_installation_sha256", "expected_observation_sha256", "expected_startup_sha256",
    "expected_build_closure_sha256", "expected_binding_sha256", "expected_launch_intent_sha256",
    "expected_sealed_material_sha256",
])
def test_independent_comparison_pins_are_all_required(argument):
    with pytest.raises(live.FixedPythonLiveModulesError):
        _compare(*_comparison_vector(), **{argument: _sha("independent-drift")})


def test_image_source_and_dto_projection_drift_refuse_without_context():
    installed, main, startup, payload = _comparison_vector()
    for candidate, overrides in (
        (installed, {"image": _image()[:-1]}),
        (installed, {"runtime_main_source": main + b"# source drift\n"}),
        (replace(installed, frozen_names=("forged",)), {}),
    ):
        with pytest.raises(live.FixedPythonLiveModulesError) as caught:
            _compare(candidate, main, startup, payload, **overrides)
        assert caught.value.__context__ is None


def test_detached_json_is_not_promoted_to_authenticated_live_completeness():
    installed, main, startup, payload = _comparison_vector()
    payload["modules"] = [item for item in payload["modules"] if item["name"] != "synthetic_module_000"]
    # A supplied JSON claim cannot authenticate that the entire live table was
    # captured. This comparator deliberately returns no such authority.
    result = _compare(installed, main, startup, payload)
    assert result.live_runtime_authenticated is False and result.production_admission is False


def test_default_source_is_unchanged_and_opt_in_embeds_callable_without_protocol_output(closure_inputs, monkeypatch):
    baseline = closure.prepare_fixed_runtime_closure(**closure_inputs)
    assert closure.prepare_fixed_runtime_closure(**closure_inputs, live_modules_profile=None) == baseline
    selected = closure.prepare_fixed_runtime_closure(**closure_inputs, live_modules_profile=live.FIXED_LIVE_MODULES_PROFILE)
    baseline_main, selected_main = (dict(item.sources)["runtime/frozen_main.py"] for item in (baseline, selected))
    baseline_ast, selected_ast = ast.parse(baseline_main), ast.parse(selected_main)
    assert ast.dump(baseline_ast.body[0]) == ast.dump(selected_ast.body[0])
    assert selected_main.endswith(ASSET.read_bytes()) and selected_main != baseline_main
    assert b"_lunar_collect_live_modules" not in baseline_main
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "_lunar_collect_live_modules" for node in ast.walk(selected_ast.body[0]))
    assert not any(isinstance(node, ast.Attribute) and node.attr in {"stdout", "write", "print"}
                   for node in ast.walk(ast.parse(ASSET.read_bytes())))
    assert dict(selected.sources)["runtime/Modules/config.c"] == dict(baseline.sources)["runtime/Modules/config.c"]
    monkeypatch.setattr(closure, "prepare_fixed_live_main", lambda *args, **kwargs: pytest.fail("no implicit opt-in"))
    assert closure.prepare_fixed_runtime_closure(**closure_inputs) == baseline


@pytest.mark.parametrize("value", [False, True, "unknown", 1])
def test_invalid_live_source_profile_refuses_before_source_preparation(closure_inputs, value):
    with pytest.raises(closure.RuntimeClosureError, match="live_module_profile_invalid"):
        closure.prepare_fixed_runtime_closure(**closure_inputs, live_modules_profile=value)


def test_private_sink_profile_selects_new_pinned_c_without_changing_legacy_profile(closure_inputs):
    baseline = closure.prepare_fixed_runtime_closure(**closure_inputs)
    collector_only = closure.prepare_fixed_runtime_closure(
        **closure_inputs, live_modules_profile=live.FIXED_LIVE_MODULES_PROFILE,
    )
    selected = closure.prepare_fixed_runtime_closure(
        **closure_inputs, live_modules_profile=live.FIXED_LIVE_PRIVATE_SINK_PROFILE,
    )
    assert live.FIXED_LIVE_SINK_LAUNCHER_PATH not in dict(baseline.sources)
    assert live.FIXED_LIVE_SINK_LAUNCHER_PATH not in dict(collector_only.sources)
    assert dict(selected.sources)["runtime/frozen_main.py"] == dict(collector_only.sources)["runtime/frozen_main.py"]
    asset = dict(selected.sources)[live.FIXED_LIVE_SINK_LAUNCHER_PATH]
    assert len(asset) == live.FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES
    assert _sha(asset) == live.FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256
    assert closure.prepare_fixed_runtime_closure(**closure_inputs) == baseline
