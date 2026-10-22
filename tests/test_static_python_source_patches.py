"""Inert source-byte tests; no whole CPython source, freezer or image execution."""

from __future__ import annotations

import ast
import builtins
import codecs
import copy
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from tools.static_python_fixture import source_patches as preparation

FIXTURE = Path(__file__).parent / "fixtures/static_python_source"
PINS = {
    "Lib/importlib/_bootstrap_external.py": (
        73219, "a97a03ea9f9d38d90c8a50942183382ff5a479e7c4c5163c2ac5bae3561444ae",
        64722, "2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab",
    ),
    "Python/import.c": (
        146770, "4e18922dc31001c24fd9875746881ab407252bddc6bca544f22403d50e493a61",
        146559, "58a5fac8fac5916511f890f3fdd095d817e6f32ab709ebf0ed0becf9328226b1",
    ),
    "Lib/encodings/aliases.py": (
        15713, "cac92d68c7ea5bc0f05b448b9144e3bdf236d0b7d27ab66112e96d43aad15b3f",
        802, "43aadac378861c1bbdaaf04be8e1bb7d878529a7641ec123b5df4eccdd4c6106",
    ),
    "Lib/abc.py": (
        6538, "e558702a95cdce3febd289da021715d2b92bc43995b8a1bc58dfa1c3d8010287",
        6468, "a6684b1a49cfbc9c64caeeac7e55ef8f35052b8e8ca93a091941817cdc510b1c",
    ),
    "Lib/encodings/__init__.py": (
        5884, "78c4744d407690f321565488710b5aaf6486b5afa8d185637aa1e7633ab59cd8",
        1101, "47a11d930321492bca552eed29dad061ed6739bf84c919485453315d911b1c60",
    ),
}
PROVENANCE_PINS = {
    "Lib/abc.py": PINS["Lib/abc.py"][:2],
    "Lib/importlib/_bootstrap_external.py": PINS["Lib/importlib/_bootstrap_external.py"][:2],
    "Python/import.c": PINS["Python/import.c"][:2],
    "Lib/encodings/aliases.py": PINS["Lib/encodings/aliases.py"][:2],
    "Lib/encodings/__init__.py": PINS["Lib/encodings/__init__.py"][:2],
}
DENIED_METHODS = (
    ("_LoaderBasics", "exec_module"), ("SourceLoader", "get_code"),
    ("SourcelessFileLoader", "get_code"), ("ExtensionFileLoader", "create_module"),
    ("ExtensionFileLoader", "exec_module"), ("PathFinder", "find_spec"),
    ("FileFinder", "find_spec"),
)
CLAIMS = (
    "source_execution_performed", "build_performed", "frozen_headers_generated",
    "execution_performed", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
)


@pytest.fixture
def sources():
    return {path: (FIXTURE / (path + ".source")).read_bytes() for path in PINS}


def forbidden(*_args, **_kwargs):
    pytest.fail("unexpected callback or effect")


class CallbackMapping(Mapping):
    __getitem__ = forbidden
    __iter__ = forbidden
    __len__ = forbidden


class CallbackDict(dict):
    __iter__ = forbidden
    __len__ = forbidden
    __getitem__ = forbidden


class CallbackBytes(bytes):
    __len__ = forbidden
    __iter__ = forbidden
    __bytes__ = forbidden


class CallbackString(str):
    __hash__ = str.__hash__
    __eq__ = forbidden
    encode = forbidden


class Poison:
    __getattribute__ = forbidden
    __call__ = forbidden
    __str__ = forbidden
    __repr__ = forbidden
    __bool__ = forbidden
    __iter__ = forbidden


def external_ast(sources):
    outputs, _manifest = preparation.prepare_static_python_sources(sources)
    return ast.parse(outputs["Lib/importlib/_bootstrap_external.py"])


def find_method(tree, class_name, method_name):
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(node for node in owner.body
                if isinstance(node, ast.FunctionDef) and node.name == method_name)


