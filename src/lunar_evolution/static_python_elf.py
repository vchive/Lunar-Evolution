"""Pure, bounded observations of the first static Python ELF format profile.

ELF structure does not establish CPython identity, complete runtime dependencies,
immutable loading, or production admission. No image is opened or executed here.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

MAX_STATIC_PYTHON_IMAGE_BYTES = 128 * 1024 * 1024
_MAX_PROGRAM_HEADERS = 256
_MAX_SECTION_HEADERS = 4096
_MAX_DYNAMIC_ENTRIES = 4096
_MAX_RELOCATABLE_ENTRIES = 262144
# LLVM ELF extensions with embedded linker options or dependent-library names.
# Their bytes can select additional link inputs, unlike ADDRSIG/unwind metadata.
_EXTERNAL_LINK_INPUT_SECTIONS = frozenset({0x6FFF4C01, 0x6FFF4C04})
_LLVM_LTO_SECTION = 0x6FFF4C0C  # Embedded LTO/ThinLTO is outside this native-object profile.
_UINT64_MAX = (1 << 64) - 1
_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
_PROGRAM = struct.Struct("<IIQQQQQQ")
_SECTION = struct.Struct("<IIQQQQIIQQ")
_DYNAMIC = struct.Struct("<qQ")
_SYMBOL = struct.Struct("<IBBHQQ")


class StaticPythonELFError(ValueError):
    """A fixed reason, without image-controlled strings or paths."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class StaticPythonELFProfile:
    sha256: str
    size: int
    osabi: int
    entry_point: int
    program_header_count: int
    section_header_count: int
    load_segment_count: int
    executable_load_segment_count: int
    dynamic_table_count: int
    dynamic_entry_count: int
    elf_class: int = 64
    byte_order: str = "little"
    machine: str = "x86_64"
    elf_type: str = "ET_EXEC"
    has_pt_interp: bool = False
    has_dt_needed: bool = False
    runtime_load_protection: bool = False
    general_code_origin_protection: bool = False
    production_admission: bool = False


def _fail(reason: str) -> NoReturn:
    raise StaticPythonELFError("static_python_elf_" + reason)


def _end(offset: int, size: int) -> int:
    if size > _UINT64_MAX - offset:
        _fail("layout_invalid")
    return offset + size


def _file_end(offset: int, size: int, image_size: int) -> int:
    end = _end(offset, size)
    if end > image_size:
        _fail("layout_invalid")
    return end


def _alignment(value: int) -> bool:
    return value in (0, 1) or value & (value - 1) == 0


def _dynamic_entries(image: bytes, offset: int, size: int) -> None:
    if not size or size % _DYNAMIC.size:
        _fail("dynamic_invalid")
    terminated = False
    for position in range(offset, offset + size, _DYNAMIC.size):
        tag, value = _DYNAMIC.unpack_from(image, position)
        if tag == 1:  # DT_NEEDED, including misleading entries after DT_NULL.
            _fail("needed_forbidden")
        if terminated and (tag or value):
            _fail("dynamic_invalid")
        if tag == 0:
            if value:
                _fail("dynamic_invalid")
            terminated = True
    if not terminated:
        _fail("dynamic_invalid")


