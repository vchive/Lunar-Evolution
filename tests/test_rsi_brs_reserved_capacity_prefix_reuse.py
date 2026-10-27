"""Capacity parses fresh detached prefix facts within each pure operation."""

from __future__ import annotations

from copy import deepcopy

import pytest
from test_rsi_brs_reserved_rejection_consumers import _expected, _fixture

from lunar_evolution import rsi_brs_rejection_capacity as capacity
from lunar_evolution import rsi_brs_reserved_rejection as rejection
from lunar_evolution.rsi_learning import RSILearningError


def _case(monkeypatch, stage, outcomes=("published", "all_rejected")):
    _before, c1, c2, options, rejected, published = _fixture(monkeypatch, outcomes)
    state = {"producer_publication_lineage": c1}
    wire = c1 if stage == "c1" else c2
    return state, wire, options, rejected, published


def _materials(state, wire, options, rejected, published, stage):
    return capacity._retained_reserved_brs_materials(
        state, wire, rejected, published, **options,
        provenance_reserve=capacity.MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES if stage == "c1" else 0,
        with_provenance=stage == "c2",
    )


@pytest.mark.parametrize("stage", ["c1", "c2"])
@pytest.mark.parametrize("outcomes", [(), ("published", "all_rejected"),
    ("all_rejected", "published") * 3 + ("published",)])
def test_materials_parses_once_on_each_call_without_mutating_inputs(monkeypatch, stage, outcomes):
    state, wire, options, rejected, published = _case(monkeypatch, stage, outcomes)
    saved = deepcopy((state, wire, rejected, published))
    original = rejection._prefix
    observations = []

    def observe(prefix):
        observations.append(prefix)
        return original(prefix)

    monkeypatch.setattr(rejection, "_prefix", observe)
    for _ in range(2):
        observations.clear()
        actual, _materials_by_path, _identities = _materials(state, wire, options, rejected, published, stage)
        assert actual == _expected(wire, rejected, published)
        assert len(observations) == 1
        assert observations[0] is options["prefix"]
    assert (state, wire, rejected, published) == saved


@pytest.mark.parametrize("stage,parses", [("c1", 1), ("c2", 2)])
def test_outer_capacity_wrapper_keeps_its_independent_transition_observation(monkeypatch, stage, parses):
    state, wire, options, rejected, published = _case(monkeypatch, stage)
    original = rejection._prefix
    observations = []

    def observe(prefix):
        observations.append(prefix)
        return original(prefix)

    monkeypatch.setattr(rejection, "_prefix", observe)
    count = (capacity._retained_reserved_brs_c1_evidence_bytes if stage == "c1"
             else capacity._retained_reserved_brs_c2_evidence_bytes)
    assert count(state, wire, rejected, published, **options) == _expected(wire, rejected, published)
    assert len(observations) == parses
    assert all(prefix is options["prefix"] for prefix in observations)


@pytest.mark.parametrize("stage", ["c1", "c2"])
@pytest.mark.parametrize("fault,code", [
    ("ready_and_prefix", "rsi_producer_ready_capsule_state_invalid"),
    ("prefix_and_scope", "rsi_brs_reserved_rejection_noncanonical_bytes"),
    ("scope_and_entry", "rsi_brs_reserved_rejection_head_drift"),
    ("entry_and_tables", "rsi_brs_reserved_rejection_entry_invalid"),
])
def test_capacity_preserves_ready_prefix_scope_and_entry_refusal_order(monkeypatch, stage, fault, code):
    state, wire, options, rejected, published = _case(monkeypatch, stage)
    prefix = options["prefix"]
    if fault in {"ready_and_prefix", "prefix_and_scope"}:
        object.__setattr__(prefix, "canonical_bytes", prefix.canonical_bytes + b"\n")
    if fault == "ready_and_prefix":
        state["producer_episode_staging"] = []
    elif fault == "prefix_and_scope":
        wire["head"] = True
    elif fault == "scope_and_entry":
        wire["head"] = True
        wire["batches"][-1]["prepared_journal"] = {}
    else:
        wire["batches"][-1]["prepared_journal"] = {}
        rejected.clear()
    with pytest.raises(RSILearningError) as caught:
        _materials(state, wire, options, rejected, published, stage)
    assert str(caught.value) == code


