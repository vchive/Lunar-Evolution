"""Pure format and real retained-FD consumption; no build or image executes."""

from __future__ import annotations

import json
import struct
from dataclasses import replace

import pytest

from lunar_evolution import static_python_elf as elf
from lunar_evolution import static_python_link_objects as objects
from tests import test_static_python_retained_installation as retained_tests
from tests import test_static_python_worker_input_view_installation as worker_tests
from tests.test_static_python_retained_installation import record, sha, write
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import retained_installation as candidate
from tools.static_python_rsi_fixture import zig_support_selection as selected
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.runtime_closure import canonical
from tools.static_python_rsi_fixture.zig_lld_linker import _PREFIX, PROFILE_SCHEMA

retained_history = retained_tests.history
worker_history = worker_tests.worker_history


def object_bytes(payload=b"\x90"):
    names = b"\0.text\0.shstrtab\0"
    names_offset = 64 + len(payload)
    section_offset = (names_offset + len(names) + 7) // 8 * 8
    header = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + b"\0" * 9,
                         1, 62, 1, 0, 0, section_offset, 0, 64, 0, 0, 64, 3, 2)
    sections = (b"\0" * 64
                + struct.pack("<IIQQQQIIQQ", 1, 1, 6, 0, 64, len(payload), 0, 0, 1, 0)
                + struct.pack("<IIQQQQIIQQ", 7, 3, 0, 0, names_offset, len(names), 0, 0, 1, 0))
    return header + payload + names + b"\0" * (section_offset - names_offset - len(names)) + sections


def entry(token, data):
    assert len(token) <= 16
    header = (token.ljust(16, b" ") + b"0".ljust(12, b" ") + b"0".ljust(6, b" ")
              + b"0".ljust(6, b" ") + b"644".ljust(8, b" ")
              + str(len(data)).encode().ljust(10, b" ") + b"`\n")
    return header + data + (b"\n" if len(data) % 2 else b"")


def archive_bytes(items=None, *, symbols=0):
    items = [(b"unit.o", object_bytes())] if items is None else items
    names, tokens = b"", []
    for name, _raw in items:
        if len(name) > 15 or b"/" in name:
            tokens.append(b"/" + str(len(names)).encode())
            names += name + b"/\n"
        else:
            tokens.append(name + b"/")
    names_entry = entry(b"//", names + (b"\n" if len(names) % 2 else b"")) if names else b""
    members = [entry(token, raw) for token, (_name, raw) in zip(tokens, items, strict=True)]
    symbol_entry = b""
    if symbols:
        symbol_names = b"".join(b"symbol" + str(index).encode() + b"\0" for index in range(len(items)))
        payload_size = symbols * (len(items) + 1) + len(symbol_names)
        offset = 8 + 60 + payload_size + payload_size % 2 + len(names_entry)
        offsets = []
        for member in members:
            offsets.append(offset)
            offset += len(member)
        payload = len(items).to_bytes(symbols, "big") + b"".join(
            offset.to_bytes(symbols, "big") for offset in offsets) + symbol_names
        symbol_entry = entry(b"/" if symbols == 4 else b"/SYM64/", payload)
    return b"!<arch>\n" + symbol_entry + names_entry + b"".join(members)


def object_header(raw, index, value):
    header = list(struct.unpack_from("<16sHHIQQQIHHHHHH", raw))
    header[index] = value
    return struct.pack("<16sHHIQQQIHHHHHH", *header) + raw[64:]


def rich_object_bytes():
    """An inert object with real linked string/symbol/relocation/group tables."""
    payloads = [b"\0" * 8, b"\0symbol\0",
                b"\0" * 24 + struct.pack("<IBBHQQ", 1, 0x10, 0, 1, 0, 8),
                struct.pack("<QQq", 0, (1 << 32) | 1, 0), struct.pack("<II", 1, 1)]
    metadata = [(1, 6, 0, 0, 1, 0), (3, 0, 0, 0, 1, 0), (2, 0, 2, 1, 8, 24),
                (4, 0, 3, 1, 8, 24), (17, 0, 3, 1, 4, 4)]
    body, sections, offsets = b"", [b"\0" * 64], []
    for payload, (kind, flags, link, info, alignment, item_size) in zip(payloads, metadata, strict=True):
        body += b"\0" * (-len(body) % 8)
        offset = 64 + len(body)
        offsets.append(offset)
        sections.append(struct.pack("<IIQQQQIIQQ", 0, kind, flags, 0, offset, len(payload),
                                    link, info, alignment, item_size))
        body += payload
    body += b"\0" * (-len(body) % 8)
    header = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + b"\0" * 9,
                         1, 62, 1, 0, 0, 64 + len(body), 0, 64, 0, 0, 64, len(sections), 0)
    return header + body + b"".join(sections), offsets


