"""Predispatch object checks consume the original worker inventory FDs once.

Only inert bytes and doubled kernel/Podman boundaries are used. These finite
format checks confer no immutable-custody, driver, drain or runtime authority.
"""

from __future__ import annotations

import os
import stat
import struct

import pytest

from tests import test_static_python_rsi_vfs_lifetime as lifetime_tests
from tests import test_static_python_worker_input_view as worker_tests
from tests.test_static_python_link_objects import archive_bytes, object_bytes
from tools.static_python_rsi_fixture import podman_vfs_lifetime as lifetime
from tools.static_python_rsi_fixture import podman_vfs_snapshots as retained
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

worker_owner_vector = worker_tests.worker_owner_vector
original_vector = lifetime_tests.original_vector
retained_vector = lifetime_tests.retained_vector
service_root_double = lifetime_tests.service_root_double
row, write, held_root = worker_tests.row, worker_tests.write, worker_tests.held_root
REFUSALS = (ValueError, OSError, BuildExecutionError)


def llvm_option_object():
    raw = object_bytes(b"/ambient/undeclared.a\0")
    section = struct.unpack_from("<Q", raw, 40)[0] + 64
    return raw[:section + 4] + struct.pack("<I", 0x6FFF4C01) + raw[section + 8:]


def ar_argv(*inputs):
    return ["@toolchain/zig", "ar", "rcsD", "@work/libraries/result.a", *inputs]


def direct_link_argv(*, standalone=False):
    role = "standalone-linker" if standalone else "zig-lld"
    executable = (["@toolchain/standalone-linker/bin/ld.lld"] if standalone else
                  ["@toolchain/zig", "ld.lld"])
    return [*executable, "-m", "elf_x86_64", "-static", "--no-dynamic-linker", "-o",
            "@work/bin/lunar-shinka", "@toolchain/" + role + "/support/crt1.o",
            "@work/objects/unit.o", "--start-group", "@toolchain/" + role + "/support/libc.a",
            "@toolchain/" + role + "/support/libcompiler_rt.a", "--end-group",
            "--dependency-file", "@work/link-dependencies/bin/lunar-shinka.d"]


def link_inventories(argv):
    result = {"source": [row("unit.c", b"source bytes")], "toolchain": [], "work": []}
    for reference in argv:
        if reference.startswith(("@toolchain/", "@work/")) and reference.endswith((".o", ".a")):
            role, path = reference[1:].split("/", 1)
            result[role].append(row(path, archive_bytes() if path.endswith(".a") else object_bytes()))
    return result


@pytest.mark.parametrize("standalone", [False, True])
def test_exact_direct_link_inputs_exclude_executable_output_and_depfile(standalone):
    argv = direct_link_argv(standalone=standalone)
    inventories = link_inventories(argv)
    expected = {role: sorted(record["path"] for record in records)
                for role, records in inventories.items()}
    expected["source"] = []
    assert lifetime._worker_link_inputs(argv, inventories) == expected


@pytest.mark.parametrize("explicit", [False, True])
def test_zig_cc_links_select_exact_prior_and_explicit_support_inputs(explicit):
    target = "@work/bin/lunar-shinka"
    work = ["@work/objects/unit.o", "@work/libraries/python.a"]
    support = ["@toolchain/lunar-support/" + name for name in (
        "crt1.o", "crti.o", "libc.a", "libcompiler_rt.a", "crtn.o")]
    argv = ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static"]
    if explicit:
        argv += ["-nostdlib", "-o", target, *support[:2], *work, "-Xlinker", "--start-group",
                 *support[2:4], "-Xlinker", "--end-group", support[4]]
    else:
        argv += ["-o", target, *work, "-lm", "-lpthread", "-lc"]
    argv += ["-Xlinker", "--dependency-file", "-Xlinker", "@work/link-dependencies/bin/lunar-shinka.d"]
    inventories = link_inventories(argv)
    assert lifetime._worker_link_inputs(argv, inventories) == {
        "source": [], "toolchain": sorted(ref.removeprefix("@toolchain/") for ref in support) if explicit else [],
        "work": ["libraries/python.a", "objects/unit.o"]}