@pytest.mark.parametrize("stage", ["c1", "c2"])
@pytest.mark.parametrize("field", ["domain_bytes", "canonical_bytes", "batch_bytes"])
def test_later_capacity_invocation_revalidates_each_original_prefix_member(monkeypatch, stage, field):
    state, wire, options, rejected, published = _case(monkeypatch, stage)
    _materials(state, wire, options, rejected, published, stage)
    prefix = options["prefix"]
    original = getattr(prefix, field)
    changed = ((original[0] + b"\n", *original[1:]) if field == "batch_bytes" else original + b"\n")
    object.__setattr__(prefix, field, changed)
    with pytest.raises(RSILearningError) as caught:
        _materials(state, wire, options, rejected, published, stage)
    assert str(caught.value) == "rsi_brs_reserved_rejection_noncanonical_bytes"
    object.__setattr__(prefix, field, original)
    assert _materials(state, wire, options, rejected, published, stage)[0] == _expected(wire, rejected, published)


@pytest.mark.parametrize("stage", ["c1", "c2"])
def test_later_capacity_invocation_revalidates_mutated_active_entry(monkeypatch, stage):
    state, wire, options, rejected, published = _case(monkeypatch, stage)
    _materials(state, wire, options, rejected, published, stage)
    entry = wire["batches"][-1]
    original = entry["request_sha256"]
    entry["request_sha256"] = "0" * 64
    with pytest.raises(RSILearningError) as caught:
        _materials(state, wire, options, rejected, published, stage)
    assert str(caught.value) == "rsi_brs_reserved_rejection_entry_invalid"
    entry["request_sha256"] = original
    assert _materials(state, wire, options, rejected, published, stage)[0] == _expected(wire, rejected, published)


@pytest.mark.parametrize("stage", ["c1", "c2"])
def test_parsed_facts_share_only_one_stack_and_detach_from_later_calls(monkeypatch, stage):
    state, wire, options, rejected, published = _case(monkeypatch, stage)
    saved = deepcopy((state, wire, rejected, published))
    scope, entry = rejection._transition_scope_from_prefix, rejection._validated_entry_from_prefix
    seen = []

    def observe_scope(previous, current, parsed_prefix, original_lineage_bytes):
        seen.append(("scope", parsed_prefix))
        return scope(previous, current, parsed_prefix, original_lineage_bytes)

    def observe_entry(active, parsed_prefix, plan, with_provenance):
        seen.append(("entry", parsed_prefix))
        return entry(active, parsed_prefix, plan, with_provenance)

    monkeypatch.setattr(rejection, "_transition_scope_from_prefix", observe_scope)
    monkeypatch.setattr(rejection, "_validated_entry_from_prefix", observe_entry)
    _materials(state, wire, options, rejected, published, stage)
    first = seen[0][1]
    assert [name for name, _facts in seen] == ["scope", "entry"]
    assert seen[1][1] is first
    first[0]["episode_ids"][0] = "changed-detached-result"
    seen.clear()
    assert _materials(state, wire, options, rejected, published, stage)[0] == _expected(wire, rejected, published)
    assert [name for name, _facts in seen] == ["scope", "entry"]
    assert seen[0][1] is seen[1][1] and seen[0][1] is not first
    assert (state, wire, rejected, published) == saved


@pytest.mark.parametrize("stage", ["c1", "c2"])
def test_foreign_prefix_member_refuses_before_foreign_methods_or_io(monkeypatch, stage):
    state, wire, options, rejected, published = _case(monkeypatch, stage)

    class ForeignBytes(bytes):
        def __len__(self):  # noqa: PLE0303 - any invocation must fail the test
            pytest.fail("capacity invoked foreign length")

        def __eq__(self, other):
            pytest.fail("capacity invoked foreign equality")

    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: pytest.fail("pure capacity read disk"))
    prefix = options["prefix"]
    object.__setattr__(prefix, "canonical_bytes", ForeignBytes(prefix.canonical_bytes))
    with pytest.raises(RSILearningError) as caught:
        _materials(state, wire, options, rejected, published, stage)
    assert str(caught.value) == "rsi_brs_reserved_rejection_prefix_invalid"