@pytest.mark.parametrize("symbols", [0, 4, 8])
@pytest.mark.parametrize("name", [b"unit.o", b".zig-global-cache/o/0123456789abcdef/long_compiler_runtime_zcu.o"])
def test_inline_short_long_and_both_gnu_symbol_widths(symbols, name):
    raw = archive_bytes([(name, object_bytes())], symbols=symbols)
    facts = objects.inspect_static_python_link_archive(raw)
    assert facts.member_count == 1 and facts.symbol_count == bool(symbols)
    assert facts.sha256 == sha(raw) and facts.size == len(raw)
    assert facts.production_admission is False


def test_multiple_inline_members_and_duplicate_embedded_names_are_not_external_paths():
    raw = archive_bytes([(b"duplicate.o", object_bytes()), (b"duplicate.o", object_bytes(b"\xc3"))], symbols=4)
    assert objects.inspect_static_python_link_archive(raw).member_count == 2


@pytest.mark.parametrize("raw", [b"!<thin>\n", b"INPUT(/ambient/other.a)\n", b"GROUP(libc.a)\n",
                                  b"!<arch>\n", b"!<arch>\ntrailing", b"#!/bin/sh\n"])
def test_thin_scripts_empty_and_incomplete_archives_refuse(raw):
    with pytest.raises(objects.StaticPythonLinkObjectError):
        objects.inspect_static_python_link_archive(raw)


@pytest.mark.parametrize("name", [b"/ambient/foreign.o", b"../foreign.o", b"cache/../foreign.o",
                                   b"cache//foreign.o", b"C:foreign.o", b"cache\\foreign.o",
                                   b"__.SYMDEF", b"__.SYMDEF_64"])
def test_long_embedded_names_cannot_supply_absolute_or_parent_paths(name):
    with pytest.raises(objects.StaticPythonLinkObjectError):
        objects.inspect_static_python_link_archive(archive_bytes([(name, object_bytes())]))


@pytest.mark.parametrize("change", [
    lambda raw: raw[:56] + b"9999999999" + raw[66:],
    lambda raw: raw[:66] + b"xx" + raw[68:],
    lambda raw: raw + b"x",
    lambda raw: raw[:-1],
    lambda raw: raw[:24] + b"-" + raw[25:],
])
def test_archive_header_extent_and_trailing_bytes_refuse(change):
    with pytest.raises((objects.StaticPythonLinkObjectError, elf.StaticPythonELFError)):
        objects.inspect_static_python_link_archive(change(archive_bytes()))


def test_odd_length_payload_requires_its_original_newline_padding():
    raw = b"!<arch>\n" + entry(b"//", b"long_name_for_an_object.o/\n") + entry(b"/0", object_bytes())
    assert objects.inspect_static_python_link_archive(raw).member_count == 1
    first_length = int(raw[56:66])
    assert first_length % 2 == 1
    at = 68 + first_length
    with pytest.raises(objects.StaticPythonLinkObjectError, match="extent"):
        objects.inspect_static_python_link_archive(raw[:at] + b"x" + raw[at + 1:])


@pytest.mark.parametrize("token", [b"/1", b"/9999", b"/bad", b"#1/8", b"#1/8/", b"/SYMOTHER/"])
def test_long_names_must_reference_an_exact_prior_entry_start(token):
    raw = b"!<arch>\n" + entry(b"//", b"long_name_for_an_object.o/\n") + entry(token, object_bytes())
    with pytest.raises(objects.StaticPythonLinkObjectError):
        objects.inspect_static_python_link_archive(raw)


