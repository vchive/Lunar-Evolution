"""Final graph drift refuses before invoking changed Python or native aliases."""

from __future__ import annotations

import hashlib
import math
import os
import sqlite3
import time

import pytest

from lunar_evolution import rsi_brs_rejection_ready_ack as ack_graph
from lunar_evolution import rsi_brs_rejection_ready_final as final
from lunar_evolution import rsi_brs_rejection_ready_ledger as ledger
from lunar_evolution import rsi_brs_rejection_ready_state as transport_state
from lunar_evolution import rsi_learning as learning
from lunar_evolution.rsi_learning import RSILearningError

_CAPSULE = (None,) * 8 + (((10.0,), (20.0,)),)


def _foreign(*_args, **_kwargs):
    raise AssertionError("changed dependency ran")


@pytest.mark.parametrize("module,name", [
    (os, "open"), (os, "read"), (os, "close"), (os, "stat"), (os, "fstat"), (os, "listdir"),
    (hashlib, "sha256"), (math, "isfinite"), (time, "time"), (time, "monotonic"),
    (sqlite3, "connect"), (ledger, "assert_rejection_ready_rows"), (ledger, "_readonly_uri"),
])
def test_native_or_reader_alias_replacement_never_runs(module, name, monkeypatch):
    monkeypatch.setattr(module, name, _foreign)
    with pytest.raises(RSILearningError, match="final_graph_drift"):
        final.rejection_ready_deadlines(_CAPSULE)


@pytest.mark.parametrize("function", final._FINAL_FUNCTIONS,
                         ids=lambda function: function.__name__)
def test_every_declared_local_code_is_held_before_final_invocation(function, monkeypatch):
    # Keeping the free-variable count permits a safe in-place code mutation
    # without constructing a new function or invoking the changed code.
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign-final"))
    with pytest.raises(RSILearningError, match="final_(graph|guard)_drift"):
        final.rejection_ready_deadlines(_CAPSULE)


@pytest.mark.parametrize("field,value", [("__defaults__", ("foreign",)),
                                        ("__kwdefaults__", {"foreign": True}),
                                        ("__annotations__", {"foreign": "annotation"}),
                                        ("__name__", "foreign-name")])
def test_internal_function_metadata_is_held(field, value, monkeypatch):
    function = next(function for function in final._FINAL_FUNCTIONS if function.__name__ == "observe_file")
    monkeypatch.setattr(function, field, value)
    with pytest.raises(RSILearningError, match="final_graph_drift"):
        final.rejection_ready_deadlines(_CAPSULE)


def test_application_exception_initializer_is_never_a_refusal_callback(monkeypatch):
    calls = []

    def changed(*_args, **_kwargs):
        calls.append("error initializer")
        raise AssertionError

    monkeypatch.setattr(learning.RSILearningError, "__init__", changed)
    with pytest.raises(RSILearningError, match="final_graph_drift") as raised:
        final.rejection_ready_deadlines(_CAPSULE)
    assert not calls
    assert raised.value.code.endswith("final_graph_drift")


def test_internal_guard_error_helper_cannot_execute_after_code_replacement(monkeypatch):
    function = final._FINAL_FUNCTIONS[-1]
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign-refusal"))
    monkeypatch.setattr(os, "read", _foreign)
    with pytest.raises(RSILearningError, match="final_guard_drift"):
        final.rejection_ready_deadlines(_CAPSULE)


def test_ledger_table_and_schema_inventory_cannot_be_replaced(monkeypatch):
    monkeypatch.setattr(ledger, "_TABLES", tuple(reversed(ledger._TABLES)))
    with pytest.raises(RSILearningError, match="final_graph_drift"):
        final.rejection_ready_deadlines(_CAPSULE)


@pytest.mark.parametrize("function", (*transport_state._STATE_FUNCTIONS,
                                      ack_graph.assert_rejection_ready_ack,
                                      ack_graph.assert_rejection_ready_ack_graph),
                         ids=lambda function: function.__name__)
def test_final_pending_and_ack_tail_code_is_independently_held(function, monkeypatch):
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign-tail"))
    with pytest.raises(RSILearningError, match="final_graph_drift"):
        final.rejection_ready_deadlines(_CAPSULE)
