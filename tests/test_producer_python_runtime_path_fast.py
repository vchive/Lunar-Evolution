"""Differential contract tests for producer runtime's lexical path validator."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from lunar_evolution import producer_python_runtime as runtime


def _outcome(validator, value, *, absolute=False, dot=False):
    try:
        return ("ok", validator(value, absolute=absolute, dot=dot))
    except runtime.PythonRuntimeError as error:
        return ("error", error.code)


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("dot", [False, True])
def test_lexical_path_matches_pathlib_reference_on_control_matrix(absolute, dot):
    values = [
        "a", "a/b", ".", "./a", "..", "../a", "a/..", "a//b", "/a", "//a",
        "///a", "/", "//", "///", "a/", "a/.", "a/./b", "a//", "//a/b", "a\\b",
        "", "a\x00b", "a\r b", "a\nb", "说明/文件.py", "a/说明", "./", "/.", "/.//",
        "/..", "/a/..", "a/../b", "a/../../b", "...", ".../a", "//./a", "//a/./b",
        "////a", "//a//b", "a//..", "a/../../", "\ud800", "a/\ud800",
    ]
    alphabet = "/.ab_"
    values.extend("".join(chars) for size in range(7) for chars in itertools.product(alphabet, repeat=size))
    for value in values:
        assert _outcome(runtime._path_reference, value, absolute=absolute, dot=dot) == _outcome(
            runtime._path, value, absolute=absolute, dot=dot), (value, absolute, dot)


@pytest.mark.parametrize("value", [None, True, 1, b"a", Path("a")])
def test_lexical_path_preserves_exact_str_type_gate(value):
    assert _outcome(runtime._path_reference, value) == _outcome(runtime._path, value)


def test_lexical_path_preserves_utf8_and_component_bounds():
    within_bytes = "字" * 1365 + "a"
    over_bytes = "字" * 1366
    within_parts = "/".join(["a"] * 128)
    over_parts = "/".join(["a"] * 129)
    for value in (within_bytes, over_bytes, within_parts, over_parts):
        assert _outcome(runtime._path_reference, value) == _outcome(runtime._path, value)
    assert _outcome(runtime._path, within_bytes) == ("ok", within_bytes)
    assert _outcome(runtime._path, within_parts) == ("ok", within_parts)
    assert _outcome(runtime._path, over_bytes)[0] == "error"
    assert _outcome(runtime._path, over_parts)[0] == "error"


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("parts", [127, 128, 129])
def test_component_count_includes_absolute_anchor(absolute, parts):
    value = ("/" if absolute else "") + "/".join(["字"] * parts)
    expected = ("ok", value) if parts + int(absolute) <= 128 else (
        "error", "python_runtime_path_invalid",
    )
    assert _outcome(runtime._path_reference, value, absolute=absolute) == expected
    assert _outcome(runtime._path, value, absolute=absolute) == expected


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("byte_count", [4095, 4096, 4097])
@pytest.mark.parametrize("character", ["a", "é", "字", "😀"])
def test_utf8_byte_bound_precedes_component_scans(absolute, byte_count, character):
    prefix = "/" if absolute else ""
    body_bytes = byte_count - len(prefix)
    width = len(character.encode("utf-8"))
    value = prefix + character * (body_bytes // width) + "a" * (body_bytes % width)
    expected = ("ok", value) if byte_count <= 4096 else (
        "error", "python_runtime_path_invalid",
    )
    assert len(value.encode("utf-8")) == byte_count
    assert _outcome(runtime._path_reference, value, absolute=absolute) == expected
    assert _outcome(runtime._path, value, absolute=absolute) == expected


@pytest.mark.parametrize("value", [
    "说明/文件.py", "e\u0301/é", "😀/资源", "a\tb", "a\u2028b", "a\u0085b",
    ".隐藏/..允许", ".../…", "a/．/b", "a/．．/b", "a/..é", "a/.é", "/目录/文件.py",
    "a\ud800b", "a/\udfffb", "/a/\ud800", "a\x00b", "a\rb", "a\nb", "a\\b",
])
def test_unicode_and_complete_dot_components_preserve_reference(value):
    for absolute, dot in itertools.product((False, True), repeat=2):
        assert _outcome(runtime._path_reference, value, absolute=absolute, dot=dot) == _outcome(
            runtime._path, value, absolute=absolute, dot=dot,
        )


@pytest.mark.parametrize("maximum", [0, 1, 128])
@pytest.mark.parametrize("dot", [False, True])
def test_dot_and_root_retain_zero_component_and_one_anchor_bounds(monkeypatch, maximum, dot):
    monkeypatch.setattr(runtime, "_MAX_PATH_PARTS", maximum)
    for value, absolute in ((".", False), ("/", True)):
        assert _outcome(runtime._path_reference, value, absolute=absolute, dot=dot) == _outcome(
            runtime._path, value, absolute=absolute, dot=dot,
        )


def test_foreign_string_and_object_type_gates_do_not_call_str_or_encode():
    calls = []

    class Foreign:
        def __str__(self):
            calls.append("str")
            raise AssertionError("foreign object converted to text")

        def encode(self, *_args, **_kwargs):
            calls.append("encode")
            raise AssertionError("foreign object encoded")

    class ForeignString(str):
        def __str__(self):
            calls.append("str subclass")
            raise AssertionError("string subclass converted to text")

        def encode(self, *_args, **_kwargs):
            calls.append("encode subclass")
            raise AssertionError("string subclass encoded")

    for value in (Foreign(), ForeignString("a/b")):
        for validator in (runtime._path_reference, runtime._path):
            assert _outcome(validator, value) == ("error", "python_runtime_path_invalid")
    assert calls == []


@pytest.mark.parametrize("absolute", [None, 0, 1, "", "relative"])
def test_absolute_flag_keeps_exact_boolean_identity_gate(absolute):
    for value in ("a", "/a"):
        assert _outcome(runtime._path_reference, value, absolute=absolute) == (
            "error", "python_runtime_path_invalid",
        )
        assert _outcome(runtime._path, value, absolute=absolute) == (
            "error", "python_runtime_path_invalid",
        )


def test_path_validation_has_no_path_construction_or_filesystem_effect(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("lexical path validation accessed filesystem or constructed Path")

    with monkeypatch.context() as guards:
        guards.setattr(runtime, "Path", forbidden)
        guards.setattr(runtime.os, "open", forbidden)
        guards.setattr(runtime.os, "stat", forbidden)
        guards.setattr(runtime.os, "lstat", forbidden)
        assert _outcome(runtime._path, "a/b.py") == ("ok", "a/b.py")
        assert _outcome(runtime._path, "/a/b.py", absolute=True) == ("ok", "/a/b.py")
        assert _outcome(runtime._path, "a/../b.py") == ("error", "python_runtime_path_invalid")