@pytest.mark.parametrize("symbols", [4, 8])
@pytest.mark.parametrize("change", ["offset", "count", "unterminated", "duplicate"])
def test_symbol_table_counts_names_and_object_offsets_are_bounded(symbols, change):
    raw = archive_bytes(symbols=symbols)
    if change == "offset":
        raw = raw[:68 + symbols] + (9).to_bytes(symbols, "big") + raw[68 + symbols * 2:]
    elif change == "count":
        raw = raw[:68] + (objects._MAX_SYMBOLS + 1).to_bytes(symbols, "big") + raw[68 + symbols:]
    elif change == "unterminated":
        symbol_end = 68 + int(raw[56:66])
        raw = raw[:symbol_end - 1] + b"x" + raw[symbol_end:]
    else:
        table_end = 68 + int(raw[56:66]) + int(raw[56:66]) % 2
        raw = raw[:table_end] + raw[8:table_end] + raw[table_end:]
    with pytest.raises(objects.StaticPythonLinkObjectError):
        objects.inspect_static_python_link_archive(raw)


@pytest.mark.parametrize("index,value", [(1, 2), (2, 183), (3, 2), (4, 1), (5, 64),
                                        (7, 1), (9, 56), (10, 1), (11, 32),
                                        (12, 4097), (13, 0xffff), (6, (1 << 64) - 8)])
def test_relocatable_wrong_architecture_type_program_tables_and_bounds_refuse(index, value):
    with pytest.raises(elf.StaticPythonELFError):
        elf.inspect_static_python_relocatable_elf(object_header(object_bytes(), index, value))


@pytest.mark.parametrize("field,value", [(1, 6), (1, 11), (1, 18), (3, 1), (4, 1 << 63),
                                        (5, 1 << 63), (6, 3), (8, 3), (9, 3)])
def test_relocatable_section_layout_and_dynamic_routes_refuse(field, value):
    raw = object_bytes()
    start = struct.unpack_from("<Q", raw, 40)[0] + 64
    section = list(struct.unpack_from("<IIQQQQIIQQ", raw, start))
    section[field] = value
    changed = raw[:start] + struct.pack("<IIQQQQIIQQ", *section) + raw[start + 64:]
    with pytest.raises(elf.StaticPythonELFError):
        elf.inspect_static_python_relocatable_elf(changed)


@pytest.mark.parametrize("kind", [0x6FFF4C01, 0x6FFF4C04])
def test_llvm_embedded_linker_options_and_dependent_libraries_refuse_even_inside_archives(kind):
    raw = object_bytes(b"/ambient/undeclared.a\0")
    start = struct.unpack_from("<Q", raw, 40)[0] + 64
    changed = raw[:start + 4] + struct.pack("<I", kind) + raw[start + 8:]
    with pytest.raises(elf.StaticPythonELFError, match="external_input"):
        objects.inspect_static_python_link_archive(archive_bytes([(b"autolink.o", changed)]))


@pytest.mark.parametrize("kind", [0x6FFF4C03, 0x70000001])
def test_retained_addrsig_and_x86_unwind_metadata_do_not_select_additional_files(kind):
    raw = object_bytes(b"\0" * 8)
    start = struct.unpack_from("<Q", raw, 40)[0] + 64
    changed = raw[:start + 4] + struct.pack("<I", kind) + raw[start + 8:]
    assert elf.inspect_static_python_relocatable_elf(changed).elf_type == "ET_REL"


def test_fat_lto_section_is_an_unreviewed_bitcode_route_even_with_an_elf_container():
    raw = object_bytes(b"BC\xc0\xdefat-lto")
    start = struct.unpack_from("<Q", raw, 40)[0] + 64
    changed = raw[:start + 4] + struct.pack("<I", 0x6FFF4C0C) + raw[start + 8:]
    with pytest.raises(elf.StaticPythonELFError, match="bitcode"):
        objects.inspect_static_python_link_archive(archive_bytes([(b"fat.o", changed)]))


def test_original_executable_and_relocatable_profiles_remain_separate():
    raw = object_bytes()
    facts = elf.inspect_static_python_relocatable_elf(raw)
    assert facts.sha256 == sha(raw) and facts.section_header_count == 3
    with pytest.raises(elf.StaticPythonELFError):
        elf.inspect_static_python_elf(raw)
    with pytest.raises(elf.StaticPythonELFError):
        objects.inspect_static_python_link_archive(archive_bytes([(b"unit.o", b"BC\xc0\xdebitcode")]))


