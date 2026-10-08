"""Synthetic ELF format tests; no compiler, process, or CPython execution proof."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from lunar_evolution import static_python_elf as elf

_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
_PROGRAM = struct.Struct("<IIQQQQQQ")
_SECTION = struct.Struct("<IIQQQQIIQQ")
_BASE = 0x400000
_UINT64 = (1 << 64) - 1
_IDENT = b"\x7fELF\x02\x01\x01" + b"\0" * 9
_FIELDS = ("ident", "kind", "machine", "version", "entry", "phoff", "shoff", "flags",
           "ehsize", "phsize", "phcount", "shsize", "shcount", "shnames")


def _load(**changes):
    return {"segment": 1, "permissions": 5, "offset": 0, "address": _BASE,
            "physical": 0, "file_size": 512, "memory_size": 512, "alignment": 4096,
            **changes}


def _image(*, programs=None, sections=(), blobs=(), size=512, **header):
    programs = [_load(file_size=size, memory_size=size)] if programs is None else programs
    values = dict(zip(_FIELDS, (_IDENT, 2, 62, 1, _BASE + 128, 64,
                               256 if sections else 0, 0, 64, 56, len(programs),
                               64 if sections else 0, len(sections) + 1 if sections else 0, 0)))
    values.update(header)
    data = bytearray(size)
    data[:64] = _HEADER.pack(*(values[key] for key in _FIELDS))
    program_fields = ("segment", "permissions", "offset", "address", "physical",
                      "file_size", "memory_size", "alignment")
    for index, program in enumerate(programs):
        _PROGRAM.pack_into(data, 64 + index * 56,
                           *(program.get(key, 0) for key in program_fields))
    section_fields = ("name", "section_type", "flags", "address", "offset", "size",
                      "link", "info", "alignment", "item_size")
    for index, section in enumerate(sections, 1):
        _SECTION.pack_into(data, 256 + index * 64,
                           *(section.get(key, 0) for key in section_fields))
    for offset, raw in blobs:
        data[offset:offset + len(raw)] = raw
    return bytes(data)


def _header(image, **changes):
    values = dict(zip(_FIELDS, _HEADER.unpack_from(image)))
    values.update(changes)
    return _HEADER.pack(*(values[key] for key in _FIELDS)) + image[64:]


def _refused(image, reason):
    with pytest.raises(elf.StaticPythonELFError) as caught:
        elf.inspect_static_python_elf(image)
    assert caught.value.reason == "static_python_elf_" + reason
    assert str(caught.value) == caught.value.reason


def _dynamic(*entries):
    return b"".join(struct.pack("<qQ", *entry) for entry in entries)


@pytest.mark.parametrize("osabi", [0, 3])
def test_synthetic_format_profile_is_frozen_and_makes_no_runtime_claim(osabi):
    ident = _IDENT[:7] + bytes([osabi]) + _IDENT[8:]
    image = _image(ident=ident)
    observed = elf.inspect_static_python_elf(image)
    assert observed.sha256 == hashlib.sha256(image).hexdigest()
    assert observed.size == len(image) == 512
    assert (observed.elf_class, observed.byte_order, observed.machine, observed.elf_type) == (
        64, "little", "x86_64", "ET_EXEC",
    )
    assert observed.osabi == osabi and observed.entry_point == _BASE + 128
    assert observed.program_header_count == observed.load_segment_count == 1
    assert observed.executable_load_segment_count == 1
    assert observed.section_header_count == observed.dynamic_table_count == 0
    assert observed.dynamic_entry_count == 0
    assert observed.has_pt_interp is observed.has_dt_needed is False
    assert observed.runtime_load_protection is observed.general_code_origin_protection is False
    assert observed.production_admission is False
    with pytest.raises(FrozenInstanceError):
        observed.size = 1


@pytest.mark.parametrize("value", [None, "ELF", bytearray(b"ELF"), memoryview(b"ELF"), 1])
def test_exact_bytes_required(value):
    _refused(value, "type_invalid")


def test_bytes_subclass_is_refused():
    class Subclass(bytes):
        pass

    _refused(Subclass(_image()), "type_invalid")


@pytest.mark.parametrize("size", [0, 1, 16, 63])
def test_header_truncation_is_fixed_size_refusal(size):
    _refused(_image()[:size], "size_invalid")


def test_128_mib_ceiling_is_checked_before_hashing(monkeypatch):
    assert elf.MAX_STATIC_PYTHON_IMAGE_BYTES == 134217728

    def forbidden(_value):
        pytest.fail("over-limit image must not reach hashing")

    monkeypatch.setattr(elf.hashlib, "sha256", forbidden)
    _refused(bytes(134217729), "size_invalid")


def test_exact_128_mib_image_is_within_format_budget():
    image = _image() + bytes(134217728 - 512)
    observed = elf.inspect_static_python_elf(image)
    assert observed.size == 134217728
    assert observed.sha256 == hashlib.sha256(image).hexdigest()


@pytest.mark.parametrize("position,value", [
    (0, 0), (4, 1), (5, 2), (6, 0), (7, 9), (8, 1), (9, 1), (15, 1),
])
def test_ident_magic_class_encoding_version_abi_and_padding_are_checked(position, value):
    ident = bytearray(_IDENT)
    ident[position] = value
    _refused(_image(ident=bytes(ident)), "header_invalid")


@pytest.mark.parametrize("field,value", [
    ("kind", 1), ("kind", 3), ("machine", 183), ("version", 0),
    ("flags", 1), ("ehsize", 63), ("ehsize", 65), ("phsize", 0), ("phsize", 55),
    ("phcount", 0), ("phoff", 0), ("phoff", 63),
])
def test_header_profile_fields_are_checked(field, value):
    _refused(_header(_image(), **{field: value}), "header_invalid")


@pytest.mark.parametrize("changes", [
    {"phcount": 0xFFFF}, {"shcount": 0xFF00}, {"shnames": 0xFFFF},
    {"shoff": 256, "shcount": 0},
])
def test_extended_numbering_is_refused(changes):
    _refused(_header(_image(), **changes), "extended_counts_unsupported")


@pytest.mark.parametrize("changes", [{"phcount": 257}, {"shcount": 4097}])
def test_header_vector_limits_refuse_before_iteration(monkeypatch, changes):
    def forbidden(*_args):
        pytest.fail("over-limit vectors must not be iterated")

    monkeypatch.setattr(elf, "_PROGRAM", SimpleNamespace(size=56, unpack_from=forbidden))
    _refused(_header(_image(), **changes), "limits_exceeded")


@pytest.mark.parametrize("changes", [
    {"phoff": 500}, {"phoff": _UINT64 - 10},
    {"shcount": 2, "shoff": 500, "shsize": 64},
    {"shcount": 2, "shoff": _UINT64 - 10, "shsize": 64},
    {"shcount": 1, "shoff": 64, "shsize": 64},
])
def test_header_table_bounds_overflow_truncation_and_overlap(changes):
    _refused(_header(_image(), **changes), "layout_invalid")


@pytest.mark.parametrize("changes", [
    {"shsize": 1}, {"shnames": 1},
    {"shcount": 2, "shoff": 0, "shsize": 64},
    {"shcount": 2, "shoff": 256, "shsize": 63},
    {"shcount": 2, "shoff": 256, "shsize": 64, "shnames": 2},
])
def test_section_header_metadata_is_consistent(changes):
    _refused(_header(_image(), **changes), "header_invalid")


@pytest.mark.parametrize("changes", [
    {"offset": 500, "file_size": 20}, {"offset": _UINT64 - 3, "file_size": 8},
    {"address": _UINT64 - 3, "memory_size": 8}, {"alignment": 3},
])
def test_segment_bounds_virtual_overflow_and_alignment(changes):
    _refused(_image(programs=[_load(**changes)]), "layout_invalid")


@pytest.mark.parametrize("changes", [
    {"memory_size": 1}, {"permissions": 8}, {"permissions": 4},
    {"segment": 4}, {"address": _BASE + 1},
])
def test_executable_load_and_congruent_mapping_required(changes):
    _refused(_image(programs=[_load(**changes)]), "load_invalid")


@pytest.mark.parametrize("entry", [0, _BASE - 1, _BASE + 512, _BASE + 800, _UINT64])
def test_nonzero_entry_must_be_inside_file_backed_executable_load(entry):
    _refused(_image(entry=entry), "entry_invalid")


def test_entry_inside_zero_filled_tail_is_refused():
    _refused(_image(programs=[_load(memory_size=1024)], entry=_BASE + 700), "entry_invalid")


@pytest.mark.parametrize("malformed", [False, True])
def test_any_interp_segment_is_forbidden(malformed):
    segment = {"segment": 3, "offset": _UINT64 if malformed else 400,
               "file_size": 5 if malformed else 0}
    _refused(_image(programs=[_load(), segment]), "interp_forbidden")


def test_sections_and_string_names_are_observed_without_reading_a_path():
    names = b"\0.text\0.shstrtab\0"
    image = _image(sections=[
        {"section_type": 1, "name": 1, "flags": 6, "address": _BASE + 128,
         "offset": 128, "size": 1, "alignment": 1},
        {"section_type": 3, "name": 7, "offset": 480, "size": len(names)},
    ], blobs=[(128, b"\xc3"), (480, names)], shnames=2)
    assert elf.inspect_static_python_elf(image).section_header_count == 3


@pytest.mark.parametrize("section", [
    {"section_type": 1, "offset": 500, "size": 20},
    {"section_type": 1, "offset": _UINT64 - 3, "size": 8},
    {"section_type": 8, "offset": 128, "size": 8, "flags": 2, "address": _UINT64 - 3},
    {"section_type": 1, "alignment": 3}, {"section_type": 1, "link": 2},
    {"section_type": 1, "size": 3, "item_size": 2}, {"section_type": 1, "name": 1},
])
def test_section_layout_is_checked(section):
    _refused(_image(sections=[section]), "layout_invalid")


def test_null_section_does_not_smuggle_extended_values():
    image = bytearray(_image(sections=[{"section_type": 1}]))
    struct.pack_into("<Q", image, 256 + 32, 123)
    _refused(bytes(image), "header_invalid")


def test_nobits_section_does_not_require_its_size_as_file_bytes():
    image = _image(sections=[{"section_type": 8, "offset": 512, "size": 10000,
                             "flags": 2, "address": _BASE + 512}])
    assert elf.inspect_static_python_elf(image).section_header_count == 2


@pytest.mark.parametrize("mode", ["segment", "section", "both"])
def test_dynamic_null_termination_and_both_views_are_observed(mode):
    raw = _dynamic((30, 0), (0, 0), (0, 0))
    programs = [_load()]
    sections = []
    if mode != "section":
        programs.append({"segment": 2, "offset": 400, "file_size": len(raw),
                         "memory_size": len(raw), "alignment": 8})
    if mode != "segment":
        sections.append({"section_type": 6, "offset": 400, "size": len(raw), "item_size": 16})
    observed = elf.inspect_static_python_elf(_image(
        programs=programs, sections=sections, blobs=[(400, raw)],
    ))
    assert observed.dynamic_table_count == (2 if mode == "both" else 1)
    assert observed.dynamic_entry_count == (6 if mode == "both" else 3)


@pytest.mark.parametrize("mode", ["segment", "section"])
@pytest.mark.parametrize("entries", [((1, 123), (0, 0)), ((0, 0), (1, 123))])
def test_needed_in_segment_or_section_is_always_forbidden(mode, entries):
    raw = _dynamic(*entries)
    programs = [_load(), {"segment": 2, "offset": 400, "file_size": len(raw),
                         "memory_size": len(raw)}] if mode == "segment" else None
    sections = [{"section_type": 6, "offset": 400, "size": len(raw),
                 "item_size": 16}] if mode == "section" else []
    _refused(_image(programs=programs, sections=sections, blobs=[(400, raw)]), "needed_forbidden")


@pytest.mark.parametrize("raw", [_dynamic((30, 0)), _dynamic((0, 1)),
                                  _dynamic((0, 0), (30, 1)), b"\0" * 15, b""])
def test_dynamic_tables_need_exact_records_and_zero_padded_termination(raw):
    image = _image(programs=[_load(), {"segment": 2, "offset": 400,
                                     "file_size": len(raw), "memory_size": len(raw)}],
                   blobs=[(400, raw)])
    _refused(image, "dynamic_invalid")


def test_dynamic_segment_cannot_exceed_memory_span():
    image = _image(programs=[_load(), {"segment": 2, "offset": 400,
                                     "file_size": 16, "memory_size": 0}])
    _refused(image, "dynamic_invalid")


@pytest.mark.parametrize("item_size", [0, 8, 32])
def test_dynamic_section_entry_size_must_be_16(item_size):
    _refused(_image(sections=[{"section_type": 6, "offset": 400, "size": 32,
                              "item_size": item_size}]), "dynamic_invalid")


def test_dynamic_entry_total_is_bounded_across_repeated_views():
    length = 4096 * 16
    programs = [_load(file_size=70000, memory_size=70000),
                {"segment": 2, "offset": 512, "file_size": length, "memory_size": length}]
    image = _image(size=70000, programs=programs)
    assert elf.inspect_static_python_elf(image).dynamic_entry_count == 4096
    section = {"section_type": 6, "offset": 512, "size": 16, "item_size": 16}
    _refused(_image(size=70000, programs=programs, sections=[section]), "limits_exceeded")


def test_maximum_program_vector_is_supported():
    programs = [_load(file_size=16000, memory_size=16000)] + [{"segment": 0}] * 255
    assert elf.inspect_static_python_elf(_image(size=16000, programs=programs)).program_header_count == 256


def test_maximum_section_vector_is_supported():
    sections = [{"section_type": 1}] * 4095
    image = _image(size=263000, sections=sections)
    assert elf.inspect_static_python_elf(image).section_header_count == 4096