def extracted_function(node, namespace=None):
    # Only one reviewed fixed method/function is compiled. Never execute the
    # whole upstream importlib module or freeze target bytecode with host Python.
    function = copy.deepcopy(node)
    function.decorator_list = []
    tree = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {} if namespace is None else namespace
    namespace["__builtins__"] = {"ImportError": ImportError}
    exec(compile(tree, "<inert-extracted-fixture-method>", "exec"), namespace)  # noqa: S102
    return namespace[function.name]


def test_fixture_bytes_and_license_retain_reviewed_git_provenance(sources):
    provenance = json.loads((FIXTURE / "provenance.json").read_bytes())
    assert provenance["source_commit"] == "1cbe481834751b0125e006042ffbd8cd5eaec8a8"
    assert provenance["source_tag"] == "v3.13.12"
    assert provenance["scope"] == "inert-source-byte-fixtures-only"
    for claim in ("official_python_org_archive_verified", "source_signature_verified",
                  "full_source_execution_performed", "build_performed"):
        assert provenance[claim] is False
    assert b"PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in (FIXTURE / "LICENSE").read_bytes()
    assert sorted(item["source_path"] for item in provenance["files"]) == sorted(PROVENANCE_PINS)
    for item in provenance["files"]:
        data = sources[item["source_path"]]
        assert item["fixture_path"].endswith(".source")
        assert len(data) == item["bytes"] == PROVENANCE_PINS[item["source_path"]][0]
        assert hashlib.sha256(data).hexdigest() == item["sha256"] == PROVENANCE_PINS[item["source_path"]][1]
    for path, (size, digest, _after_size, _after_digest) in PINS.items():
        data = sources[path]
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == digest


def test_all_outputs_are_deterministic_detached_and_fully_pinned(sources):
    original = dict(sources)
    outputs, manifest = preparation.prepare_static_python_sources(sources)
    assert sources == original and outputs is not sources
    assert preparation.prepare_static_python_sources(sources) == (outputs, manifest)
    assert sorted(outputs) == sorted(PINS)
    for path, (before_size, before_sha, after_size, after_sha) in PINS.items():
        assert len(sources[path]) == before_size
        assert hashlib.sha256(sources[path]).hexdigest() == before_sha
        assert len(outputs[path]) == after_size
        assert hashlib.sha256(outputs[path]).hexdigest() == after_sha
    assert manifest == preparation.source_patch_manifest()
    outputs.clear()
    manifest["files"].clear()
    assert len(preparation.source_patch_manifest()["files"]) == len(PINS)
    assert len(preparation.prepare_static_python_sources(sources)[0]) == len(PINS)