def test_linked_symbol_relocation_and_group_payloads_are_consumed_as_structures():
    raw, _offsets = rich_object_bytes()
    assert elf.inspect_static_python_relocatable_elf(raw).section_header_count == 6


@pytest.mark.parametrize("change", ["symbol_name", "symbol_section", "symbol_value", "symbol_size",
                                    "symbol_null", "relocation_symbol", "relocation_offset",
                                    "group_flag", "group_member", "group_self"])
def test_inner_symbol_relocation_and_group_indices_cannot_escape_their_tables(change):
    raw, offsets = rich_object_bytes()
    data = bytearray(raw)
    symbol = offsets[2] + 24
    if change == "symbol_name":
        struct.pack_into("<I", data, symbol, 99)
    elif change == "symbol_section":
        struct.pack_into("<H", data, symbol + 6, 0xFFFF)
    elif change == "symbol_value":
        struct.pack_into("<Q", data, symbol + 8, 9)
    elif change == "symbol_size":
        struct.pack_into("<Q", data, symbol + 16, 9)
    elif change == "symbol_null":
        data[offsets[2]] = 1
    elif change == "relocation_symbol":
        struct.pack_into("<Q", data, offsets[3] + 8, (2 << 32) | 1)
    elif change == "relocation_offset":
        struct.pack_into("<Q", data, offsets[3], 8)
    elif change == "group_flag":
        struct.pack_into("<I", data, offsets[4], 2)
    else:
        struct.pack_into("<I", data, offsets[4] + 4, 99 if change == "group_member" else 5)
    with pytest.raises(elf.StaticPythonELFError):
        elf.inspect_static_python_relocatable_elf(bytes(data))


def test_object_entry_budget_is_finite_across_symbol_relocation_and_group_tables(monkeypatch):
    raw, _offsets = rich_object_bytes()
    monkeypatch.setattr(elf, "_MAX_RELOCATABLE_ENTRIES", 2)
    with pytest.raises(elf.StaticPythonELFError, match="limits"):
        elf.inspect_static_python_relocatable_elf(raw)


@pytest.mark.parametrize("kind", ["members", "size", "names"])
def test_archive_resource_limits_precede_unbounded_work(monkeypatch, kind):
    raw = archive_bytes([(b"long_name_for_an_object.o", object_bytes())])
    monkeypatch.setattr(objects, {"members": "MAX_LINK_ARCHIVE_MEMBERS", "size": "MAX_LINK_ARCHIVE_BYTES",
                                  "names": "_MAX_NAMES"}[kind], 0)
    with pytest.raises(objects.StaticPythonLinkObjectError):
        objects.inspect_static_python_link_archive(raw)


@pytest.mark.parametrize("inspector,raw", [(objects.inspect_static_python_link_archive, archive_bytes()),
                                          (elf.inspect_static_python_relocatable_elf, object_bytes())])
def test_original_checkpoint_is_used_inside_parsing_and_hashing(inspector, raw):
    calls = []

    def stop():
        calls.append(None)
        if len(calls) == 4:
            raise TimeoutError("original deadline")

    with pytest.raises(TimeoutError):
        inspector(raw, checkpoint=stop)
    assert len(calls) == 4