def inspect_static_python_elf(image: bytes) -> StaticPythonELFProfile:
    """Observe exact immutable bytes without accepting them as a Python runtime.

    The profile accepts System V or Linux OSABI, which is not a Linux execution
    proof. Extended ELF numbering is unsupported. Dynamic-entry counts include
    padding and repeated segment/section views; a total of 4096 is allowed.
    """
    if type(image) is not bytes:
        _fail("type_invalid")
    size = len(image)
    if not _HEADER.size <= size <= MAX_STATIC_PYTHON_IMAGE_BYTES:
        _fail("size_invalid")
    (ident, kind, machine, version, entry, phoff, shoff, flags, ehsize,
     phsize, phcount, shsize, shcount, shnames) = _HEADER.unpack_from(image)
    if (ident[:4] != b"\x7fELF" or ident[4:7] != b"\x02\x01\x01"
            or ident[7] not in (0, 3) or ident[8:] != b"\0" * 8
            or kind != 2 or machine != 62 or version != 1 or flags
            or ehsize != _HEADER.size):
        _fail("header_invalid")
    if phcount == 0xFFFF or shcount >= 0xFF00 or shnames == 0xFFFF or (shoff and not shcount):
        _fail("extended_counts_unsupported")
    if phcount > _MAX_PROGRAM_HEADERS or shcount > _MAX_SECTION_HEADERS:
        _fail("limits_exceeded")
    if not phcount or phsize != _PROGRAM.size or phoff < _HEADER.size:
        _fail("header_invalid")
    phend = _file_end(phoff, phsize * phcount, size)
    if shcount:
        if shsize != _SECTION.size or shoff < _HEADER.size or shnames >= shcount:
            _fail("header_invalid")
        shend = _file_end(shoff, shsize * shcount, size)
        if phoff < shend and shoff < phend:
            _fail("layout_invalid")
    elif shoff or shnames or shsize not in (0, _SECTION.size):
        _fail("header_invalid")

    loads = executable = 0
    entry_covered = False
    dynamic_tables: list[tuple[int, int]] = []
    total_dynamic_entries = 0

    def add_dynamic(offset: int, length: int) -> None:
        nonlocal total_dynamic_entries
        if not length or length % _DYNAMIC.size:
            _fail("dynamic_invalid")
        total_dynamic_entries += length // _DYNAMIC.size
        if total_dynamic_entries > _MAX_DYNAMIC_ENTRIES:
            _fail("limits_exceeded")
        dynamic_tables.append((offset, length))

    for position in range(phoff, phend, _PROGRAM.size):
        (segment, permissions, offset, address, _physical, file_size,
         memory_size, alignment) = _PROGRAM.unpack_from(image, position)
        if segment == 3:  # PT_INTERP is forbidden even when malformed or empty.
            _fail("interp_forbidden")
        _file_end(offset, file_size, size)
        _end(address, memory_size)
        if not _alignment(alignment):
            _fail("layout_invalid")
        if segment == 1:  # PT_LOAD
            if (file_size > memory_size or permissions & ~7
                    or (alignment > 1 and offset % alignment != address % alignment)):
                _fail("load_invalid")
            loads += 1
            if permissions & 1:
                executable += 1
                entry_covered |= address <= entry < address + file_size
        elif segment == 2:  # PT_DYNAMIC
            if file_size > memory_size:
                _fail("dynamic_invalid")
            add_dynamic(offset, file_size)
    if not executable:
        _fail("load_invalid")
    if not entry or not entry_covered:
        _fail("entry_invalid")

    section_names: tuple[int, int] | None = None
    name_offsets: list[int] = []
    for index in range(shcount):
        section = _SECTION.unpack_from(image, shoff + index * _SECTION.size)
        if index == 0:
            if any(section):
                _fail("header_invalid")
            continue
        (name, section_type, section_flags, address, offset, length,
         link, _info, alignment, item_size) = section
        _file_end(offset, 0 if section_type == 8 else length, size)  # SHT_NOBITS
        if section_flags & 2:  # SHF_ALLOC
            _end(address, length)
        if (not _alignment(alignment) or link >= shcount
                or (item_size and length % item_size)):
            _fail("layout_invalid")
        name_offsets.append(name)
        if index == shnames:
            if section_type != 3 or not length or image[offset] != 0 or image[offset + length - 1]:
                _fail("layout_invalid")
            section_names = offset, length
        if section_type == 6:  # SHT_DYNAMIC; do not rely only on program headers.
            if item_size != _DYNAMIC.size:
                _fail("dynamic_invalid")
            add_dynamic(offset, length)
    if shnames:
        if section_names is None or any(name >= section_names[1] for name in name_offsets):
            _fail("layout_invalid")
    elif any(name_offsets):
        _fail("layout_invalid")
    for offset, length in dynamic_tables:
        _dynamic_entries(image, offset, length)

    return StaticPythonELFProfile(
        sha256=hashlib.sha256(image).hexdigest(), size=size, osabi=ident[7],
        entry_point=entry, program_header_count=phcount, section_header_count=shcount,
        load_segment_count=loads, executable_load_segment_count=executable,
        dynamic_table_count=len(dynamic_tables), dynamic_entry_count=total_dynamic_entries,
    )


@dataclass(frozen=True, slots=True)
class StaticPythonRelocatableELFProfile:
    """Finite ET_REL structure; no link, code-origin or runtime authority."""

    sha256: str
    size: int
    section_header_count: int
    elf_type: str = "ET_REL"
    machine: str = "x86_64"
    production_admission: bool = False