def test_ar_selects_prior_objects_and_compilation_keeps_all_roles_stream_only():
    inventories = {"source": [row("source.o", b"source is data")],
                   "toolchain": [row("unused.a", b"unselected support data")],
                   "work": [row("objects/a.o", object_bytes()), row("objects/b.o", object_bytes(b"b"))]}
    assert lifetime._worker_link_inputs(ar_argv("@work/objects/b.o", "@work/objects/a.o"), inventories) == {
        "source": [], "toolchain": [], "work": ["objects/a.o", "objects/b.o"]}
    compilation = ["@toolchain/zig", "cc", "-c", "@source/source.o", "-o", "@work/objects/new.o"]
    assert lifetime._worker_link_inputs(compilation, inventories) == {role: [] for role in inventories}


@pytest.mark.parametrize("change", ["missing", "duplicate-reference", "source-reference", "directory-reference",
                                    "duplicate-record", "executable", "empty", "oversize"])
def test_original_command_cannot_select_unknown_ambiguous_or_unbounded_inputs(change):
    reference = "@work/objects/a.o"
    argv = ar_argv(reference)
    inventories = {"source": [], "toolchain": [], "work": [row("objects/a.o", object_bytes())]}
    if change == "missing":
        inventories["work"] = []
    elif change == "duplicate-reference":
        argv.append(reference)
    elif change == "source-reference":
        argv[-1] = "@source/objects/a.o"
        inventories["source"] = inventories["work"]
    elif change == "directory-reference":
        argv[-1] = "@work-dir/objects/a.o"
    elif change == "duplicate-record":
        inventories["work"].append(dict(inventories["work"][0]))
    elif change == "executable":
        inventories["work"][0]["executable"] = True
    else:
        inventories["work"][0]["size"] = 0 if change == "empty" else 128 * 1024**2 + 1
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        lifetime._worker_link_inputs(argv, inventories)


@pytest.fixture
def object_tree(tmp_path):
    root = tmp_path / "worker-role"
    root.mkdir()
    values = {"objects/a.o": object_bytes(), "libraries/a.a": archive_bytes(),
              "source/opaque.o": b"unselected source remains data", "bin/zig": b"never executed"}
    records = []
    for path, raw in sorted(values.items()):
        write(root, path, raw, executable=path == "bin/zig")
        records.append(row(path, raw, executable=path == "bin/zig"))
    return root, records, values


def observe(root, records, *, selected=None, checkpoint=lambda: None):
    with held_root(root) as fd:
        return lifetime._observe_worker_inventory(fd, records, checkpoint, link_inputs=selected)


def test_selected_formats_share_original_inventory_read_and_leave_summary_unchanged(object_tree, monkeypatch):
    root, records, values = object_tree
    read_bytes, parsed = {}, []
    real_read = os.read
    original_object = lifetime.inspect_static_python_relocatable_elf
    original_archive = lifetime.inspect_static_python_link_archive

    def count_read(fd, size):
        raw = real_read(fd, size)
        info = os.fstat(fd)
        if raw and stat.S_ISREG(info.st_mode):
            read_bytes[info.st_ino] = read_bytes.get(info.st_ino, 0) + len(raw)
        return raw

    def inspect_object(raw, **kwargs):
        parsed.append(("object", raw))
        return original_object(raw, **kwargs)

    def inspect_archive(raw, **kwargs):
        parsed.append(("archive", raw))
        return original_archive(raw, **kwargs)

    monkeypatch.setattr(lifetime.os, "read", count_read)
    monkeypatch.setattr(lifetime, "inspect_static_python_relocatable_elf", inspect_object)
    monkeypatch.setattr(lifetime, "inspect_static_python_link_archive", inspect_archive)
    result = observe(root, records, selected=["objects/a.o", "libraries/a.a"])
    assert result == {"inventory_sha256": retained._sha(retained._json(records)), "file_count": 4,
                      "directory_count": 5, "total_bytes": sum(map(len, values.values()))}
    assert read_bytes == {(root / record["path"]).stat().st_ino: record["size"] for record in records}
    assert parsed == [("archive", values["libraries/a.a"]), ("object", values["objects/a.o"])]