@pytest.fixture
def staging(tmp_path, monkeypatch):
    prep = RSIProfilePreparation(b"synthetic unaccepted preparation")
    tool_root = tmp_path / "tools"
    tool_root.mkdir()
    zig = b"synthetic tool never executed"
    tools = [record("zig", zig, True)]
    write(tool_root, "zig", zig, 0o500)
    monkeypatch.setattr(selected, "complete_zig_inventory", lambda _raw: tools)

    def controls(replacements=None):
        files = {"zig-lld/support/crt1.o": object_bytes(),
                 "zig-lld/support/libc.a": archive_bytes(),
                 "zig-lld/support/libcompiler_rt.a": archive_bytes()}
        files.update(replacements or {})
        rows = [record(path, raw) for path, raw in sorted(files.items())]
        profile = canonical({"schema": PROFILE_SCHEMA, "target": "x86_64-linux-musl",
                             "linker_execution": "static-x86_64-elf", "crt_mode": "crt1",
                             "archives": ["libc.a", "libcompiler_rt.a"], "inputs": [*tools, *rows]})
        # Profile rows must retain canonical path order, as the original selector requires.
        profile_data = json.loads(profile)
        profile_data["inputs"].sort(key=lambda row: row["path"])
        profile = canonical(profile_data)
        support = [{**row, "candidate_path": "candidates/global/o/fixed/" + row["path"].split("/")[-1]}
                   for row in rows]
        manifest = canonical({"schema": selected._SCHEMA, "preparation_sha256": prep.sha256,
                              "candidate_bundle_sha256": sha(b"synthetic bundle"),
                              "zig_inventory_sha256": sha(canonical(tools)),
                              "zig_lld_profile_sha256": sha(profile), "support": support,
                              "seed_executed": False, **selected._FALSE})
        selection = selected.ZigLLDSupportSelection(manifest, tuple(sorted(files.items())))
        return {"selection": selection, "expected_selection_sha256": selection.sha256,
                "zig_manifest_bytes": b"synthetic fixed inventory", "zig_lld_profile_bytes": profile,
                "expected_zig_lld_profile_sha256": sha(profile), "toolchain_root": tool_root,
                "deadline": 100.0, "monotonic": lambda: 10.0}

    return prep, controls, tool_root


def test_strict_staging_consumes_original_pinned_bytes_into_fresh_namespace(staging):
    prep, controls, root = staging
    options = controls()
    selected.stage_zig_lld_support_selection_object_format(prep, **options)
    assert {path: (root / path).read_bytes() for path, _raw in options["selection"].files} == dict(
        options["selection"].files)


@pytest.mark.parametrize("path,raw", [("zig-lld/support/crt1.o", object_header(object_bytes(), 2, 183)),
                                     ("zig-lld/support/libc.a", b"!<thin>\n"),
                                     ("zig-lld/support/libcompiler_rt.a", b"INPUT(/ambient.a)")])
def test_strict_staging_refuses_pinned_but_unsupported_formats_before_writes(staging, path, raw):
    prep, controls, root = staging
    options = controls({path: raw})
    with pytest.raises(selected.ZigSupportSelectionError, match="object_format"):
        selected.stage_zig_lld_support_selection_object_format(prep, **options)
    assert not (root / "zig-lld").exists()
    # The old API deliberately retains its former byte-only profile.
    selected.stage_zig_lld_support_selection(prep, **options)
    assert (root / path).read_bytes() == raw


def _refresh_strict_history(history):
    wire, options = history["wire"], history["options"]
    root = options["workspace"]
    stages = []
    for stage in wire["stages"]:
        commands, stage_outputs = [], []
        for index, command in enumerate(stage["commands"]):
            rows = []
            for planned in command["outputs"]:
                raw = history["output_bytes"][planned["path"]]
                planned["max_size"] = len(raw) + 1024
                rows.append(record(planned["path"], raw, planned["executable"]))
                write(root / "work", planned["path"], raw, 0o711 if planned["executable"] else 0o600)
            commands.append({"index": index, "status": "complete", "returncode": 0,
                             "direct_child_reaped": True, "outputs": rows, "custody": {"synthetic": True}})
            stage_outputs.extend(rows)
        stages.append({"stage": stage["stage"], "status": "complete", "commands": commands,
                       "outputs": stage_outputs})
    raw = canonical(wire)
    report = replace(history["build"].execution_report, recipe_sha256=sha(raw), stage_evidence=tuple(stages))
    report_raw, outputs = consumer._report_outputs(
        report, wire, worker_tests.BACKEND, version4=True, workspace=root, checkpoint=lambda: None,
        vfs_roots=True, vfs_retained=True, vfs_lifetime=True, vfs_worker_input_view=True)
    inventory = canonical(outputs)
    common = {"recipe_sha256": sha(raw), "manifest_sha256": options["expected_manifest_sha256"],
              "output_inventory_sha256": sha(inventory), "inputs_sha256": sha(canonical(wire["inputs"]))}
    for name in ("compiler-dependency-comparison.json", "linker-dependency-comparison.json"):
        data = json.loads((root / name).read_bytes())
        data.update(common)
        if name.startswith("linker"):
            data["links"] = [{"synthetic": True}, {"synthetic": True}]
        write(root, name, canonical(data))
    compiler = sha((root / "compiler-dependency-comparison.json").read_bytes())
    linker = sha((root / "linker-dependency-comparison.json").read_bytes())
    data = json.loads((root / "dependency-report.json").read_bytes())
    data.update(common, execution_report_sha256=sha(report_raw), compiler_comparison_sha256=compiler,
                linker_comparison_sha256=linker, links=2)
    write(root, "dependency-report.json", canonical(data))
    write(root, "dependency-output-inventory.json", inventory)
    write(root, "report.json", report_raw)
    history["build"] = consumer.DependencyCheckedBuild(report, sha(canonical(data)), compiler, linker, sha(inventory))
    history["outputs"] = outputs
    options.update(recipe_bytes=raw, expected_recipe_sha256=sha(raw),
                   expected_dependency_report_sha256=sha(canonical(data)))


