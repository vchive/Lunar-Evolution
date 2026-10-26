"""Operation-local prefix reuse keeps fresh pure validation and refusal order."""

from __future__ import annotations

from copy import deepcopy

import pytest
from test_rsi_brs_reserved_rejection import _fixture

from lunar_evolution import rsi_brs_reserved_rejection as rejection
from lunar_evolution.rsi_learning import RSILearningError


def _operation(stage):
    before, c1, c2, kwargs = _fixture(("all_rejected", "published"))
    if stage == "c1":
        return rejection.validate_reserved_brs_c1_transition, before, c1, kwargs
    return rejection.validate_reserved_brs_c2_transition, c1, c2, kwargs


@pytest.mark.parametrize("stage", ["c1", "c2"])
@pytest.mark.parametrize("fault,code", [
    ("prefix_and_wire", "noncanonical_bytes"),
    ("scope_and_entry", "head_drift"),
    ("journal", "entry_invalid"),
])
def test_prefix_scope_and_entry_refusal_order_matches_original(stage, fault, code):
    validate, previous, current, kwargs = _operation(stage)
    if fault == "prefix_and_wire":
        prefix = kwargs["prefix"]
        object.__setattr__(prefix, "canonical_bytes", prefix.canonical_bytes + b"\n")
        current["head"] = True
    elif fault == "scope_and_entry":
        current["head"] = True
        current["batches"][-1]["prepared_journal"] = None
    else:
        # The parser raises ValueError for this shape. It must still receive the
        # public entry wrapper even when invoked inside a C1/C2 operation.
        current["batches"][-1]["prepared_journal"] = {}
    with pytest.raises(RSILearningError) as caught:
        validate(previous, current, **kwargs)
    assert str(caught.value) == "rsi_brs_reserved_rejection_" + code


def test_c2_current_entry_failure_precedes_previous_entry_failure():
    validate, previous, current, kwargs = _operation("c2")
    previous["batches"][-1]["native_plan_sha256"] = "0" * 64
    current["batches"][-1]["prepared_journal"] = None
    with pytest.raises(RSILearningError) as caught:
        validate(previous, current, **kwargs)
    assert str(caught.value) == "rsi_brs_reserved_rejection_entry_invalid"


@pytest.mark.parametrize("stage", ["c1", "c2"])
@pytest.mark.parametrize("field", ["domain_bytes", "canonical_bytes", "batch_bytes"])
def test_each_invocation_revalidates_mutated_prefix_bytes(stage, field):
    validate, previous, current, kwargs = _operation(stage)
    saved = deepcopy((previous, current))
    validate(previous, current, **kwargs)
    prefix = kwargs["prefix"]
    original = getattr(prefix, field)
    changed = ((original[0] + b"\n", *original[1:]) if field == "batch_bytes" else original + b"\n")
    object.__setattr__(prefix, field, changed)
    with pytest.raises(RSILearningError) as caught:
        validate(previous, current, **kwargs)
    assert str(caught.value) == "rsi_brs_reserved_rejection_noncanonical_bytes"
    object.__setattr__(prefix, field, original)
    validate(previous, current, **kwargs)
    assert (previous, current) == saved


@pytest.mark.parametrize("stage", ["c1", "c2"])
def test_each_invocation_revalidates_mutated_current_entry(stage):
    validate, previous, current, kwargs = _operation(stage)
    validate(previous, current, **kwargs)
    entry = current["batches"][-1]
    original = entry["request_sha256"]
    entry["request_sha256"] = "0" * 64
    with pytest.raises(RSILearningError) as caught:
        validate(previous, current, **kwargs)
    assert str(caught.value) == "rsi_brs_reserved_rejection_entry_invalid"
    entry["request_sha256"] = original
    validate(previous, current, **kwargs)


@pytest.mark.parametrize("stage", ["c1", "c2"])
def test_changed_prefix_subclass_refuses_before_foreign_hooks(stage):
    validate, previous, current, kwargs = _operation(stage)
    validate(previous, current, **kwargs)

    class ForeignBytes(bytes):
        def __len__(self):
            raise AssertionError("foreign length executed")

        def __eq__(self, other):
            pytest.fail("foreign equality executed")

    prefix = kwargs["prefix"]
    object.__setattr__(prefix, "canonical_bytes", ForeignBytes(prefix.canonical_bytes))
    with pytest.raises(RSILearningError) as caught:
        validate(previous, current, **kwargs)
    assert str(caught.value) == "rsi_brs_reserved_rejection_prefix_invalid"


@pytest.mark.parametrize("stage", ["c1", "c2"])
@pytest.mark.parametrize("outcomes", [(), ("all_rejected", "published"), ("published", "all_rejected") * 3 + ("published",)])
def test_one_prefix_parse_per_top_level_transition(monkeypatch, stage, outcomes):
    before, c1, c2, kwargs = _fixture(outcomes)
    validate = (rejection.validate_reserved_brs_c1_transition if stage == "c1"
                else rejection.validate_reserved_brs_c2_transition)
    previous, current = (before, c1) if stage == "c1" else (c1, c2)
    original = rejection._prefix
    observations = []

    def count(prefix):
        observations.append(prefix)
        return original(prefix)

    monkeypatch.setattr(rejection, "_prefix", count)
    for _ in range(2):
        observations.clear()
        validate(previous, current, **kwargs)
        assert len(observations) == 1
        assert observations[0] is kwargs["prefix"]


def test_standalone_entry_and_scope_parse_independently(monkeypatch):
    _before, c1, c2, kwargs = _fixture(("all_rejected", "published"))
    original = rejection._prefix
    observations = []

    def count(prefix):
        observations.append(prefix)
        return original(prefix)

    monkeypatch.setattr(rejection, "_prefix", count)
    for _ in range(2):
        rejection.validate_reserved_brs_rejected_entry(c2["batches"][-1], prefix=kwargs["prefix"],
            native_plan_sha256=kwargs["native_plan_sha256"], with_provenance=True)
        rejection._transition_scope(c1, c2, kwargs["prefix"], kwargs["original_lineage_bytes"])
    assert len(observations) == 4
    assert all(prefix is kwargs["prefix"] for prefix in observations)
