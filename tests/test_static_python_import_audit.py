"""Synthetic pinned-byte tests for the AST import observer only."""

from __future__ import annotations

import builtins
import hashlib
import json
import subprocess
import urllib.request

import pytest

from lunar_evolution import (
    IMPORT_AUDIT_SCHEMA,
    StaticPythonImportAudit,
    StaticPythonImportAuditError,
    audit_static_python_imports,
)
from lunar_evolution import (
    static_python_import_audit as audit,
)


def _pins(sources: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(source).hexdigest() for name, source in sources.items()}


def _run(sources: dict[str, bytes]):
    return audit.audit_static_python_imports(sources, expected_source_sha256=_pins(sources))


def _edge_set(result) -> set[tuple[str, str, str]]:
    return {
        (item["source"], item["target"], item["kind"])
        for item in result.to_dict()["imports"]
    }


def _refusal(reason: str, sources: dict[str, bytes], pins: dict[str, str] | None = None):
    with pytest.raises(audit.StaticPythonImportAuditError) as caught:
        audit.audit_static_python_imports(
            sources,
            expected_source_sha256=_pins(sources) if pins is None else pins,
        )
    assert caught.value.reason == f"static_python_import_audit_{reason}"
    assert str(caught.value) == caught.value.reason


def test_observes_absolute_imports_without_requiring_target_sources() -> None:
    result = _run({"root": b"import os.path, missing_module\nfrom codecs import lookup\n"})
    assert _edge_set(result) == {
        ("root", "os.path", "import"),
        ("root", "missing_module", "import"),
        ("root", "codecs", "from-import"),
    }
    assert result.to_dict()["unresolved_imports"] == []
    assert result.to_dict()["unsupported_import_sites"] == []


def test_from_import_adds_only_a_supplied_possible_submodule_edge() -> None:
    result = _run({
        "pkg.__init__": b"from . import child, attribute\n",
        "pkg.child": b"VALUE = 1\n",
    })
    assert _edge_set(result) == {
        ("pkg", "pkg", "from-import"),
        ("pkg", "pkg.child", "from-import"),
    }


def test_relative_import_requires_explicit_package_initializer() -> None:
    result = _run({"pkg.module": b"from . import child\n"})
    wire = result.to_dict()
    assert wire["imports"] == []
    assert wire["unresolved_imports"] == [{
        "source": "pkg.module",
        "line": 1,
        "column": 0,
        "reason": "relative-import-unresolved",
    }]


def test_relative_import_resolves_with_explicit_package_chain() -> None:
    result = _run({
        "pkg.__init__": b"",
        "pkg.sub.__init__": b"from ..shared import item\n",
        "pkg.shared": b"",
    })
    assert _edge_set(result) == {("pkg.sub", "pkg.shared", "from-import")}
    assert result.to_dict()["unresolved_imports"] == []


def test_relative_import_allows_namespace_parent_without_parent_initializer() -> None:
    result = _run({
        "pkg.sub.__init__": (
            b"from ..shared import item\n"
            b"import importlib\n"
            b"importlib.import_module(name='..sibling', package='pkg.sub')\n"
        ),
    })
    assert _edge_set(result) == {
        ("pkg.sub", "pkg.shared", "from-import"),
        ("pkg.sub", "importlib", "import"),
        ("pkg.sub", "pkg.sibling", "literal-import"),
    }
    assert result.to_dict()["unresolved_imports"] == []


def test_relative_import_beyond_top_level_is_retained_as_unresolved() -> None:
    result = _run({"pkg.__init__": b"from ..outside import item\n"})
    assert result.to_dict()["imports"] == []
    assert result.to_dict()["unresolved_imports"][0]["reason"] == "relative-import-unresolved"


def test_literal_import_calls_produce_literal_edges_and_dynamic_calls_are_retained() -> None:
    result = _run({
        "pkg.__init__": b"",
        "scanner": (
            b"import importlib as il\n"
            b"from importlib import import_module as load\n"
            b"def run(name):\n"
            b"    __import__('literal_mod')\n"
            b"    il.import_module('.child', 'pkg')\n"
            b"    load(name)\n"
            b"    __import__(name)\n"
            b"    helper.import_module(name)\n"
            b"    eval(name)\n"
            b"    exec(name, {})\n"
            b"    compile(name, '<src>', 'exec')\n"
        ),
    })
    assert _edge_set(result) == {
        ("scanner", "importlib", "import"),
        ("scanner", "importlib", "from-import"),
        ("scanner", "literal_mod", "literal-import"),
        ("scanner", "pkg.child", "literal-import"),
    }
    reasons = [item["reason"] for item in result.to_dict()["unsupported_import_sites"]]
    assert reasons.count("dynamic-import") == 3
    assert reasons.count("dynamic-code-execution") == 3
    assert result.to_dict()["unresolved_imports"] == []