@pytest.fixture
def strict_history(worker_history, monkeypatch):
    history = worker_history

    def original_custody_double(command, *args, checkpoint=None, **_options):
        assert command["custody"] == {"synthetic": True}
        if checkpoint:
            checkpoint()

    monkeypatch.setattr(custody, "validate_custody_observation_v6", original_custody_double)
    tools = {"zig": b"synthetic zig never executed", "zig-lld/support/crt1.o": object_bytes(),
             "zig-lld/support/libc.a": archive_bytes(), "zig-lld/support/libcompiler_rt.a": archive_bytes()}
    history["tool_bytes"] = tools

    def repin_tools():
        rows = [record(path, raw, path == "zig") for path, raw in sorted(tools.items())]
        history["wire"]["inputs"]["toolchain"] = rows
        for path, raw in tools.items():
            target = history["options"]["workspace"] / "toolchain" / path
            if target.exists():
                target.chmod(0o700 if path == "zig" else 0o600)
            write(history["options"]["workspace"] / "toolchain", path, raw, 0o500 if path == "zig" else 0o444)
        profile = canonical({"schema": PROFILE_SCHEMA, "target": "x86_64-linux-musl",
                             "linker_execution": "static-x86_64-elf", "crt_mode": "crt1",
                             "archives": ["libc.a", "libcompiler_rt.a"], "inputs": rows})
        history["format_options"] = {"zig_lld_profile_bytes": profile,
                                     "expected_zig_lld_profile_sha256": sha(profile)}

    history["repin_tools"] = repin_tools
    repin_tools()
    outputs = history["output_bytes"]
    outputs["configuration/probe.o"] = object_bytes()
    outputs["libraries/liblunarpython.a"] = archive_bytes()
    solver_image = "bin/lunar-" + history["closure"]["solver"]
    outputs["bin/lunar-freeze-module"] = outputs[solver_image]

    def direct_link(path):
        depfile = "link-dependencies/" + path + ".d"
        outputs[depfile] = b"synthetic retained link dependencies"
        return {"argv": [*_PREFIX, "@work/" + path, "@toolchain/zig-lld/support/crt1.o",
                         "@work/configuration/probe.o", "--start-group", "@toolchain/zig-lld/support/libc.a",
                         "@toolchain/zig-lld/support/libcompiler_rt.a", "--end-group",
                         "--dependency-file", "@work/" + depfile],
                "outputs": [{"path": path, "max_size": len(outputs[path]) + 1024, "executable": True},
                            {"path": depfile, "max_size": 1024, "executable": False}]}

    for stage in history["wire"]["stages"]:
        stage["commands"][0]["argv"] = ["@toolchain/zig", "synthetic-unexecuted"]
        if stage["stage"] == "freeze":
            stage["commands"].append(direct_link("bin/lunar-freeze-module"))
        elif stage["stage"] == "link":
            stage["commands"] = [{"argv": ["@toolchain/zig", "ar", "rcsD", "@work/libraries/liblunarpython.a",
                                             "@work/configuration/probe.o"],
                                   "outputs": [{"path": "libraries/liblunarpython.a", "max_size": 1024,
                                                "executable": False}]}, direct_link(solver_image)]
    _refresh_strict_history(history)
    return history