def inspect_static_python_relocatable_elf(
    image: bytes, *, checkpoint: Callable[[], None] | None = None,
) -> StaticPythonRelocatableELFProfile:
    """Check inline ordinary ELF objects without opening or executing anything.

    This structural profile deliberately excludes program headers, dynamic and
    extended-index tables. It does not validate relocation instructions, symbol
    resolution or machine code. The ET_EXEC inspector above is unchanged.
    """
    if checkpoint is not None and not callable(checkpoint):
        _fail("relocatable_control")
    check = checkpoint if checkpoint is not None else lambda: None
    check()
    if type(image) is not bytes:
        _fail("relocatable_type")
    size = len(image)
    if not _HEADER.size <= size <= MAX_STATIC_PYTHON_IMAGE_BYTES:
        _fail("relocatable_size")
    (ident, kind, machine, version, entry, phoff, shoff, flags, ehsize,
     phsize, phcount, shsize, shcount, shnames) = _HEADER.unpack_from(image)
    if (ident[:4] != b"\x7fELF" or ident[4:7] != b"\x02\x01\x01"
            or ident[7] not in (0, 3) or ident[8:] != b"\0" * 8
            or kind != 1 or machine != 62 or version != 1 or flags or entry
            or phoff or phcount or phsize or ehsize != _HEADER.size):
        _fail("relocatable_header")
    if (not 0 < shcount <= _MAX_SECTION_HEADERS or shnames >= shcount
            or shoff < _HEADER.size or shsize != _SECTION.size):
        _fail("relocatable_sections")
    shend = _file_end(shoff, shsize * shcount, size)
    sections = []
    for index in range(shcount):
        check()
        row = _SECTION.unpack_from(image, shoff + index * shsize)
        sections.append(row)
        if index == 0:
            if any(row):
                _fail("relocatable_sections")
            continue
        (name, section_type, _section_flags, address, offset, length,
         link, _info, alignment, item_size) = row
        if section_type in _EXTERNAL_LINK_INPUT_SECTIONS:
            _fail("relocatable_external_input")
        if section_type == _LLVM_LTO_SECTION:
            _fail("relocatable_bitcode")
        if (section_type in (0, 6, 11, 18) or address or link >= shcount
                or not _alignment(alignment) or item_size and length % item_size):
            _fail("relocatable_sections")
        end = _file_end(offset, 0 if section_type == 8 else length, size)
        if section_type != 8 and length and (
                offset < _HEADER.size or offset < shend and shoff < end):
            _fail("relocatable_sections")
        if shnames == 0 and name:
            _fail("relocatable_names")
    if shnames:
        names = sections[shnames]
        start, length = names[4:6]
        if (names[1] != 3 or not length or image[start] or image[start + length - 1]
                or any(row[0] >= length for row in sections)):
            _fail("relocatable_names")
    entries = 0
    for index, row in enumerate(sections[1:], 1):
        check()
        kind, length, link, info, item_size = row[1], row[5], row[6], row[7], row[9]
        if kind in (2, 4, 9, 17):
            entries += length // max(1, item_size)
            if entries > _MAX_RELOCATABLE_ENTRIES:
                _fail("relocatable_limits")
        if kind == 2:  # SHT_SYMTAB
            if (item_size != 24 or length < 24 or not link or sections[link][1] != 3
                    or info > length // 24):
                _fail("relocatable_symbols")
            strings = sections[link]
            start, string_size = strings[4:6]
            if not string_size or image[start] or image[start + string_size - 1]:
                _fail("relocatable_symbols")
            if any(image[row[4]:row[4] + 24]):
                _fail("relocatable_symbols")
            for offset in range(row[4], row[4] + length, 24):
                check()
                name, _binding, _visibility, section, value, symbol_size = _SYMBOL.unpack_from(image, offset)
                if (name >= string_size or section >= shcount and section not in (0xFFF1, 0xFFF2)
                        or 0 < section < shcount and (
                            value > sections[section][5] or symbol_size > sections[section][5] - value)):
                    _fail("relocatable_symbols")
        elif kind in (4, 9):  # SHT_RELA / SHT_REL
            if (item_size != (24 if kind == 4 else 16) or not link
                    or sections[link][1] != 2 or sections[link][9] != 24
                    or not 0 < info < shcount):
                _fail("relocatable_relocations")
            for offset in range(row[4], row[4] + length, item_size):
                check()
                target, relation = struct.unpack_from("<QQ", image, offset)
                if (relation >> 32 >= sections[link][5] // 24 or target > sections[info][5]
                        or relation & 0xFFFFFFFF and target == sections[info][5]):
                    _fail("relocatable_relocations")
        elif kind == 17:  # SHT_GROUP, linked to its signature's symbol table.
            if (item_size != 4 or not length or not link or sections[link][1] != 2
                    or sections[link][9] != 24 or not 0 < info < sections[link][5] // 24):
                _fail("relocatable_group")
            for offset in range(row[4], row[4] + length, 4):
                check()
                member = struct.unpack_from("<I", image, offset)[0]
                if (offset == row[4] and member not in (0, 1)
                        or offset != row[4] and (not 0 < member < shcount or member == index)):
                    _fail("relocatable_group")
    digest = hashlib.sha256()
    for offset in range(0, size, 65536):
        check()
        digest.update(memoryview(image)[offset:offset + 65536])
    check()
    return StaticPythonRelocatableELFProfile(digest.hexdigest(), size, shcount)