def test_unpinned_literal_relative_import_package_is_unresolved() -> None:
    result = _run({"scanner": b"importlib.import_module('.child', 'pkg')\n"})
    assert result.to_dict()["imports"] == []
    assert result.to_dict()["unresolved_imports"][0]["reason"] == "relative-import-unresolved"


def test_literal_import_calls_accept_keyword_names_and_packages() -> None:
    result = _run({
        "pkg.__init__": b"",
        "scanner": (
            b"import importlib\n"
            b"importlib.import_module(name='.child', package='pkg')\n"
            b"__import__(name='literal_mod')\n"
        ),
    })
    assert _edge_set(result) == {
        ("scanner", "importlib", "import"),
        ("scanner", "pkg.child", "literal-import"),
        ("scanner", "literal_mod", "literal-import"),
    }
    assert result.to_dict()["unsupported_import_sites"] == []


def test_nonliteral_relative_import_package_is_unsupported() -> None:
    result = _run({
        "pkg.__init__": b"",
        "scanner": b"importlib.import_module('.child', package=choose_package())\n",
    })
    assert result.to_dict()["imports"] == []
    assert result.to_dict()["unresolved_imports"] == []
    assert result.to_dict()["unsupported_import_sites"] == [{
        "source": "scanner",
        "line": 1,
        "column": 0,
        "reason": "dynamic-import",
    }]


def test_importlib_submodule_alias_does_not_fake_import_module_observation() -> None:
    result = _run({
        "scanner": (
            b"import importlib.util as iu\n"
            b"iu.import_module('should_not_be_imported')\n"
        ),
        "shadowed": (
            b"import importlib.util as importlib\n"
            b"importlib.import_module('should_not_be_imported')\n"
        ),
    })
    assert _edge_set(result) == {
        ("scanner", "importlib.util", "import"),
        ("shadowed", "importlib.util", "import"),
    }
    assert result.to_dict()["unsupported_import_sites"] == [{
        "source": "scanner",
        "line": 2,
        "column": 0,
        "reason": "dynamic-import",
    }, {
        "source": "shadowed",
        "line": 2,
        "column": 0,
        "reason": "dynamic-import",
    }]


def test_unbound_import_module_function_does_not_fake_literal_import() -> None:
    result = _run({
        "scanner": (
            b"def import_module(name):\n"
            b"    return name\n"
            b"import_module('not_a_module_import')\n"
        ),
    })
    assert result.to_dict()["imports"] == []
    assert result.to_dict()["unsupported_import_sites"] == [{
        "source": "scanner",
        "line": 3,
        "column": 0,
        "reason": "dynamic-import",
    }]


def test_star_import_keeps_base_edge_and_marks_unknown_members_unsupported() -> None:
    result = _run({"scanner": b"from package_name import *\n"})
    assert _edge_set(result) == {("scanner", "package_name", "from-import")}
    assert result.to_dict()["unsupported_import_sites"][0]["reason"] == "star-import"


def test_builtin_import_aliases_and_builtin_module_aliases_are_observed() -> None:
    result = _run({
        "scanner": (
            b"from builtins import __import__ as imp\n"
            b"import builtins as bi\n"
            b"imp('first')\n"
            b"bi.__import__('second')\n"
        ),
    })
    assert _edge_set(result) == {
        ("scanner", "builtins", "import"),
        ("scanner", "builtins", "from-import"),
        ("scanner", "first", "literal-import"),
        ("scanner", "second", "literal-import"),
    }


def test_repeated_imports_are_deterministically_deduplicated() -> None:
    result = _run({"scanner": b"import one\nimport one\nfrom one import thing\n"})
    assert result.to_dict()["imports"] == [
        {"source": "scanner", "target": "one", "kind": "from-import"},
        {"source": "scanner", "target": "one", "kind": "import"},
    ]
    assert result.wire_bytes == _run({"scanner": b"import one\nimport one\nfrom one import thing\n"}).wire_bytes


def test_result_is_canonical_detached_and_has_only_false_claims() -> None:
    result = _run({"scanner": b"import target\n"})
    value = result.to_dict()
    assert result.wire_bytes == json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
    value["sources"].clear()
    value["imports"].clear()
    reread = result.to_dict()
    assert len(reread["sources"]) == 1
    assert len(reread["imports"]) == 1
    assert all(claim is False for claim in reread["claims"].values())
    assert "import target" not in result.wire_bytes.decode("ascii")