def strict_prepare(history, **overrides):
    return candidate.prepare_worker_input_view_object_format_fixed_installation_description(
        history["build"], **{**history["options"], **history["format_options"], **overrides})


def test_strict_original_retained_consumption_preserves_candidate_bytes_and_files(strict_history):
    history = strict_history
    root = history["options"]["workspace"]
    before = worker_tests.snapshot(root)
    old = worker_tests.prepare(history)
    current = strict_prepare(history)
    assert current.candidate_bytes == old.candidate_bytes
    assert current.dependency_report_sha256 == old.dependency_report_sha256
    assert all(flag is False for flag in current.to_dict()["claims"].values())
    assert worker_tests.snapshot(root) == before


@pytest.mark.parametrize("path,raw", [("zig-lld/support/crt1.o", object_header(object_bytes(), 2, 183)),
                                     ("zig-lld/support/libc.a", b"!<thin>\n"),
                                     ("zig-lld/support/libcompiler_rt.a", b"INPUT(/external/member.o)")])
def test_retained_pinned_wrong_support_format_refuses_without_changing_old_reader(strict_history, path, raw):
    history = strict_history
    history["tool_bytes"][path] = raw
    history["repin_tools"]()
    _refresh_strict_history(history)
    assert worker_tests.prepare(history).production_admission is False
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        strict_prepare(history)


def test_retained_pinned_wrong_library_format_cannot_become_a_strict_candidate(strict_history):
    history = strict_history
    history["output_bytes"]["libraries/liblunarpython.a"] = b"!<thin>\n"
    _refresh_strict_history(history)
    assert worker_tests.prepare(history).online_publication is False
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        strict_prepare(history)


@pytest.mark.parametrize("change", ["profile_pin", "profile_rows", "no_ar", "ar_future_input"])
def test_strict_reader_binds_the_independent_original_profile_and_library_graph(strict_history, change):
    history = strict_history
    options = {}
    if change == "profile_pin":
        options["expected_zig_lld_profile_sha256"] = "a" * 64
    elif change == "profile_rows":
        profile = json.loads(history["format_options"]["zig_lld_profile_bytes"])
        profile["inputs"][0]["sha256"] = "a" * 64
        raw = canonical(profile)
        options = {"zig_lld_profile_bytes": raw, "expected_zig_lld_profile_sha256": sha(raw)}
    else:
        commands = history["wire"]["stages"][-1]["commands"]
        if change == "no_ar":
            commands[0]["argv"] = ["@toolchain/zig", "synthetic-unexecuted"]
        else:
            commands[0]["argv"][-1] = "@work/objects/not-yet-produced.o"
        _refresh_strict_history(history)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        strict_prepare(history, **options)


def test_strict_reader_keeps_original_post_format_fd_readback(strict_history, monkeypatch):
    original_read = candidate._read_pin
    observed = []

    def read(root, row, checkpoint, **options):
        result = original_read(root, row, checkpoint, **options)
        if row["path"] == "libraries/liblunarpython.a" and options.get("retain"):
            observed.append(row["path"])
            (root / row["path"]).write_bytes(result + b"drift")
        return result

    monkeypatch.setattr(candidate, "_read_pin", read)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        strict_prepare(strict_history)
    assert observed == ["libraries/liblunarpython.a"]


@pytest.mark.parametrize("control", ["deadline", "interrupted"])
def test_strict_format_consumption_keeps_original_absolute_control(strict_history, monkeypatch, control):
    original = candidate.inspect_static_python_link_archive

    def inspect(raw, *, checkpoint):
        if control == "deadline":
            strict_history["controls"]["now"] = 100.0
        else:
            strict_history["controls"]["interrupt"] = True
        return original(raw, checkpoint=checkpoint)

    monkeypatch.setattr(candidate, "inspect_static_python_link_archive", inspect)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_" + control + "$"):
        strict_prepare(strict_history)


def test_strict_reader_cannot_replace_original_worker_history_validation(strict_history, monkeypatch):
    def refuse(*_args, **_options):
        raise ValueError("original worker history refused")

    monkeypatch.setattr(custody, "validate_custody_observation_v6", refuse)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        strict_prepare(strict_history)
