"""Declared Python files are pinned without running or discovering target code."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import producer_python_runtime as runtime


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


_SLOTS = {
    "runtime": {"interpreter", "loader", "shared_library", "stdlib", "stdlib_archive"},
    "dependency": {"extension", "site_package"},
    "project": {"project_source"},
    "resource": {"project_resource"},
    "metadata": {"venv_config", "dependency_lock"},
}


def _resign(value):
    """Reach parser schema validation with consistent externally computed digests."""
    value = json.loads(json.dumps(value))
    for slot, roles in _SLOTS.items():
        value[f"{slot}_sha256"] = hashlib.sha256(_canonical({
            "slot": slot, "files": [item for item in value["files"] if item["role"] in roles],
        })).hexdigest()
    value.pop("manifest_sha256", None)
    value["manifest_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
    return _canonical(value)


def _target(**changes):
    return runtime.PythonRuntimeTarget(**({
        "platform": "linux", "architecture": "x86_64", "python_version": "3.11",
        "abi_tag": "cp311", "layout": "portable-tree",
    } | changes))


def _tree(tmp_path, *, layout="portable-tree"):
    base = tmp_path.resolve() / "inert-python-tree"
    base.mkdir()
    roots = {label: base / label for label in ("runtime", "deps", "project", "assets", "meta")}
    declarations = []
    entries = (
        ("runtime", "bin/python", "interpreter"),
        ("runtime", "lib/loader.so", "loader"),
        ("runtime", "lib/libpython.so", "shared_library"),
        ("runtime", "lib/stdlib/os.py", "stdlib"),
        ("runtime", "lib/stdlib.zip", "stdlib_archive"),
        ("deps", "site/native.so", "extension"),
        ("deps", "site/package/__init__.py", "site_package"),
        ("project", "src/main.py", "project_source"),
        ("assets", "data/input.txt", "project_resource"),
        ("meta", "requirements.lock", "dependency_lock"),
    )
    if layout == "venv-tree":
        entries += (("meta", "pyvenv.cfg", "venv_config"),)
    for label, relative, role in entries:
        path = roots[label] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # Even the executable is an inert blob; the project file is never evaluated.
        path.write_bytes(f"inert declared {role}\n".encode())
        path.chmod(0o700 if role == "interpreter" else 0o600)
        declarations.append(runtime.PythonRuntimeFileDeclaration(label, relative, role))
    imports = tuple(runtime.PythonRuntimeImportRoot(label, relative) for label, relative in (
        ("runtime", "lib/stdlib"), ("deps", "site"), ("project", "src"),
    ))
    return SimpleNamespace(
        base=base, roots=roots, declarations=tuple(declarations), imports=imports,
        entrypoint=next(item for item in declarations if item.role == "project_source"),
        target=_target(layout=layout),
    )


def _build(tree, **changes):
    return runtime.build_python_runtime_manifest(**({
        "root_paths": tree.roots, "file_declarations": tree.declarations,
        "target": tree.target, "import_roots": tree.imports, "entrypoint": tree.entrypoint,
    } | changes))


def _verify(manifest, **changes):
    return runtime.verify_python_runtime_manifest(manifest, **({
        "expected_manifest_sha256": manifest.manifest_sha256,
        "expected_target": manifest.target,
    } | changes))


def _path(tree, role):
    declaration = next(item for item in tree.declarations if item.role == role)
    return tree.roots[declaration.root_label] / declaration.relative_path


def _inventory(base):
    inventory = {}
    for path in (base, *sorted(base.rglob("*"))):
        info = path.lstat()
        inventory[path.relative_to(base).as_posix()] = (
            path.read_bytes() if stat.S_ISREG(info.st_mode) else None,
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns,
        )
    return inventory


def _refused(call):
    with pytest.raises(runtime.PythonRuntimeError) as refused:
        call()
    assert refused.value.code.startswith("python_runtime_")


@pytest.mark.parametrize("layout", ["portable-tree", "venv-tree"])
def test_manifest_roundtrip_and_observation_are_declared_scope_only(tmp_path, layout):
    tree = _tree(tmp_path, layout=layout)
    manifest = _build(tree)
    data = manifest.to_dict()
    assert data["schema_version"] == "1"
    assert data["protocol"] == "lunar-python-runtime-inventory-v1"
    assert data["scope"] == "declared-files-only"
    assert data["policy"] == {
        "argv_flags": ["-I", "-S", "-B"], "inherit_python_environment": False,
        "user_site": False, "pth_processing": False, "customization_imports": False,
        "cwd_imports": False, "bytecode_writes": False,
    }
    assert manifest.to_json() == _canonical(data)
    assert _resign(data) == manifest.to_json()
    assert runtime.parse_python_runtime_manifest(manifest.to_json()) == manifest
    assert runtime.parse_python_runtime_manifest(manifest.to_json().decode()) == manifest
    observation = _verify(manifest)
    assert observation.target == tree.target
    assert observation.file_count == len(tree.declarations)
    assert observation.total_bytes == sum(_path(tree, item.role).stat().st_size
                                          for item in tree.declarations)
    assert observation.to_dict()["execution_performed"] is False
    assert observation.to_dict()["runtime_load_protection"] is False
    assert observation.to_dict()["scope"] == "declared-files-only"
    assert observation.manifest_sha256 == manifest.manifest_sha256
    assert observation.to_json() == _canonical(observation.to_dict())


def test_caller_order_is_canonical_and_to_dict_is_detached(tmp_path):
    tree = _tree(tmp_path)
    manifest = _build(tree)
    reordered = _build(
        tree, root_paths=dict(reversed(tuple(tree.roots.items()))),
        file_declarations=tuple(reversed(tree.declarations)),
        import_roots=tuple(reversed(tree.imports)),
    )
    assert manifest.to_json() == reordered.to_json()
    detached = manifest.to_dict()
    detached["files"][0]["sha256"] = "a" * 64
    detached["roots"][0]["directories"].clear()
    assert manifest.to_json() == reordered.to_json()
    objects = (tree.target, tree.declarations[0], tree.imports[0], manifest, manifest.files[0],
               manifest.roots[0], manifest.roots[0].directories[0], _verify(manifest))
    for item in objects:
        assert item.to_json() == _canonical(item.to_dict())
        with pytest.raises((FrozenInstanceError, AttributeError)):
            setattr(item, fields(item)[0].name, "mutation")
        assert not hasattr(item, "__dict__")


def test_unicode_resource_path_has_canonical_utf8_bytes(tmp_path):
    tree = _tree(tmp_path)
    path = tree.roots["assets"] / "data" / "说明.txt"
    path.write_bytes(b"inert resource")
    declaration = runtime.PythonRuntimeFileDeclaration("assets", "data/说明.txt", "project_resource")
    manifest = _build(tree, file_declarations=(*tree.declarations, declaration))
    assert "说明.txt".encode() in manifest.to_json()
    assert b"\\u8bf4" not in manifest.to_json()
    assert runtime.parse_python_runtime_manifest(manifest.to_json()) == manifest


@pytest.mark.parametrize("change", ["newline", "indent", "key-order", "duplicate", "bom"])
def test_parser_refuses_noncanonical_or_duplicate_json(tmp_path, change):
    raw = _build(_tree(tmp_path)).to_json()
    if change == "newline":
        raw += b"\n"
    elif change == "indent":
        raw = json.dumps(json.loads(raw), indent=2).encode()
    elif change == "key-order":
        raw = json.dumps(dict(reversed(tuple(json.loads(raw).items()))), separators=(",", ":")).encode()
    elif change == "duplicate":
        raw = raw[:-1] + b',"schema_version":"1"}'
    else:
        raw = b"\xef\xbb\xbf" + raw
    _refused(lambda: runtime.parse_python_runtime_manifest(raw))


@pytest.mark.parametrize("location", ["manifest", "target", "policy", "root", "directory", "file",
                                      "import-root", "entrypoint"])
@pytest.mark.parametrize("change", ["unknown", "missing"])
def test_parser_requires_exact_schema_at_every_level(tmp_path, location, change):
    data = _build(_tree(tmp_path)).to_dict()
    item = {
        "manifest": data, "target": data["target"], "policy": data["policy"],
        "root": data["roots"][0], "directory": data["roots"][0]["directories"][0],
        "file": data["files"][0], "import-root": data["import_roots"][0],
        "entrypoint": data["entrypoint"],
    }[location]
    if change == "unknown":
        item["caller_trust"] = True
    else:
        del item[next(iter(item))]
    # Deleting a file role prevents computing the slot; malformed schema is still explicit.
    raw = _canonical(data) if location == "file" and change == "missing" else _resign(data)
    _refused(lambda: runtime.parse_python_runtime_manifest(raw))


@pytest.mark.parametrize("location,field", [
    ("file", "size"), ("file", "device"), ("file", "inode"), ("file", "mode"),
    ("file", "mtime_ns"), ("file", "ctime_ns"), ("root", "device"), ("root", "inode"),
    ("root", "mode"), ("directory", "device"), ("directory", "inode"), ("directory", "mode"),
])
def test_parser_rejects_boolean_stat_pins_instead_of_treating_them_as_integers(tmp_path, location, field):
    data = _build(_tree(tmp_path)).to_dict()
    item = {"file": data["files"][0], "root": data["roots"][0],
            "directory": data["roots"][0]["directories"][0]}[location]
    item[field] = True
    _refused(lambda: runtime.parse_python_runtime_manifest(_resign(data)))


@pytest.mark.parametrize("changes", [
    {"platform": "windows"}, {"architecture": "armv7"}, {"python_version": "3.10"},
    {"python_version": "3.11.9"}, {"python_version": True}, {"abi_tag": "cp312"},
    {"layout": "ambient-site"},
])
def test_builder_refuses_invalid_declared_targets(tmp_path, changes):
    tree = _tree(tmp_path)
    _refused(lambda: _build(tree, target=_target(**changes)))


@pytest.mark.parametrize("version,abi", [("3.11", "cp311"), ("3.12", "cp312"), ("3.13", "cp313")])
@pytest.mark.parametrize("platform,architecture", [("linux", "x86_64"), ("darwin", "aarch64")])
def test_supported_target_is_a_declaration_without_local_abi_execution(tmp_path, version, abi,
                                                                      platform, architecture):
    tree = _tree(tmp_path)
    declared = _target(python_version=version, abi_tag=abi, platform=platform,
                       architecture=architecture)
    manifest = _build(tree, target=declared)
    assert _verify(manifest).target == declared


@pytest.mark.parametrize("mutation", ["profile", "abi", "order", "sha256", "runtime-slot",
                                      "manifest-digest", "scope", "protocol", "negative-size"])
def test_parser_rejects_invalid_semantics_even_with_recomputed_manifest_digest(tmp_path, mutation):
    data = _build(_tree(tmp_path)).to_dict()
    if mutation == "profile":
        data["policy"]["pth_processing"] = True
    elif mutation == "abi":
        data["target"]["abi_tag"] = "cp312"
    elif mutation == "order":
        data["files"].reverse()
    elif mutation == "sha256":
        data["files"][0]["sha256"] = "A" * 64
    elif mutation == "scope":
        data["scope"] = "complete-python-runtime"
    elif mutation == "protocol":
        data["protocol"] = "lunar-python-runtime-inventory-v2"
    elif mutation == "negative-size":
        data["files"][0]["size"] = -1
    raw = _resign(data)
    if mutation in {"runtime-slot", "manifest-digest"}:
        data = json.loads(raw)
        field = "runtime_sha256" if mutation == "runtime-slot" else "manifest_sha256"
        data[field] = "a" * 64
        if mutation == "runtime-slot":
            data.pop("manifest_sha256")
            data["manifest_sha256"] = hashlib.sha256(_canonical(data)).hexdigest()
        raw = _canonical(data)
    _refused(lambda: runtime.parse_python_runtime_manifest(raw))


@pytest.mark.parametrize("role", sorted(set().union(*_SLOTS.values())))
def test_every_declared_role_detects_byte_drift(tmp_path, role):
    tree = _tree(tmp_path, layout="venv-tree")
    manifest = _build(tree)
    path = _path(tree, role)
    original = path.read_bytes()
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    _refused(lambda: _verify(manifest))


@pytest.mark.parametrize("mutation", ["same-bytes-inode", "chmod", "mtime", "missing", "hardlink",
                                      "fifo", "directory", "setuid", "setgid", "symlink"])
def test_declared_file_identity_and_metadata_drift_is_refused(tmp_path, mutation):
    tree = _tree(tmp_path)
    manifest = _build(tree)
    path = _path(tree, "site_package")
    if mutation == "same-bytes-inode":
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(replacement, path)
    elif mutation == "chmod":
        path.chmod(0o400)
    elif mutation == "mtime":
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    elif mutation == "hardlink":
        os.link(path, path.with_name("other-hardlink"))
    elif mutation in {"setuid", "setgid"}:
        if mutation == "setgid":
            os.chown(path, -1, os.getegid())
        path.chmod(path.stat().st_mode | (stat.S_ISUID if mutation == "setuid" else stat.S_ISGID))
        assert path.stat().st_mode & (stat.S_ISUID if mutation == "setuid" else stat.S_ISGID)
    else:
        content = path.read_bytes()
        path.unlink()
        if mutation == "fifo":
            os.mkfifo(path)
        elif mutation == "directory":
            path.mkdir()
        elif mutation == "symlink":
            other = path.with_name("same-content")
            other.write_bytes(content)
            path.symlink_to(other)
    _refused(lambda: _verify(manifest))


@pytest.mark.parametrize("location", ["root", "parent", "import-directory", "used-file-parent"])
@pytest.mark.parametrize("mutation", ["chmod", "replace", "symlink"])
def test_directory_identity_and_mode_pins_include_ancestors_and_import_roots(tmp_path, location,
                                                                           mutation):
    tree = _tree(tmp_path)
    # An explicit empty import directory is pinned despite having no declared file below it.
    empty_import = tree.roots["deps"] / "empty-import"
    empty_import.mkdir()
    imports = (*tree.imports, runtime.PythonRuntimeImportRoot("deps", "empty-import"))
    manifest = _build(tree, import_roots=imports)
    path = {"root": tree.roots["deps"], "parent": tree.base,
            "import-directory": empty_import,
            "used-file-parent": _path(tree, "site_package").parent}[location]
    pinned = {Path(item.path) for root in manifest.roots for item in root.directories}
    assert path in pinned
    original_mode = stat.S_IMODE(path.stat().st_mode)
    if mutation == "chmod":
        path.chmod(stat.S_IMODE(path.stat().st_mode) ^ 0o100)
    else:
        saved = path.with_name(path.name + "-retained")
        path.rename(saved)
        if mutation == "symlink":
            path.symlink_to(saved, target_is_directory=True)
        else:
            shutil.copytree(saved, path)
    try:
        _refused(lambda: _verify(manifest))
    finally:
        if mutation == "chmod":
            path.chmod(original_mode)


@pytest.mark.parametrize("bad", ["/absolute.py", "../outside.py", "src/../main.py", "src//main.py",
                                 "./src/main.py", "src/main.py/", "src/./main.py", "src\\main.py"])
def test_builder_refuses_noncanonical_or_escaping_relative_file_paths(tmp_path, bad):
    tree = _tree(tmp_path)

    def invalid_declaration():
        replacement = replace(tree.entrypoint, relative_path=bad)
        declarations = tuple(replacement if item == tree.entrypoint else item
                             for item in tree.declarations)
        return _build(tree, file_declarations=declarations, entrypoint=replacement)

    _refused(invalid_declaration)


@pytest.mark.parametrize("bad", ["../", "/absolute", "lib/../lib", "lib//stdlib", "./lib", ""])
def test_builder_refuses_noncanonical_import_directories(tmp_path, bad):
    tree = _tree(tmp_path)
    _refused(lambda: _build(tree, import_roots=(*tree.imports,
                                             runtime.PythonRuntimeImportRoot("runtime", bad))))


@pytest.mark.parametrize("mutation", ["overlap", "same-root-alias", "root-symlink", "ancestor-symlink",
                                      "duplicate-declaration", "duplicate-import", "unused-root",
                                      "unknown-root", "relative-root"])
def test_root_and_declaration_aliases_cannot_broaden_inventory(tmp_path, mutation):
    tree = _tree(tmp_path)
    kwargs = {}
    if mutation == "overlap":
        kwargs["root_paths"] = tree.roots | {"inner": tree.roots["runtime"] / "lib"}
    elif mutation == "same-root-alias":
        kwargs["root_paths"] = tree.roots | {"alias": tree.roots["runtime"]}
    elif mutation == "root-symlink":
        alias = tree.base / "alias"
        alias.symlink_to(tree.roots["runtime"], target_is_directory=True)
        kwargs["root_paths"] = tree.roots | {"runtime": alias}
    elif mutation == "ancestor-symlink":
        alias = tmp_path / "alias-parent"
        alias.symlink_to(tree.base, target_is_directory=True)
        kwargs["root_paths"] = {label: alias / label for label in tree.roots}
    elif mutation == "duplicate-declaration":
        kwargs["file_declarations"] = (*tree.declarations, tree.declarations[0])
    elif mutation == "duplicate-import":
        kwargs["import_roots"] = (*tree.imports, tree.imports[0])
    elif mutation == "unused-root":
        extra = tree.base / "unused"
        extra.mkdir()
        kwargs["root_paths"] = tree.roots | {"unused": extra}
    elif mutation == "unknown-root":
        kwargs["file_declarations"] = (*tree.declarations,
            runtime.PythonRuntimeFileDeclaration("missing", "file.py", "site_package"))
    else:
        kwargs["root_paths"] = tree.roots | {"runtime": Path("relative-runtime")}
    _refused(lambda: _build(tree, **kwargs))


@pytest.mark.parametrize("basename", ["injected.pth", "INJECTED.PTH", "sitecustomize.py",
                                      "SiteCustomize.py", "usercustomize.py", "USERCUSTOMIZE.PY"])
def test_listed_import_customization_hooks_are_explicitly_refused(tmp_path, basename):
    tree = _tree(tmp_path)
    path = tree.roots["deps"] / "site" / basename
    path.write_bytes(b"inert forbidden customization declaration")
    _refused(lambda: _build(tree, file_declarations=(*tree.declarations,
        runtime.PythonRuntimeFileDeclaration("deps", f"site/{basename}", "site_package"))))


@pytest.mark.parametrize("mutation", ["no-interpreter", "two-interpreters", "not-executable",
                                      "no-stdlib", "no-lock", "entrypoint-not-listed",
                                      "entrypoint-not-source", "unknown-role",
                                      "portable-venv-config", "venv-no-config", "venv-wrong-name"])
def test_required_runtime_roles_and_entrypoint_are_structural_contracts(tmp_path, mutation):
    tree = _tree(tmp_path, layout="venv-tree" if mutation.startswith("venv-") else "portable-tree")
    kwargs = {}
    declarations = tree.declarations
    if mutation == "no-interpreter":
        declarations = tuple(item for item in declarations if item.role != "interpreter")
    elif mutation == "two-interpreters":
        path = tree.roots["runtime"] / "bin" / "other-python"
        path.write_bytes(b"another inert executable")
        path.chmod(0o700)
        declarations += (runtime.PythonRuntimeFileDeclaration("runtime", "bin/other-python", "interpreter"),)
    elif mutation == "not-executable":
        _path(tree, "interpreter").chmod(0o600)
    elif mutation == "no-stdlib":
        declarations = tuple(item for item in declarations if item.role not in {"stdlib", "stdlib_archive"})
    elif mutation == "no-lock":
        declarations = tuple(item for item in declarations if item.role != "dependency_lock")
    elif mutation == "entrypoint-not-listed":
        kwargs["entrypoint"] = replace(tree.entrypoint, relative_path="src/other.py")
    elif mutation == "entrypoint-not-source":
        kwargs["entrypoint"] = next(item for item in declarations if item.role == "site_package")
    elif mutation == "unknown-role":
        _refused(lambda: _build(tree, file_declarations=tuple(
            replace(item, role="trusted_blob") if item.role == "extension" else item
            for item in declarations)))
        return
    elif mutation == "portable-venv-config":
        path = tree.roots["meta"] / "pyvenv.cfg"
        path.write_bytes(b"inert declared venv config")
        declarations += (runtime.PythonRuntimeFileDeclaration("meta", "pyvenv.cfg", "venv_config"),)
    elif mutation == "venv-no-config":
        declarations = tuple(item for item in declarations if item.role != "venv_config")
    else:
        original = _path(tree, "venv_config")
        original.rename(original.with_name("different.cfg"))
        declarations = tuple(replace(item, relative_path="different.cfg")
                             if item.role == "venv_config" else item for item in declarations)
    _refused(lambda: _build(tree, file_declarations=declarations, **kwargs))


@pytest.mark.parametrize("pin", ["a" * 64, "A" * 64, "", None])
def test_verifier_requires_an_external_manifest_digest_pin(tmp_path, pin):
    manifest = _build(_tree(tmp_path))
    _refused(lambda: _verify(manifest, expected_manifest_sha256=pin))


@pytest.mark.parametrize("field,value", [("platform", "darwin"), ("architecture", "aarch64"),
                                         ("layout", "venv-tree")])
def test_verifier_requires_exact_declared_target_pin(tmp_path, field, value):
    manifest = _build(_tree(tmp_path))
    _refused(lambda: _verify(manifest, expected_target=replace(manifest.target, **{field: value})))


def test_verifier_has_no_implicit_expected_pins(tmp_path):
    manifest = _build(_tree(tmp_path))
    with pytest.raises(TypeError):
        runtime.verify_python_runtime_manifest(manifest)
    with pytest.raises(TypeError):
        runtime.verify_python_runtime_manifest(manifest, expected_target=manifest.target)
    with pytest.raises(TypeError):
        runtime.verify_python_runtime_manifest(manifest, expected_manifest_sha256=manifest.manifest_sha256)


def test_undeclared_files_do_not_imply_complete_import_inventory(tmp_path):
    tree = _tree(tmp_path)
    manifest = _build(tree)
    # This deliberately documents the v1 boundary: no discovery or runtime load enforcement.
    extra = tree.roots["deps"] / "site" / "unlisted.py"
    extra.write_bytes(b"inert undeclared source")
    extra_hook = tree.roots["deps"] / "site" / "unlisted.pth"
    extra_hook.write_bytes(b"inert undeclared hook")
    observation = _verify(manifest)
    assert observation.file_count == len(tree.declarations)
    assert observation.to_dict()["runtime_load_protection"] is False
    assert all(item.relative_path != "site/unlisted.py" for item in manifest.files)


def test_build_parse_and_verify_do_not_execute_write_or_enumerate_extra_files(tmp_path, monkeypatch):
    tree = _tree(tmp_path)
    entrypoint = _path(tree, "project_source")
    sentinel = tree.base / "executed-sentinel"
    entrypoint.write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n")
    before = _inventory(tree.base)

    def forbidden(*_args, **_kwargs):
        pytest.fail("inventory tried to execute, mutate or discover target contents")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in ("system", "write", "mkdir", "unlink", "rename", "replace", "chmod", "execve"):
        monkeypatch.setattr(runtime.os, name, forbidden)
    with monkeypatch.context() as reads_only:
        for name in ("iterdir", "glob", "rglob", "write_bytes", "write_text", "touch"):
            reads_only.setattr(Path, name, forbidden)
        manifest = _build(tree)
        parsed = runtime.parse_python_runtime_manifest(manifest.to_json())
        assert _verify(parsed).file_count == len(tree.declarations)
    assert not sentinel.exists()
    assert _inventory(tree.base) == before


@pytest.mark.parametrize("operation", ["build", "verify"])
@pytest.mark.parametrize("mutation", ["earlier-bytes", "earlier-inode", "parent-mode"])
def test_two_whole_snapshots_reject_earlier_file_or_parent_drift(tmp_path, monkeypatch, operation,
                                                               mutation):
    tree = _tree(tmp_path)
    manifest = _build(tree)
    original = runtime._observe_snapshot
    calls = 0
    parent = _path(tree, "project_source").parent
    original_mode = stat.S_IMODE(parent.stat().st_mode)

    def observed(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 1:
            path = _path(tree, "project_source")
            if mutation == "earlier-bytes":
                path.write_bytes(b"changed earlier file\n")
            elif mutation == "earlier-inode":
                replacement = path.with_name("replacement")
                replacement.write_bytes(path.read_bytes())
                replacement.chmod(stat.S_IMODE(path.stat().st_mode))
                os.replace(replacement, path)
            else:
                path.parent.chmod(stat.S_IMODE(path.parent.stat().st_mode) ^ 0o100)
        return result

    monkeypatch.setattr(runtime, "_observe_snapshot", observed)
    try:
        _refused(lambda: _build(tree) if operation == "build" else _verify(manifest))
    finally:
        if mutation == "parent-mode":
            parent.chmod(original_mode)
    assert calls >= 2


@pytest.mark.parametrize("mutation", ["write", "same-bytes-replacement", "parent-mode"])
def test_file_read_detects_mutation_before_its_descriptor_is_closed(tmp_path, monkeypatch, mutation):
    tree = _tree(tmp_path)
    path = _path(tree, "interpreter")
    declaration = next(item for item in tree.declarations if item.role == "interpreter")
    original = runtime.os.read
    changed = False
    original_mode = stat.S_IMODE(path.parent.stat().st_mode)

    def read_and_change(fd, amount):
        nonlocal changed
        result = original(fd, amount)
        if result and not changed:
            changed = True
            if mutation == "write":
                path.write_bytes(b"changed during read\n")
            elif mutation == "same-bytes-replacement":
                replacement = path.with_name("replacement")
                replacement.write_bytes(path.read_bytes())
                replacement.chmod(stat.S_IMODE(path.stat().st_mode))
                os.replace(replacement, path)
            else:
                path.parent.chmod(stat.S_IMODE(path.parent.stat().st_mode) ^ 0o100)
        return result

    monkeypatch.setattr(runtime.os, "read", read_and_change)
    try:
        _refused(lambda: runtime._observe_file(tree.roots["runtime"], declaration,
                                              runtime.MAX_PYTHON_RUNTIME_FILE_BYTES))
    finally:
        if mutation == "parent-mode":
            path.parent.chmod(original_mode)
    assert changed


@pytest.mark.parametrize("failure", ["os-error", "keyboard-interrupt"])
def test_file_descriptor_is_closed_after_read_failure_or_interrupt(tmp_path, monkeypatch, failure):
    tree = _tree(tmp_path)
    declaration = next(item for item in tree.declarations if item.role == "interpreter")
    original_open = runtime.os.open
    original_close = runtime.os.close
    opened = set()
    closed = set()

    def tracked_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def tracked_close(fd):
        closed.add(fd)
        return original_close(fd)

    def failing_read(*_args, **_kwargs):
        if failure == "keyboard-interrupt":
            raise KeyboardInterrupt("fixture interruption")
        raise OSError("fixture read failure")

    monkeypatch.setattr(runtime.os, "open", tracked_open)
    monkeypatch.setattr(runtime.os, "close", tracked_close)
    monkeypatch.setattr(runtime.os, "read", failing_read)
    if failure == "keyboard-interrupt":
        with pytest.raises(KeyboardInterrupt):
            runtime._observe_file(tree.roots["runtime"], declaration,
                                  runtime.MAX_PYTHON_RUNTIME_FILE_BYTES)
    else:
        _refused(lambda: runtime._observe_file(tree.roots["runtime"], declaration,
                                              runtime.MAX_PYTHON_RUNTIME_FILE_BYTES))
    assert opened
    assert opened == closed
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("bound", ["files", "roots", "file-bytes", "total-bytes", "manifest-bytes"])
def test_inventory_bounds_refuse_before_claiming_a_valid_manifest(tmp_path, monkeypatch, bound):
    tree = _tree(tmp_path)
    if bound == "files":
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_FILES", len(tree.declarations) - 1)
        _refused(lambda: _build(tree))
    elif bound == "roots":
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_ROOTS", len(tree.roots) - 1)
        _refused(lambda: _build(tree))
    elif bound == "file-bytes":
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_FILE_BYTES", 1)
        _refused(lambda: _build(tree))
    elif bound == "total-bytes":
        largest = max(_path(tree, item.role).stat().st_size for item in tree.declarations)
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TOTAL_BYTES", largest)
        _refused(lambda: _build(tree))
    else:
        raw = _build(tree).to_json()
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_MANIFEST_BYTES", len(raw) - 1)
        _refused(lambda: runtime.parse_python_runtime_manifest(raw))


def test_sparse_oversized_file_is_rejected_without_reading_its_bytes(tmp_path, monkeypatch):
    tree = _tree(tmp_path)
    path = _path(tree, "project_resource")
    with path.open("wb") as target:
        target.truncate(runtime.MAX_PYTHON_RUNTIME_FILE_BYTES + 1)

    def forbidden(*_args, **_kwargs):
        pytest.fail("oversized sparse file was read before checking its stat bound")

    declaration = next(item for item in tree.declarations if item.role == "project_resource")
    monkeypatch.setattr(runtime.os, "read", forbidden)
    _refused(lambda: runtime._observe_file(tree.roots["assets"], declaration,
                                          runtime.MAX_PYTHON_RUNTIME_FILE_BYTES))


@pytest.mark.parametrize("mutation", ["duplicate-file", "file-identity-alias", "root-identity-alias",
                                      "duplicate-import", "reverse-roots", "reverse-imports",
                                      "missing-ancestor-pin", "extra-directory-pin", "conflicting-ancestor",
                                      "unused-root", "entrypoint-mismatch", "listed-hook",
                                      "no-interpreter", "float-stat", "integer-policy"])
def test_resigned_manifests_cannot_forge_structural_relationships(tmp_path, mutation):
    data = _build(_tree(tmp_path)).to_dict()
    if mutation == "duplicate-file":
        data["files"].insert(1, dict(data["files"][0]))
    elif mutation == "file-identity-alias":
        for field in ("device", "inode"):
            data["files"][1][field] = data["files"][0][field]
    elif mutation == "root-identity-alias":
        other = data["roots"][1]
        for field in ("device", "inode"):
            other[field] = data["roots"][0][field]
            next(item for item in other["directories"] if item["path"] == other["path"])[field] = other[field]
    elif mutation == "duplicate-import":
        data["import_roots"].insert(1, dict(data["import_roots"][0]))
    elif mutation == "reverse-roots":
        data["roots"].reverse()
    elif mutation == "reverse-imports":
        data["import_roots"].reverse()
    elif mutation == "missing-ancestor-pin":
        data["roots"][0]["directories"].pop(0)
    elif mutation == "extra-directory-pin":
        directories = data["roots"][0]["directories"]
        directories.append({"path": "/unrelated-directory", "device": 1, "inode": 1, "mode": 0o700})
        directories.sort(key=lambda item: item["path"])
    elif mutation == "conflicting-ancestor":
        data["roots"][1]["directories"][0]["inode"] += 1
    elif mutation == "unused-root":
        data["files"] = [item for item in data["files"] if item["root_label"] != "assets"]
    elif mutation == "entrypoint-mismatch":
        data["entrypoint"]["relative_path"] = "src/other.py"
    elif mutation == "listed-hook":
        next(item for item in data["files"] if item["role"] == "extension")["relative_path"] = "site/injected.pth"
    elif mutation == "no-interpreter":
        data["files"] = [item for item in data["files"] if item["role"] != "interpreter"]
    elif mutation == "float-stat":
        data["files"][0]["mtime_ns"] = float(data["files"][0]["mtime_ns"])
    else:
        data["policy"]["user_site"] = 0
    _refused(lambda: runtime.parse_python_runtime_manifest(_resign(data)))


def test_parser_is_pure_json_and_does_not_resolve_or_open_declared_paths(tmp_path, monkeypatch):
    manifest = _build(_tree(tmp_path))
    raw = manifest.to_json()

    def forbidden(*_args, **_kwargs):
        pytest.fail("parsing a declaration attempted filesystem observation")

    for name in ("open", "stat", "lstat", "read"):
        monkeypatch.setattr(runtime.os, name, forbidden)
    for name in ("stat", "lstat", "resolve", "exists", "is_file", "is_dir"):
        monkeypatch.setattr(Path, name, forbidden)
    assert runtime.parse_python_runtime_manifest(raw) == manifest


@pytest.mark.parametrize("location", ["target", "file", "root"])
def test_nested_duplicate_json_keys_are_refused(tmp_path, location):
    raw = _build(_tree(tmp_path)).to_json()
    field, encoded_value = {
        "target": (b'"platform":"linux"', b'"platform":"linux","platform":"linux"'),
        "file": (b'"role":"project_resource"', b'"role":"project_resource","role":"project_resource"'),
        "root": (b'"label":"assets"', b'"label":"assets","label":"assets"'),
    }[location]
    assert raw.count(field) == 1
    _refused(lambda: runtime.parse_python_runtime_manifest(raw.replace(field, encoded_value, 1)))


@pytest.mark.parametrize("value", [b"\xff", "\ud800", b"{}", b"[]", None, bytearray(b"{}"),
                                   b'{"value":NaN}', b'{"value":Infinity}'])
def test_invalid_json_types_encodings_and_nonfinite_values_are_refused(value):
    _refused(lambda: runtime.parse_python_runtime_manifest(value))


@pytest.mark.parametrize("mutation", ["leaf-symlink", "parent-symlink", "hardlink", "fifo",
                                      "directory", "setuid", "setgid"])
def test_initial_unsafe_files_cannot_become_an_accepted_manifest(tmp_path, mutation):
    tree = _tree(tmp_path)
    path = _path(tree, "extension")
    if mutation == "parent-symlink":
        original = path.parent
        retained = original.with_name("retained-site")
        original.rename(retained)
        original.symlink_to(retained, target_is_directory=True)
    elif mutation == "hardlink":
        os.link(path, path.with_name("alias.so"))
    elif mutation in {"setuid", "setgid"}:
        if mutation == "setgid":
            os.chown(path, -1, os.getegid())
        path.chmod(path.stat().st_mode | (stat.S_ISUID if mutation == "setuid" else stat.S_ISGID))
        assert path.stat().st_mode & (stat.S_ISUID if mutation == "setuid" else stat.S_ISGID)
    else:
        content = path.read_bytes()
        path.unlink()
        if mutation == "leaf-symlink":
            retained = path.with_name("retained.so")
            retained.write_bytes(content)
            path.symlink_to(retained)
        elif mutation == "fifo":
            os.mkfifo(path)
        else:
            path.mkdir()
    _refused(lambda: _build(tree))


@pytest.mark.parametrize("declaration", ["oversized-utf8", "too-many-components", "nul", "newline"])
def test_declared_path_bounds_and_control_characters_are_refused(declaration):
    relative = {
        "oversized-utf8": "字" * 1400,
        "too-many-components": "/".join(["a"] * 129),
        "nul": "src/bad\x00.py", "newline": "src/bad\n.py",
    }[declaration]
    _refused(lambda: runtime.PythonRuntimeFileDeclaration("project", relative, "project_source"))


@pytest.mark.parametrize("label", ["", "../escape", "a" * 129, True, "space label"])
def test_root_labels_are_bounded_identifiers(label):
    _refused(lambda: runtime.PythonRuntimeImportRoot(label))


def test_import_root_dot_is_explicit_and_a_file_cannot_be_an_import_directory(tmp_path):
    tree = _tree(tmp_path)
    dot = runtime.PythonRuntimeImportRoot("project")
    manifest = _build(tree, import_roots=(*tree.imports, dot))
    assert dot.relative_path == "."
    assert _verify(manifest).file_count == len(tree.declarations)
    invalid = runtime.PythonRuntimeImportRoot("project", "src/main.py")
    _refused(lambda: _build(tree, import_roots=(*tree.imports, invalid)))


@pytest.mark.parametrize("operation", ["build", "verify"])
@pytest.mark.parametrize("snapshot_number", [1, 2])
def test_changes_to_an_earlier_file_while_a_later_file_is_read_are_not_missed(tmp_path, monkeypatch,
                                                                           operation, snapshot_number):
    tree = _tree(tmp_path)
    manifest = _build(tree)
    earliest = manifest.files[0]
    earliest_path = tree.roots[earliest.root_label] / earliest.relative_path
    latest = manifest.files[-1]
    original = runtime._observe_file
    changed = False
    snapshots = 0

    def observed(root, declaration, maximum_bytes):
        nonlocal changed, snapshots
        result = original(root, declaration, maximum_bytes)
        if (declaration.root_label, declaration.relative_path) == (
                latest.root_label, latest.relative_path):
            snapshots += 1
            if snapshots == snapshot_number:
                changed = True
                earliest_path.write_bytes(b"changed after earlier read\n")
        return result

    monkeypatch.setattr(runtime, "_observe_file", observed)
    _refused(lambda: _build(tree) if operation == "build" else _verify(manifest))
    assert changed


@pytest.mark.parametrize("mutation", ["swap-before-open", "symlink-before-open"])
def test_change_between_path_stat_and_descriptor_open_is_refused(tmp_path, monkeypatch, mutation):
    tree = _tree(tmp_path)
    path = _path(tree, "extension")
    declaration = next(item for item in tree.declarations if item.role == "extension")
    original_open = runtime.os.open
    changed = False

    def changed_open(name, flags, *args, **kwargs):
        nonlocal changed
        if name == path.name and kwargs.get("dir_fd") is not None and not changed:
            changed = True
            replacement = path.with_name("replacement.so")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(stat.S_IMODE(path.stat().st_mode))
            if mutation == "swap-before-open":
                os.replace(replacement, path)
            else:
                path.unlink()
                path.symlink_to(replacement)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(runtime.os, "open", changed_open)
    _refused(lambda: runtime._observe_file(tree.roots["deps"], declaration,
                                          runtime.MAX_PYTHON_RUNTIME_FILE_BYTES))
    assert changed


def test_successful_inventory_and_verification_close_all_opened_descriptors(tmp_path, monkeypatch):
    tree = _tree(tmp_path)
    original_open = runtime.os.open
    original_close = runtime.os.close
    live = set()
    opens = 0

    def opened(*args, **kwargs):
        nonlocal opens
        fd = original_open(*args, **kwargs)
        assert fd not in live
        live.add(fd)
        opens += 1
        return fd

    def closed(fd):
        assert fd in live
        live.remove(fd)
        return original_close(fd)

    monkeypatch.setattr(runtime.os, "open", opened)
    monkeypatch.setattr(runtime.os, "close", closed)
    manifest = _build(tree)
    assert not live
    assert _verify(manifest).file_count == len(tree.declarations)
    assert opens >= 4 * len(tree.declarations)
    assert not live
