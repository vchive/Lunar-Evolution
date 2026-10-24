"""A pinned AST-import scan of the fixed prepared nine-module source set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lunar_evolution.static_python_import_audit import audit_static_python_imports
from tools.static_python_fixture.source_patches import (
    SOURCE_PATHS,
    prepare_static_python_sources,
)

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _ROOT / "tests/fixtures/static_python_source"

# The four upstream Python inputs are retained as inert .source fixture bytes;
# the five Lunar-prepared postimages come from the fixed patch policy. The
# custom main is retained verbatim from the historical expanded candidate.
# The current codec-negative candidate has a separate source graph and audit.
_FROZEN_SOURCE_PINS = {
    "_frozen_importlib": (57082, "b84488f731914f6da30607e10f6f8d4c5c2ff7f4b0e913060aa66999c04f6252"),
    "_frozen_importlib_external": (64722, "2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab"),
    "abc": (6468, "a6684b1a49cfbc9c64caeeac7e55ef8f35052b8e8ca93a091941817cdc510b1c"),
    "codecs": (36978, "2f278497548b8313580b247a1097a0a304e5087a355ebb11a92ec685fa9e63ff"),
    "encodings.__init__": (1101, "47a11d930321492bca552eed29dad061ed6739bf84c919485453315d911b1c60"),
    "encodings.aliases": (802, "43aadac378861c1bbdaaf04be8e1bb7d878529a7641ec123b5df4eccdd4c6106"),
    "encodings.utf_8": (1005, "ba0cac060269583523ca9506473a755203037c57d466a11aa89a30a5f6756f3d"),
    "io": (3582, "7cec3cb8ac004058dd0a5af246e6d950fb59c7ddd0058fda48bcb3fcb98d8822"),
}
_PREPARED_C_PIN = (146559, "58a5fac8fac5916511f890f3fdd095d817e6f32ab709ebf0ed0becf9328226b1")
_CODECS_PIN = (36978, "2f278497548b8313580b247a1097a0a304e5087a355ebb11a92ec685fa9e63ff")
_IMPORTS = [
    ("_frozen_importlib", "_frozen_importlib_external", "import"),
    ("_frozen_importlib_external", "_imp", "import"),
    ("_frozen_importlib_external", "_io", "import"),
    ("_frozen_importlib_external", "_warnings", "import"),
    ("_frozen_importlib_external", "importlib.metadata", "from-import"),
    ("_frozen_importlib_external", "importlib.readers", "from-import"),
    ("_frozen_importlib_external", "marshal", "import"),
    ("_frozen_importlib_external", "nt", "import"),
    ("_frozen_importlib_external", "posix", "import"),
    ("_frozen_importlib_external", "sys", "import"),
    ("_frozen_importlib_external", "tokenize", "import"),
    ("_frozen_importlib_external", "winreg", "import"),
    ("_lunar_static_main", "_imp", "import"),
    ("_lunar_static_main", "_lunar_fixture_pipe", "import"),
    ("_lunar_static_main", "sys", "import"),
    ("abc", "_abc", "from-import"),
    ("codecs", "_codecs", "from-import"),
    ("codecs", "builtins", "import"),
    ("codecs", "encodings", "import"),
    ("codecs", "sys", "import"),
    ("encodings", "codecs", "import"),
    ("encodings", "encodings", "from-import"),
    ("encodings", "encodings.aliases", "from-import"),
    ("encodings", "encodings.utf_8", "from-import"),
    ("encodings.utf_8", "codecs", "import"),
    ("io", "_io", "from-import"),
    ("io", "_io", "import"),
    ("io", "abc", "import"),
]
_UNSUPPORTED = [
    ("_frozen_importlib", 1176, 8, "dynamic-code-execution"),
    ("_frozen_importlib_external", 1323, 15, "dynamic-code-execution"),
    ("_lunar_static_main", 68, 47, "dynamic-import"),
    ("codecs", 16, 4, "star-import"),
]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_codecs_star_import_edge_matches_candidate_builtin_profile() -> None:
    """Cross-check one pinned edge without claiming star-import closure."""
    codecs_source = (_FIXTURE_ROOT / "Lib/codecs.py.source").read_bytes()
    assert (len(codecs_source), _sha256(codecs_source)) == _CODECS_PIN

    result = audit_static_python_imports(
        {"codecs": codecs_source},
        expected_source_sha256={"codecs": _CODECS_PIN[1]},
    )
    wire = result.to_dict()
    assert {
        (edge["source"], edge["target"], edge["kind"])
        for edge in wire["imports"]
    } >= {("codecs", "_codecs", "from-import")}
    assert wire["unsupported_import_sites"] == [{
        "source": "codecs",
        "line": 16,
        "column": 4,
        "reason": "star-import",
    }]

    example = json.loads(
        (_ROOT / "specs/189-static-python-fixture/wire-v1-example.json").read_bytes()
    )
    assert example["kind"] == "synthetic-parser-and-ELF-format-only-never-executed"
    builtins = example["descriptor"]["builtin_modules"]
    codecs_builtin = next(item for item in builtins if item["name"] == "_codecs")
    assert codecs_builtin["init_symbol"] == "PyInit__codecs"
    frozen = example["descriptor"]["frozen_modules"]
    assert any(item["name"] == "codecs" for item in frozen)
    assert all(item["name"] != "codecs" for item in builtins)
    assert all(item["name"] != "_codecs" for item in frozen)
    assert all(value is False for value in wire["claims"].values())


def test_observes_exact_prepared_nine_module_frozen_source_set() -> None:
    raw = {
        path: (_FIXTURE_ROOT / (path + ".source")).read_bytes()
        for path in SOURCE_PATHS
    }
    prepared, _manifest = prepare_static_python_sources(raw)
    assert (len(prepared["Python/import.c"]), _sha256(prepared["Python/import.c"])) == _PREPARED_C_PIN

    main_source = (
        _FIXTURE_ROOT / "Lunar/frozen_main-before-codec-negative.py.source"
    ).read_bytes()
    historical_main_pin = (
        6794, "6e6a9e661f50dc1baf5b1e6e1f2a717468f1351d7fc6d534ecae125717e0695d",
    )
    assert (len(main_source), _sha256(main_source)) == historical_main_pin

    sources = {
        "_frozen_importlib": (_FIXTURE_ROOT / "Lib/importlib/_bootstrap.py.source").read_bytes(),
        "_frozen_importlib_external": prepared["Lib/importlib/_bootstrap_external.py"],
        "abc": prepared["Lib/abc.py"],
        "codecs": (_FIXTURE_ROOT / "Lib/codecs.py.source").read_bytes(),
        "encodings.__init__": prepared["Lib/encodings/__init__.py"],
        "encodings.aliases": prepared["Lib/encodings/aliases.py"],
        "encodings.utf_8": (_FIXTURE_ROOT / "Lib/encodings/utf_8.py.source").read_bytes(),
        "io": (_FIXTURE_ROOT / "Lib/io.py.source").read_bytes(),
        "_lunar_static_main": main_source,
    }
    expected_pins = dict(_FROZEN_SOURCE_PINS)
    expected_pins["_lunar_static_main"] = historical_main_pin
    for name, expected in _FROZEN_SOURCE_PINS.items():
        assert (len(sources[name]), _sha256(sources[name])) == expected
    assert set(sources) == set(expected_pins)

    result = audit_static_python_imports(
        sources,
        expected_source_sha256={name: pin[1] for name, pin in expected_pins.items()},
    )
    wire = result.to_dict()
    assert result.source_count == 9
    assert result.import_count == 28
    assert result.unresolved_count == 0
    assert result.unsupported_count == 4
    assert _sha256(result.wire_bytes) == (
        "d7802d7ac60202b720c30bacfb124fe8ee155298ac88ddd8facdbbc7f07dc9f5"
    )
    assert [
        (edge["source"], edge["target"], edge["kind"])
        for edge in wire["imports"]
    ] == _IMPORTS
    assert wire["unresolved_imports"] == []
    assert [
        (site["source"], site["line"], site["column"], site["reason"])
        for site in wire["unsupported_import_sites"]
    ] == _UNSUPPORTED
    assert wire["evidence_scope"] == "source-ast-import-observations-only"
    assert all(value is False for value in wire["claims"].values())

    # This is an exact-name membership projection against synthetic descriptor
    # inventories. It says nothing about branch execution or runtime reachability.
    descriptor = json.loads(
        (_ROOT / "specs/189-static-python-fixture/wire-v1-example.json").read_bytes()
    )["descriptor"]
    declared_names = {
        item["name"]
        for key in ("frozen_modules", "builtin_modules")
        for item in descriptor[key]
    }
    observed_targets = {edge["target"] for edge in wire["imports"]}
    assert len(observed_targets) == 21
    assert observed_targets - declared_names == {
        "importlib.metadata", "importlib.readers", "nt", "tokenize", "winreg",
    }
    assert observed_targets & declared_names == {
        "_abc", "_codecs", "_frozen_importlib_external", "_imp", "_io",
        "_lunar_fixture_pipe", "_warnings", "abc", "builtins", "codecs",
        "encodings", "encodings.aliases", "encodings.utf_8", "marshal",
        "posix", "sys",
    }
