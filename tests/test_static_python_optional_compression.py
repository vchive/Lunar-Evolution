"""Finite JSON/source solver capabilities, with genuine ImportError fallbacks."""

from __future__ import annotations

import json

import pytest
from test_static_python_fixed_runtime_closure import (
    closure_inputs as closure_inputs,  # noqa: PLC0414 - pytest fixture re-export
)
from test_static_python_fixed_runtime_closure import refresh_cpython_pin

from tools.static_python_rsi_fixture import runtime_closure as closure

MODULES = ("bz2", "gzip", "lzma", "zlib")


@pytest.mark.parametrize("module", MODULES)
def test_guarded_compression_is_unavailable_without_fake_frozen_or_native_module(
    closure_inputs, module,
):
    args = closure_inputs
    args["cpython_sources"]["Lib/json/decoder.py"] = (
        f"try:\n    import {module}\nexcept ImportError:\n    available = False\n"
    ).encode()
    # A staged upstream file is input data, not permission to enable this module.
    path = "Lib/" + module + ".py"
    args["cpython_sources"][path] = b"import required_compression_native_provider\n"
    refresh_cpython_pin(args)
    original = dict(args["cpython_sources"])
    result = closure.prepare_fixed_runtime_closure(**args)
    facts = json.loads(result.wire_bytes)
    assert args["cpython_sources"] == original
    assert module in facts["guarded_absent_imports"]
    assert module not in {row["name"] for row in facts["frozen"]}
    assert module not in {row["module"] for row in facts["native_units"]}
    assert module not in closure._NATIVE
    assert facts["runtime_execution_performed"] is False
    assert facts["production_admission"] is False


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("statement", ["import {module}\n", "from {module} import feature\n"])
def test_required_compression_import_is_never_hidden(closure_inputs, module, statement):
    args = closure_inputs
    args["cpython_sources"]["Lib/json/decoder.py"] = statement.format(module=module).encode()
    args["cpython_sources"]["Lib/" + module + ".py"] = b"pass\n"
    refresh_cpython_pin(args)
    with pytest.raises(closure.RuntimeClosureError, match="unguarded_absent_import"):
        closure.prepare_fixed_runtime_closure(**args)


@pytest.mark.parametrize("module", ["_bz2", "_lzma", "required_compression_native_provider"])
def test_required_native_import_still_refuses(closure_inputs, module):
    args = closure_inputs
    args["cpython_sources"]["Lib/json/decoder.py"] = f"import {module}\n".encode()
    refresh_cpython_pin(args)
    with pytest.raises(closure.RuntimeClosureError, match="unresolved_import"):
        closure.prepare_fixed_runtime_closure(**args)
