"""Bounded inline GNU ar objects, without extraction or input-custody claims."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from lunar_evolution.static_python_elf import inspect_static_python_relocatable_elf

MAX_LINK_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_LINK_ARCHIVE_MEMBERS = 4096
_MAX_NAMES = 4 * 1024 * 1024
_MAX_SYMBOLS = 262144
_MAX_NAME_BYTES = 480


class StaticPythonLinkObjectError(ValueError):
    """Finite refusal; archive-controlled names never enter exception text."""


def _fail(reason: str) -> None:
    raise StaticPythonLinkObjectError("static_python_link_object_" + reason)


def _name(raw: bytes) -> None:
    if (not 0 < len(raw) <= _MAX_NAME_BYTES or raw.startswith(b"/")
            or raw in (b"__.SYMDEF", b"__.SYMDEF_64", b"__.SYMDEF SORTED", b"__.SYMDEF_64 SORTED")
            or any(part in (b"", b".", b"..") for part in raw.split(b"/"))
            or any(value < 33 or value > 126 or value in (58, 92) for value in raw)):
        _fail("member_name")


def _number(raw: bytes, *, octal: bool = False, blank: bool = False) -> int:
    value = raw.strip(b" ")
    if not value:
        if blank:
            return 0
        _fail("header")
    if any(char not in (b"01234567" if octal else b"0123456789") for char in value):
        _fail("header")
    return int(value, 8 if octal else 10)


@dataclass(frozen=True, slots=True)
class StaticPythonLinkArchiveProfile:
    """Observed bytes and inline member count, never linker/runtime acceptance."""

    sha256: str
    size: int
    member_count: int
    symbol_count: int
    production_admission: bool = False


def inspect_static_python_link_archive(
    image: bytes, *, checkpoint: Callable[[], None] | None = None,
) -> StaticPythonLinkArchiveProfile:
    """Accept only bounded ordinary GNU archives of inline x86_64 ET_REL files.

    GNU long names may contain relative directories: these remain inline names.
    Thin/BSD archives and scripts are unsupported. Symbol offsets must name
    actual object headers; no name is opened, extracted or interpreted as a path.
    """
    if checkpoint is not None and not callable(checkpoint):
        _fail("control")
    check = checkpoint if checkpoint is not None else lambda: None
    check()
    if type(image) is not bytes or not 8 < len(image) <= MAX_LINK_ARCHIVE_BYTES:
        _fail("size")
    if image[:8] != b"!<arch>\n":
        _fail("magic")
    position, members, symbol_count = 8, 0, 0
    names: dict[int, bytes] = {}
    object_offsets: set[int] = set()
    symbol_offsets: list[int] = []
    seen_symbols = seen_names = False
    while position < len(image):
        check()
        if len(image) - position < 60:
            _fail("header")
        head = image[position:position + 60]
        if head[58:] != b"`\n":
            _fail("header")
        for field in (head[16:28], head[28:34], head[34:40]):
            _number(field, blank=True)
        _number(head[40:48], octal=True, blank=True)
        length = _number(head[48:58])
        start, end = position + 60, position + 60 + length
        if end > len(image) or length % 2 and image[end:end + 1] != b"\n":
            _fail("extent")
        token = head[:16].rstrip(b" ")
        if token in (b"/", b"/SYM64/"):
            if seen_symbols or seen_names or members or length > _MAX_NAMES:
                _fail("symbols")
            seen_symbols = True
            width = 8 if token == b"/SYM64/" else 4
            if length < width:
                _fail("symbols")
            symbol_count = int.from_bytes(image[start:start + width], "big")
            cursor = start + width * (symbol_count + 1)
            if symbol_count > _MAX_SYMBOLS or cursor > end:
                _fail("symbols")
            for offset in range(start + width, cursor, width):
                check()
                symbol_offsets.append(int.from_bytes(image[offset:offset + width], "big"))
            for _ in range(symbol_count):
                check()
                terminator = image.find(b"\0", cursor, min(end, cursor + 4097))
                if terminator <= cursor:
                    _fail("symbols")
                cursor = terminator + 1
            if image[cursor:end] not in (b"", b"\0"):
                _fail("symbols")
        elif token == b"//":
            if seen_names or members or length > _MAX_NAMES:
                _fail("names")
            seen_names = True
            cursor = start
            while cursor < end:
                check()
                if end - cursor == 1 and image[cursor] == 10:  # GNU table padding.
                    break
                terminator = image.find(b"/\n", cursor, min(end, cursor + _MAX_NAME_BYTES + 2))
                if terminator < 0 or len(names) >= MAX_LINK_ARCHIVE_MEMBERS:
                    _fail("names")
                name = image[cursor:terminator]
                _name(name)
                names[cursor - start] = name
                cursor = terminator + 2
        else:
            if token.startswith(b"/"):
                index = token[1:]
                if not index or any(char not in b"0123456789" for char in index):
                    _fail("member_name")
                name = names.get(int(index))
                if name is None:
                    _fail("names")
            elif token.endswith(b"/") and b"/" not in token[:-1]:
                name = token[:-1]
            else:
                _fail("member_name")
            _name(name)
            members += 1
            if members > MAX_LINK_ARCHIVE_MEMBERS:
                _fail("members")
            inspect_static_python_relocatable_elf(image[start:end], checkpoint=check)
            object_offsets.add(position)
        position = end + length % 2
    if not members or not set(symbol_offsets).issubset(object_offsets):
        _fail("members")
    digest = hashlib.sha256()
    for offset in range(0, len(image), 65536):
        check()
        digest.update(memoryview(image)[offset:offset + 65536])
    check()
    return StaticPythonLinkArchiveProfile(digest.hexdigest(), len(image), members, symbol_count)