def test_manifest_records_true_source_policy_and_pending_build_without_effects(sources, monkeypatch):
    for target, attribute in (
        (builtins, "open"), (Path, "read_bytes"), (Path, "write_bytes"),
        (subprocess, "run"), (subprocess, "Popen"),
    ):
        monkeypatch.setattr(target, attribute, forbidden)
    outputs, manifest = preparation.prepare_static_python_sources(sources)
    assert manifest == preparation.source_patch_manifest()
    assert manifest["source_version"] == "3.13.12"
    assert manifest["source_commit"] == "1cbe481834751b0125e006042ffbd8cd5eaec8a8"
    assert manifest["provenance"] == "reviewed-git-source-files"
    assert manifest["source_archive_verification"] == "not-performed"
    assert manifest["source_signature_verification"] == "not-performed"
    assert manifest["abc_fallback_policy"] == "refuse-_py_abc-import-fallback"
    assert manifest["codec_lookup_policy"] == (
        "six-retained-utf8-aliases-plus-canonical-utf8-direct-binding"
    )
    assert all(manifest[claim] is False for claim in CLAIMS)
    assert len(outputs) == len(PINS)
    assert [item["path"] for item in manifest["files"]] == sorted(PINS)
    canonical = json.dumps(manifest["files"], sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    assert manifest["patch_set_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert manifest["patch_set_sha256"] == "f3c6f45437b954bdb8bd59a3fd05ef98d0b1715066e570cb3c277dda16596b48"
    assert sum(len(item["operations"]) for item in manifest["files"]) == 13
    assert all(operation["required_occurrences"] == 1
               for item in manifest["files"] for operation in item["operations"])


@pytest.mark.parametrize("value", [None, [], CallbackMapping(), CallbackDict()],
                         ids=["none", "list", "mapping-callback", "dict-subclass"])
def test_exact_mapping_refuses_callbacks_before_hashing(value, monkeypatch):
    monkeypatch.setattr(preparation.hashlib, "sha256", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="shape_invalid"):
        preparation.prepare_static_python_sources(value)


@pytest.mark.parametrize("path", ["../Python/import.c", "/Python/import.c", "Python\\import.c",
                                 "Python/import.c/", CallbackString("Python/import.c"), 1],
                         ids=["traversal", "absolute", "backslash", "trailing-slash",
                              "string-subclass", "integer"])
def test_fixed_paths_refuse_selection_and_callback_keys_before_hashing(sources, path, monkeypatch):
    sources.pop("Python/import.c")
    sources[path] = b"inert"
    monkeypatch.setattr(preparation.hashlib, "sha256", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="paths_invalid"):
        preparation.prepare_static_python_sources(sources)


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_source_set_is_all_or_nothing(sources, change, monkeypatch):
    if change == "missing":
        sources.pop("Python/import.c")
    else:
        sources["caller.patch"] = b"inert"
    monkeypatch.setattr(preparation.hashlib, "sha256", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="shape_invalid"):
        preparation.prepare_static_python_sources(sources)


@pytest.mark.parametrize("value", [None, "source", bytearray(b"source"), memoryview(b"source"),
                                  CallbackBytes(b"source"), pytest.param(Poison(), id="poison")],
                         ids=["none", "text", "bytearray", "memoryview", "bytes-subclass", "poison"])
def test_bytes_are_exact_before_any_hash_or_conversion(sources, value, monkeypatch):
    sources["Python/import.c"] = value
    monkeypatch.setattr(preparation.hashlib, "sha256", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="bytes_invalid"):
        preparation.prepare_static_python_sources(sources)


@pytest.mark.parametrize("size", [0, 256 * 1024 + 1])
def test_per_source_size_refuses_before_hashing(sources, size, monkeypatch):
    sources["Python/import.c"] = b"a" * size
    monkeypatch.setattr(preparation.hashlib, "sha256", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="source_size_invalid"):
        preparation.prepare_static_python_sources(sources)


def test_aggregate_source_size_refuses_before_hashing(monkeypatch):
    sources = {path: b"a" * (256 * 1024) for path in PINS}
    monkeypatch.setattr(preparation.hashlib, "sha256", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="source_budget_exceeded"):
        preparation.prepare_static_python_sources(sources)


@pytest.mark.parametrize("path", tuple(PINS))
@pytest.mark.parametrize("drift", ["same_size", "truncated", "already_patched"])
def test_every_full_source_preimage_is_required_before_manifest(sources, path, drift, monkeypatch):
    if drift == "same_size":
        sources[path] = b"!" + sources[path][1:]
    elif drift == "truncated":
        sources[path] = sources[path][:-1]
    else:
        sources[path] = preparation.prepare_static_python_sources(sources)[0][path]
    monkeypatch.setattr(preparation, "source_patch_manifest", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="preimage_drift"):
        preparation.prepare_static_python_sources(sources)


@pytest.mark.parametrize("old", [b"", b"not in reviewed source", b"\n"])
def test_unique_snippet_gate_checks_all_profiles_before_outputs(sources, old, monkeypatch):
    # A maintainer accidentally changing a fixed patch asset must refuse too;
    # no public API exposes a caller-defined patch or snippet.
    profiles = list(preparation._PROFILES)
    index = next(i for i, profile in enumerate(profiles) if profile.snippets)
    profile = profiles[index]
    profiles[index] = replace(profile, snippets=(replace(profile.snippets[0], old=old),))
    monkeypatch.setattr(preparation, "_PROFILES", tuple(profiles))
    monkeypatch.setattr(preparation, "source_patch_manifest", forbidden)
    with pytest.raises(preparation.StaticPythonSourceError, match="snippet_drift"):
        preparation.prepare_static_python_sources(sources)


def test_patch_asset_drift_cannot_return_unpinned_output(sources, monkeypatch):
    profiles = list(preparation._PROFILES)
    index = next(i for i, profile in enumerate(profiles) if profile.snippets)
    profile = profiles[index]
    profiles[index] = replace(profile, snippets=(replace(profile.snippets[0], new=b"aliases = {}\n"),))
    monkeypatch.setattr(preparation, "_PROFILES", tuple(profiles))
    with pytest.raises(preparation.StaticPythonSourceError, match="postimage_drift"):
        preparation.prepare_static_python_sources(sources)


def test_no_caller_defined_patch_argument(sources):
    with pytest.raises(TypeError):
        preparation.prepare_static_python_sources(sources, patches=[])


@pytest.mark.parametrize("class_name,method_name", DENIED_METHODS)
def test_direct_loader_method_is_one_fixed_raise_before_callbacks(sources, class_name, method_name):
    method = find_method(external_ast(sources), class_name, method_name)
    assert len(method.body) == 1 and isinstance(method.body[0], ast.Raise)
    exception = method.body[0].exc
    assert isinstance(exception, ast.Call) and isinstance(exception.func, ast.Name)
    assert exception.func.id == "ImportError"
    assert len(exception.args) == 1 and ast.literal_eval(exception.args[0]) == "lunar_static_external_loader_refused"
    function = extracted_function(method)
    arguments = [Poison() for _ in method.args.posonlyargs + method.args.args]
    with pytest.raises(ImportError, match="^lunar_static_external_loader_refused$"):
        function(*arguments)


def test_external_install_keeps_bootstrap_metadata_and_never_consults_hooks(sources):
    tree = external_ast(sources)
    install = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "_install")
    assert len(install.body) == 1
    call = install.body[0].value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    assert call.func.id == "_set_bootstrap_module" and len(call.args) == 1
    seen = []
    function = extracted_function(install, {
        "_set_bootstrap_module": seen.append, "sys": Poison(),
        "FileFinder": Poison(), "PathFinder": Poison(),
    })
    bootstrap = Poison()
    assert function(bootstrap) is None
    assert len(seen) == 1 and seen[0] is bootstrap


def test_supported_file_loader_list_is_empty_without_callbacks(sources):
    tree = external_ast(sources)
    node = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_get_supported_file_loaders")
    assert len(node.body) == 1 and isinstance(node.body[0], ast.Return)
    assert ast.literal_eval(node.body[0].value) == []
    function = extracted_function(node, {"_imp": Poison(), "sys": Poison()})
    assert function() == []


def test_core_external_init_keeps_metadata_and_omits_zip_hook_call(sources):
    outputs, _manifest = preparation.prepare_static_python_sources(sources)
    patched = outputs["Python/import.c"]
    match = re.search(rb"PyStatus\n_PyImport_InitExternal\([^\n]*\)\n\{.*?\n\}", patched, re.DOTALL)
    assert match is not None
    function = match.group()
    assert function.count(b"init_importlib_external(tstate->interp)") == 1
    assert b"_PyErr_Print(tstate);" in function
    assert b'return _PyStatus_ERR("external importer setup failed");' in function
    assert b"return _PyStatus_OK();" in function
    assert b"init_zipimport" not in function and b"path_hooks" not in function
    assert patched.count(b"init_zipimport(") == 1  # The uncalled stock helper stays in source.
    # Existing unrelated core dynamic-loader conditional policy stays unchanged;
    # this source preparation does not attest a configured no-dlopen build.
    assert patched.count(b"#ifdef HAVE_DYNAMIC_LOADING") == sources["Python/import.c"].count(b"#ifdef HAVE_DYNAMIC_LOADING")


def test_alias_source_has_exact_six_utf8_entries_and_no_other_assignment(sources):
    outputs, _manifest = preparation.prepare_static_python_sources(sources)
    tree = ast.parse(outputs["Lib/encodings/aliases.py"])
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
    assert len(assignments) == 1
    assert len(assignments[0].targets) == 1 and assignments[0].targets[0].id == "aliases"
    aliases = ast.literal_eval(assignments[0].value)
    assert aliases == {name: "utf_8" for name in
                       ("cp65001", "u8", "utf", "utf8", "utf8_ucs2", "utf8_ucs4")}
    assert list(aliases) == sorted(aliases)


def test_abc_python_fallback_fails_closed_before_importing_py_abc(sources):
    outputs, _manifest = preparation.prepare_static_python_sources(sources)
    tree = ast.parse(outputs["Lib/abc.py"])
    handler = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.ExceptHandler)
                   and isinstance(node.type, ast.Name) and node.type.id == "ImportError"
                   and any(isinstance(child, ast.Raise) and child.exc is None
                           for child in ast.walk(node)))
    assert len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise)
    assert handler.body[0].exc is None
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "_py_abc"
                   for node in ast.walk(tree))
    trigger = ast.Raise(exc=ast.Call(func=ast.Name(id="ImportError", ctx=ast.Load()),
                                     args=[ast.Constant("original failure")], keywords=[]))
    isolated = ast.Try(body=[trigger], handlers=[copy.deepcopy(handler)],
                       orelse=[], finalbody=[])
    module = ast.Module(body=[isolated], type_ignores=[])
    with pytest.raises(ImportError, match="^original failure$") as raised:
        exec(compile(ast.fix_missing_locations(module), "<fixed-abc-fallback>", "exec"), {})  # noqa: S102
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is False