@pytest.mark.parametrize("path,raw", [
    ("selected.a", b"!<thin>\n"), ("selected.a", b"INPUT(/ambient/other.a)\n"),
    ("selected.o", b"BC\xc0\xdebitcode"), ("selected.o", llvm_option_object()),
    ("selected.a", archive_bytes([(b"autolink.o", llvm_option_object())])),
])
def test_resigned_pins_do_not_admit_thin_scripts_bitcode_or_embedded_linker_options(tmp_path, path, raw):
    write(tmp_path, path, raw)
    records = [row(path, raw)]
    assert observe(tmp_path, records)["file_count"] == 1
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        observe(tmp_path, records, selected=[path])


@pytest.mark.parametrize("change", ["pin", "execute-bit"])
def test_original_pin_and_mode_are_verified_before_format_parser(object_tree, monkeypatch, change):
    root, records, _values = object_tree
    if change == "pin":
        next(record for record in records if record["path"] == "objects/a.o")["sha256"] = "0" * 64
    else:
        (root / "objects/a.o").chmod(0o500)
    monkeypatch.setattr(lifetime, "inspect_static_python_relocatable_elf",
                        lambda *_args, **_kwargs: pytest.fail("parsed before original pin/mode gate"))
    with pytest.raises(REFUSALS):
        observe(root, records, selected=["objects/a.o"])


def test_selected_size_cap_refuses_before_body_read_or_parser(tmp_path, monkeypatch):
    path = tmp_path / "oversize.a"
    size = 128 * 1024**2 + 1
    with path.open("wb") as stream:
        stream.truncate(size)
    path.chmod(0o400)
    records = [{**row(path.name, b""), "size": size}]
    monkeypatch.setattr(lifetime.os, "read", lambda *_args: pytest.fail("read oversized selected file"))
    monkeypatch.setattr(lifetime, "inspect_static_python_link_archive",
                        lambda *_args, **_kwargs: pytest.fail("parsed oversized selected file"))
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        observe(tmp_path, records, selected=[path.name])


@pytest.mark.parametrize("change", ["leaf-symlink", "parent-symlink"])
def test_selected_inputs_cannot_replace_original_paths_with_symlinks(object_tree, tmp_path, change):
    root, records, values = object_tree
    target = root / "objects/a.o"
    if change == "leaf-symlink":
        outside = tmp_path / "outside.o"
        outside.write_bytes(values["objects/a.o"])
        target.unlink()
        target.symlink_to(outside)
    else:
        outside = tmp_path / "outside-directory"
        target.parent.rename(outside)
        target.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(REFUSALS):
        observe(root, records, selected=["objects/a.o"])


@pytest.mark.parametrize("moment", ["during-read", "after-parser"])
def test_same_byte_name_replacement_is_refused_around_original_selected_fd(
        object_tree, monkeypatch, moment):
    root, records, values = object_tree
    target = root / "objects/a.o"
    inode, raw = target.stat().st_ino, values["objects/a.o"]
    real_read = os.read
    original_parser = lifetime.inspect_static_python_relocatable_elf
    replaced = False

    def replace():
        nonlocal replaced
        if not replaced:
            replaced = True
            target.unlink()
            write(root, "objects/a.o", raw)

    def read(fd, size):
        block = real_read(fd, size)
        if block and os.fstat(fd).st_ino == inode and moment == "during-read":
            replace()
        return block

    def parser(image, **kwargs):
        result = original_parser(image, **kwargs)
        if moment == "after-parser":
            replace()
        return result

    monkeypatch.setattr(lifetime.os, "read", read)
    monkeypatch.setattr(lifetime, "inspect_static_python_relocatable_elf", parser)
    with pytest.raises(REFUSALS):
        observe(root, records, selected=["objects/a.o"])
    assert replaced and target.read_bytes() == raw and target.stat().st_ino != inode


