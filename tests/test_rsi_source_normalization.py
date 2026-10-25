"""The zero-margin shortcut preserves the installed dedent backend contract."""

from __future__ import annotations

import random
import re
import textwrap
from pathlib import Path

import pytest

from lunar_evolution import rsi_identity as identity


@pytest.mark.parametrize("source", [
    "", "\n", " \t\n", "def f():\n    return 1\n", "@decorator\ndef f():\n    pass\n",
    "class C:\n\tpass\n \t\n", "    def f():\n        pass\n",
    "\n    def f():\n        pass\n", "\tdef f():\n\t\tpass\n",
    "# comment\n    block\n \t\n", "\r\n    value\r\n \t\r\n",
    "\ufeffdef f():\n    pass\n", "\u2003value\n\tline\n", "x\n \t",
])
def test_normalization_matches_standard_library_for_line_boundaries(source):
    assert identity._dedent_source(source) == textwrap.dedent(source)


def test_dedent_matches_standard_library_on_generated_lines_and_repository_sources():
    rng = random.Random(410825)
    lines = ["", " ", "\t", " \t", "code", "  code", "\tcode", "\u2003", "字", "\r"]
    for _ in range(1000):
        source = "\n".join(rng.choices(lines, k=rng.randrange(1, 20)))
        assert identity._dedent_source(source) == textwrap.dedent(source)
    root = Path(identity.__file__).parent
    for path in sorted(root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert identity._dedent_source(source) == textwrap.dedent(source), path.name


def test_changed_dedent_function_is_observed_even_for_zero_margin(monkeypatch):
    calls = []

    def replacement(source):
        calls.append(source)
        return "backend replacement"

    monkeypatch.setattr(textwrap, "dedent", replacement)
    assert identity.component_identity(None, code="zero margin").code == "backend replacement"
    assert calls == ["zero margin"]


def test_changed_backend_code_is_observed(monkeypatch):
    def replacement(_source):
        return "code replacement"

    monkeypatch.setattr(textwrap.dedent, "__code__", replacement.__code__)
    assert identity.component_identity(None, code="zero margin").code == "code replacement"


@pytest.mark.parametrize("name", ["_whitespace_only_re", "_leading_whitespace_re"])
def test_changed_backend_regex_is_observed(monkeypatch, name):
    monkeypatch.setattr(textwrap, name, re.compile("(?m)^x"))
    source = "x\n \t\n    body\n"
    assert identity._dedent_source(source) == textwrap.dedent(source)


def test_source_subclass_uses_backend(monkeypatch):
    class Source(str):
        pass

    source = Source("zero margin")
    calls = []
    original = textwrap.dedent

    def observe(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(textwrap, "dedent", observe)
    assert identity._dedent_source(source) == "zero margin"
    assert calls == [source] and calls[0] is source


def test_normalization_does_not_reuse_live_code_hook_or_byte_limit(monkeypatch):
    class Component:
        def __init__(self):
            self.source = "class First:\n    pass\n \t\n"
            self.calls = 0

        def rsi_fingerprint_code(self):
            self.calls += 1
            return self.source

        def rsi_fingerprint_config(self):
            return {}

    component = Component()
    first = identity.component_identity(component)
    component.source = "class Second:\n    pass\n"
    second = identity.component_identity(component)
    assert first.code == textwrap.dedent("class First:\n    pass\n \t\n").strip()
    assert second.code == "class Second:\n    pass" and first.digest() != second.digest()
    monkeypatch.setattr(identity, "MAX_CODE_BYTES", 1)
    with pytest.raises(identity.RSIIdentityError, match="rsi_identity_too_large"):
        identity.component_identity(component)
    assert component.calls == 3