def test_codec_lookup_only_accepts_retained_utf8_aliases_and_direct_codec_binding(sources):
    outputs, _manifest = preparation.prepare_static_python_sources(sources)
    tree = ast.parse(outputs["Lib/encodings/__init__.py"])
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert [(node.level, node.module, node.names[0].name, node.names[0].asname)
            for node in imports] == [
                (1, None, "aliases", "_aliases"),
                (1, None, "utf_8", "_utf_8"),
            ]
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "__import__" for node in ast.walk(tree))

    function_nodes = [node for node in tree.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name in {"normalize_encoding", "search_function"}]
    namespace = {
        "_cache": {},
        "_unknown": object(),
        "_aliases": type("Aliases", (), {"aliases": {
            name: "utf_8" for name in
            ("cp65001", "u8", "utf", "utf8", "utf8_ucs2", "utf8_ucs4")
        }})(),
    }

    class Utf8Codec:
        calls = 0
        entry = object()

        @classmethod
        def getregentry(cls):
            cls.calls += 1
            return cls.entry

    namespace["_utf_8"] = Utf8Codec
    module = ast.Module(body=copy.deepcopy(function_nodes), type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "<fixed-codec-functions>", "exec"), namespace)  # noqa: S102
    lookup = namespace["search_function"]
    supported = ("utf-8", "cp65001", "U8", "UTF", "utf8", "utf8-ucs2", "utf8_ucs4", b"utf-8")
    assert all(lookup(name) is Utf8Codec.entry for name in supported)
    calls_after_supported = Utf8Codec.calls
    unsupported = ("ascii", "latin-1", "utf-16", "cp1252", "utf-8-sig", "unknown-lunar-codec")
    assert all(lookup(name) is None for name in unsupported)
    assert Utf8Codec.calls == calls_after_supported
    codecs.register(lookup)
    try:
        with pytest.raises(LookupError, match="^unknown encoding:"):
            codecs.lookup("lunar_only_unavailable_codec")
    finally:
        codecs.unregister(lookup)
    assert Utf8Codec.calls == calls_after_supported