def test_public_package_api_exports_the_scanner_contract() -> None:
    assert IMPORT_AUDIT_SCHEMA == audit.IMPORT_AUDIT_SCHEMA
    assert audit_static_python_imports is audit.audit_static_python_imports
    assert StaticPythonImportAudit is audit.StaticPythonImportAudit
    assert StaticPythonImportAuditError is audit.StaticPythonImportAuditError


def test_source_is_parsed_but_never_executed_or_opened(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = _run({"scanner": b"raise RuntimeError('must not run')\n"})
    assert result.to_dict()["imports"] == []


@pytest.mark.parametrize(
    ("sources", "pins", "reason"),
    [
        ({}, {}, "bounds"),
        ({"bad-name": b""}, {"bad-name": hashlib.sha256(b"").hexdigest()}, "module"),
        ({"valid": bytearray(b"x")}, {"valid": hashlib.sha256(b"x").hexdigest()}, "shape"),
        ({"valid": b"x"}, {}, "shape"),
        ({"valid": b"x"}, {"other": hashlib.sha256(b"x").hexdigest()}, "shape"),
        ({"valid": b"x"}, {"valid": "0" * 64}, "digest"),
        ({"valid": b"x"}, {"valid": "f" * 64}, "digest"),
        ({"valid": b"x"}, {"valid": "A" * 64}, "digest"),
        ({"valid": b"x"}, {"valid": hashlib.sha256(b"y").hexdigest()}, "digest"),
    ],
)
def test_fixed_input_refusals(sources, pins, reason: str) -> None:
    _refusal(reason, sources, pins)


def test_exact_dictionary_and_exact_pin_value_types_are_required() -> None:
    class SourceMap(dict):
        pass

    class Pin(str):
        pass

    with pytest.raises(audit.StaticPythonImportAuditError, match="^static_python_import_audit_shape$"):
        audit.audit_static_python_imports(
            SourceMap(scanner=b""), expected_source_sha256={"scanner": hashlib.sha256(b"").hexdigest()}
        )
    pins = {"scanner": Pin(hashlib.sha256(b"").hexdigest())}
    _refusal("digest", {"scanner": b""}, pins)


def test_encoding_and_syntax_fail_with_fixed_refusal_codes() -> None:
    _refusal("encoding", {"scanner": b"# coding: latin-1\nname = '\xff'\n"})
    _refusal("encoding", {"scanner": b"name = '\xff'\n"})
    _refusal("syntax", {"scanner": b"from (\n"})


def test_conflicting_package_initializer_and_module_names_refuse() -> None:
    _refusal("module", {"pkg": b"", "pkg.__init__": b""})


def test_per_source_and_source_count_bounds_refuse_before_parsing() -> None:
    _refusal("budget", {"large": b"#" + b"x" * audit.MAX_SOURCE_BYTES})
    too_many = {f"m{index}": b"" for index in range(audit.MAX_SOURCE_MODULES + 1)}
    _refusal("bounds", too_many)


def test_aggregate_source_bound_refuses_before_hashing() -> None:
    sources = {f"m{index}": b"#" + b"x" * 250_000 for index in range(17)}
    _refusal("budget", sources)


def test_ast_depth_node_and_total_node_bounds_refuse() -> None:
    _refusal("budget", {"nested": b"x = " + b"[" * 140 + b"0" + b"]" * 140})
    _refusal("budget", {"many": b"x=1\n" * 7_000})
    sources = {f"m{index}": b"x=1\n" * 7_000 for index in range(6)}
    _refusal("budget", sources)


def test_import_call_site_bound_refuses_instead_of_returning_partial_edges() -> None:
    source = b"\n".join(b"import m" + str(index).encode("ascii") for index in range(
        audit.MAX_IMPORT_SITES + 1
    ))
    _refusal("budget", {"scanner": source})


def test_output_wire_bound_refuses_instead_of_returning_partial_edges() -> None:
    targets = ["m" + str(index) + "x" * (125 - len(str(index))) for index in range(2_048)]
    source_a = ("import " + ",".join(targets[:1_024]) + "\n").encode("ascii")
    source_b = ("import " + ",".join(targets[1_024:]) + "\n").encode("ascii")
    assert len(source_a) < audit.MAX_SOURCE_BYTES
    assert len(source_b) < audit.MAX_SOURCE_BYTES
    _refusal("budget", {"a": source_a, "b": source_b})