@pytest.mark.parametrize("control", [RuntimeError("original deadline"), KeyboardInterrupt("original cancellation")])
def test_parser_checkpoint_preserves_original_control_exception_and_borrowed_role(
        object_tree, monkeypatch, control):
    root, records, _values = object_tree
    parsing = False
    original_parser = lifetime.inspect_static_python_relocatable_elf

    def parser(image, **kwargs):
        nonlocal parsing
        parsing = True
        return original_parser(image, **kwargs)

    def checkpoint():
        if parsing:
            raise control

    monkeypatch.setattr(lifetime, "inspect_static_python_relocatable_elf", parser)
    with held_root(root) as fd:
        before = os.fstat(fd)
        with pytest.raises(type(control)) as caught:
            lifetime._observe_worker_inventory(fd, records, checkpoint, link_inputs=["objects/a.o"])
        assert caught.value is control
        after = os.fstat(fd)
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)


def test_original_owner_freezes_argv_and_keeps_existing_wire_summary(worker_owner_vector, monkeypatch):
    vector = worker_owner_vector
    source, valid, opaque = b"source .o remains data", object_bytes(), b"unused object remains data"
    argv = direct_link_argv()
    inventories = link_inventories(argv)
    inventories["source"] = [row("source.o", source)]
    for role, records in inventories.items():
        for record in records:
            raw = source if role == "source" else (
                archive_bytes() if record["path"].endswith(".a") else valid)
            write(vector.root / role, record["path"], raw)
    write(vector.root / "work", "objects/unused.o", opaque)
    inputs = {role: inventories[role] for role in ("source", "toolchain")}
    prior = [*inventories["work"], row("objects/unused.o", opaque)]
    owner = vector.create()
    owner._bind_worker_inputs(inputs, prior, argv=argv)
    expected = lifetime._worker_input_summary(owner.owner, {**inputs, "work": prior})
    parsed = []
    original_parser = lifetime.inspect_static_python_relocatable_elf

    def parser(image, **kwargs):
        parsed.append(image)
        return original_parser(image, **kwargs)

    monkeypatch.setattr(lifetime, "inspect_static_python_relocatable_elf", parser)
    argv[argv.index("@work/objects/unit.o")] = "@work/objects/unused.o"
    owner.before_start()
    assert parsed == [valid, valid]
    assert vector.capture.input_view == expected
    assert set(expected) == {"schema", "phase", "owner_sha256", "roles", "claims"}
    assert vector.capture.phases[1]["links"] == {"worker_input_view_sha256": retained._sha(retained._json(expected))}
    assert all(value is False for value in expected["claims"].values())


def test_original_owner_refuses_resigned_invalid_selected_bytes_before_start_boundary(worker_owner_vector):
    vector = worker_owner_vector
    raw = llvm_option_object()
    write(vector.root / "work", "objects/autolink.o", raw)
    owner = vector.create()
    owner._bind_worker_inputs({"source": [], "toolchain": []}, [row("objects/autolink.o", raw)],
                              argv=ar_argv("@work/objects/autolink.o"))
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.before_start()
    assert owner.phase == 1 and vector.capture.input_view is None
    assert [phase["phase"] for phase in vector.capture.phases] == ["initialized"]


def test_original_custody_worker_view_forwards_exact_production_argv_before_dispatch(retained_vector, monkeypatch):
    run, evidence, _work, events, _owners = lifetime_tests.original_runner(retained_vector, monkeypatch)
    subject = retained_vector[0][0][0]
    subject.vfs_worker_input_view = True
    select_capture = subject.snapshot_store._lifetime
    forwarded = []

    def capture(stage, index, *, worker_input_view):
        assert worker_input_view is True
        return select_capture(stage, index)

    def bind(_owner, inputs, prior, *, argv):
        forwarded.append((inputs, prior, argv))
        raise BuildExecutionError("inert_exact_worker_argv_boundary")

    monkeypatch.setattr(subject.snapshot_store, "_lifetime", capture)
    monkeypatch.setattr(lifetime._VfsExecutionLifetime, "_bind_worker_inputs", bind, raising=False)
    with pytest.raises(BuildExecutionError, match="inert_exact_worker_argv_boundary"):
        run()
    assert forwarded == [({"source": [], "toolchain": [{"path": "zig", "executable": True}]},
                          [], ["@toolchain/zig", "cc"])]
    assert "start-attach" not in events and evidence["status"] == "partial"
