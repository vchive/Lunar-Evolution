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
    values.extend("".join(chars) for size in range(5) for chars in itertools.product(alphabet, repeat=size))
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
