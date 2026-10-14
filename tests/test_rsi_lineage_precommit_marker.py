"""Bound the original staged owner's local archive inspection to its held marker.

Historical descriptor/checkpoint proof is isolated here; the marker, publication
lock, archive guard, offspring parser, seed gate and admission-event gate are real.
No producer, model, evaluator or controller episode is executed by this suite.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_producer_bundle_staging import fixture as _publication_fixture

from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import rsi_publication_lineage as lineage
from lunar_evolution.evolution import (
    CandidateArchive,
    EvolutionConfig,
    EvolutionError,
    OffspringOutcome,
    PopulationStrategy,
)
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionError
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture(autouse=True)
def _no_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("precommit marker tests must not execute processes or use the network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _setup(tmp_path, monkeypatch, *, historical=True):
    workspace, journal, receipt, artifact = _publication_fixture(tmp_path)
    strategy = object.__new__(PopulationStrategy)
    strategy.context = SimpleNamespace(workspace=workspace)
    strategy.config = EvolutionConfig(strategy="population", num_islands=1)
    strategy.archive = CandidateArchive(workspace)
    manifest = staging.stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,), state_after={"strategy": "population"},
    )
    batch = workspace / "evolution/producer-batches" / journal.journal_id
    staged = parse_producer_bundle_publication_journal(batch / "journal.json")
    assert staged.state == "publishing" and manifest.status == "staged"
    state_bytes = json.dumps({"iteration": 0, "status": "running"}).encode()
    prior = {
        "journal_id": "journal-before",
        "snapshots": {"archive-before": {}, "state-before": {}},
        "staged": {"candidate_ids": ["candidate-before"]},
        "terminal": {"terminal_sha256": "a" * 64, "descriptor_sha256": "b" * 64},
        "head_sources": {},
    }
    current = {
        "batches": ([prior] if historical else []) + [{
            "state": "staged", "journal_id": staged.journal_id,
            "staged": {"journal_sha256": staged.digest(), "manifest_sha256": manifest.digest()},
        }],
        "head": ({"journal_id": prior["journal_id"], "terminal_sha256": "a" * 64,
                  "lineage_sha256": "b" * 64} if historical else None),
        "rejections": [],
    }
    state = {"producer_publication_lineage": current}
    owner = object.__new__(lineage.RSIPublicationLineage)
    owner._workspace = workspace
    owner._phase = "staged"
    owner._prepared_ack = True
    owner._association = {}
    owner._plan = SimpleNamespace(journal_id=staged.journal_id)
    owner._strategy = strategy
    native = SimpleNamespace(strategy=strategy)
    owner._gateway = SimpleNamespace(producer_config=SimpleNamespace(inputs=SimpleNamespace(native_context=native)))
    checks = []

    def check_owner(self):
        assert self is owner
        checks.append("owner")
        return state

    def terminal(self, entry, **_kwargs):
        assert self is owner and entry == prior
        return b"", state_bytes

    def snapshot(self, journal_id, _pin, *, name):
        assert self is owner and journal_id == prior["journal_id"]
        return b"" if name == "archive-before" else state_bytes

    # Only checkpoint/retained descriptor proof is stubbed. All local window
    # gates run on real files and the exact CandidateArchive/PopulationStrategy.
    monkeypatch.setattr(lineage.RSIPublicationLineage, "_check_owner", check_owner)
    monkeypatch.setattr(lineage.RSIPublicationLineage, "_verify_terminal_entry", terminal)
    monkeypatch.setattr(lineage.RSIPublicationLineage, "_snapshot_bytes", snapshot)
    wire = {**current, "batches": current["batches"][:-1]}
    return SimpleNamespace(
        workspace=workspace, owner=owner, strategy=strategy, staged=staged, manifest=manifest,
        state=state, wire=wire, state_bytes=state_bytes, checks=checks, native=native,
        marker=workspace / "evolution/producer-publication.json",
    )


def _verify(value, *, precommit=True):
    return value.owner._verify_chain(
        value.wire, b"", value.state_bytes,
        **({"precommit": (value.staged, value.manifest)} if precommit else {}),
    )


@pytest.mark.parametrize("historical", [False, True])
def test_original_staged_owner_uses_local_view_and_keeps_ordinary_archive_guarded(
    tmp_path, monkeypatch, historical,
):
    value = _setup(tmp_path, monkeypatch, historical=historical)
    before = value.strategy.archive.__dict__.copy()
    strategy_before = value.strategy.__dict__.copy()
    marker_before = value.marker.read_bytes()
    inspected = []
    original_outcomes = CandidateArchive.offspring_outcomes

    def outcomes(self):
        if self is not value.strategy.archive:
            assert type(self) is CandidateArchive
            assert self.read_only is True and self._producer_publication_inspection is True
            assert self.workspace == value.workspace
            assert self.offspring_outcomes_path == value.workspace / "evolution/offspring-outcomes.jsonl"
            with pytest.raises(EvolutionError, match="^evolution_archive_read_only$"):
                self._require_writable()
            inspected.append("local")
        return original_outcomes(self)

    monkeypatch.setattr(CandidateArchive, "offspring_outcomes", outcomes)
    with staging._locked(value.workspace):
        assert _verify(value) == ((("candidate-before",),) if historical else ())
        with pytest.raises(EvolutionError, match="^producer_bundle_publication_recovery_required$"):
            value.strategy.archive.offspring_outcomes()
        with pytest.raises(EvolutionError, match="^producer_bundle_publication_recovery_required$"):
            CandidateArchive(value.workspace, read_only=True)
    assert value.checks == ["owner", "owner"]
    assert inspected == (["local"] if historical else [])
    assert value.strategy.archive.__dict__ == before
    assert value.strategy.__dict__ == strategy_before
    assert value.marker.read_bytes() == marker_before


def test_default_chain_reader_still_refuses_staged_marker(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch)
    with staging._locked(value.workspace), pytest.raises(
        EvolutionError, match="^producer_bundle_publication_recovery_required$",
    ):
        _verify(value, precommit=False)
    assert value.checks == []


@pytest.mark.parametrize("field,changed", [
    ("schema_version", "foreign"), ("protocol", "foreign"), ("status", "unknown"),
    ("journal_id", "journal-other"), ("journal_sha256", "e" * 64),
    ("manifest_sha256", "f" * 64),
])
@pytest.mark.parametrize("historical", [False, True])
def test_precommit_requires_complete_original_marker(tmp_path, monkeypatch, field, changed, historical):
    value = _setup(tmp_path, monkeypatch, historical=historical)
    payload = staging.marker_payload(
        journal_id=value.staged.journal_id, journal_sha256=value.staged.digest(),
        manifest_sha256=value.manifest.digest(), status="staged",
    )
    payload[field] = changed
    value.marker.write_bytes(staging._marker_bytes(payload))
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match="^rsi_publication_lineage_precommit_marker_invalid$",
    ):
        _verify(value)


@pytest.mark.parametrize("kind", ["missing", "malformed", "symlink", "hardlink", "mode"])
def test_precommit_refuses_invalid_marker_file(tmp_path, monkeypatch, kind):
    value = _setup(tmp_path, monkeypatch)
    if kind == "missing":
        value.marker.unlink()
    elif kind == "malformed":
        value.marker.write_bytes(b"{}")
    elif kind == "mode":
        value.marker.chmod(0o644)
    else:
        other = value.marker.with_name("other-marker")
        if kind == "symlink":
            value.marker.rename(other)
            value.marker.symlink_to(other.name)
        else:
            os.link(value.marker, other)
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match="^rsi_publication_lineage_precommit_marker_invalid$",
    ):
        _verify(value)


@pytest.mark.parametrize("kind", ["replace", "touch", "change", "remove", "link"])
def test_chain_rechecks_original_marker_pin_after_history_observation(tmp_path, monkeypatch, kind):
    value = _setup(tmp_path, monkeypatch)
    original = lineage.RSIPublicationLineage._verify_terminal_entry

    def mutate(self, *args, **kwargs):
        if kind == "replace":
            replacement = value.marker.with_name("replacement")
            replacement.write_bytes(value.marker.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(value.marker)
        elif kind == "touch":
            info = value.marker.stat()
            os.utime(value.marker, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        elif kind == "change":
            value.marker.write_bytes(b"{}")
        elif kind == "remove":
            value.marker.unlink()
        else:
            os.link(value.marker, value.marker.with_name("other-marker"))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(lineage.RSIPublicationLineage, "_verify_terminal_entry", mutate)
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match="^rsi_publication_lineage_precommit_marker_invalid$",
    ):
        _verify(value)


def test_marker_pin_is_captured_before_first_load(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch, historical=False)
    original = staging._load_marker

    def replace_before_load(path):
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(path)
        return original(path)

    monkeypatch.setattr(staging, "_load_marker", replace_before_load)
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match="^rsi_publication_lineage_precommit_marker_invalid$",
    ):
        _verify(value)


def test_zero_history_rechecks_marker_after_validation(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch, historical=False)
    original = staging._load_marker
    loads = []

    def replace_second_load(path):
        loads.append(path)
        if len(loads) == 2:
            replacement = path.with_name("replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(path)
        return original(path)

    monkeypatch.setattr(staging, "_load_marker", replace_second_load)
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match="^rsi_publication_lineage_precommit_marker_invalid$",
    ):
        _verify(value)
    assert len(loads) == 2


@pytest.mark.parametrize("kind", ["phase", "ack", "journal", "manifest", "prefix", "empty"])
def test_precommit_rejects_drift_before_marker_observation(tmp_path, monkeypatch, kind):
    value = _setup(tmp_path, monkeypatch)
    if kind == "phase":
        value.owner._phase = "terminal"
    elif kind == "ack":
        value.owner._prepared_ack = False
    elif kind == "journal":
        value.staged = replace(value.staged, journal_id="journal-other", journal_sha256=None)
    elif kind == "manifest":
        value.manifest = replace(value.manifest, journal_id="journal-other", manifest_sha256=None)
    elif kind == "prefix":
        value.wire = {**value.wire, "head": None}
    else:
        value.state["producer_publication_lineage"]["batches"] = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("association drift must refuse before marker observation")

    monkeypatch.setattr(lineage, "capture_lineage_snapshot_pin", forbidden)
    code = "state" if kind in {"phase", "ack"} else "association"
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match=f"^rsi_publication_lineage_precommit_{code}_invalid$",
    ):
        _verify(value)


@pytest.mark.parametrize("precommit", [False, [], (), (None,), ({}, {}), (None, None)])
def test_precommit_shape_gate_precedes_local_io(tmp_path, monkeypatch, precommit):
    value = _setup(tmp_path, monkeypatch)

    def forbidden(*_args, **_kwargs):
        pytest.fail("shape gate must refuse before local observation")

    monkeypatch.setattr(lineage, "capture_lineage_snapshot_pin", forbidden)
    monkeypatch.setattr(lineage.RSIPublicationLineage, "_check_owner", forbidden)
    with pytest.raises(RSILearningError, match="^rsi_publication_lineage_precommit_state_invalid$"):
        value.owner._verify_chain(value.wire, b"", value.state_bytes, precommit=precommit)


def test_precommit_requires_original_workspace_lock(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign"
    (foreign / "evolution").mkdir(parents=True)
    for lock_workspace in (None, foreign):
        if lock_workspace is None:
            with pytest.raises(RSILearningError, match="^rsi_publication_lineage_publication_lock_required$"):
                _verify(value)
        else:
            with staging._locked(lock_workspace), pytest.raises(
                RSILearningError, match="^rsi_publication_lineage_publication_lock_required$",
            ):
                _verify(value)


@pytest.mark.parametrize("kind", ["strategy", "archive", "native", "workspace"])
def test_precommit_requires_original_native_strategy(tmp_path, monkeypatch, kind):
    value = _setup(tmp_path, monkeypatch)
    if kind == "strategy":
        value.owner._strategy = SimpleNamespace()
    elif kind == "archive":
        value.strategy.archive = SimpleNamespace()
    elif kind == "native":
        value.native.strategy = object.__new__(PopulationStrategy)
    else:
        value.strategy.context.workspace = tmp_path / "foreign"
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match="^rsi_publication_lineage_precommit_strategy_invalid$",
    ):
        _verify(value)


@pytest.mark.parametrize("kind", ["offspring", "malformed_offspring", "seed", "admission"])
def test_local_inspection_preserves_population_window_gates(tmp_path, monkeypatch, kind):
    value = _setup(tmp_path, monkeypatch)
    evolution = value.workspace / "evolution"
    if kind == "offspring":
        outcome = OffspringOutcome(1, 0, 0, "candidate_failed")
        (evolution / "offspring-outcomes.jsonl").write_text(json.dumps(outcome.to_dict()) + "\n")
    elif kind == "malformed_offspring":
        (evolution / "offspring-outcomes.jsonl").write_bytes(b"{}\n")
    elif kind == "seed":
        (evolution / "seed-commit.json").write_bytes(b"{}")
    else:
        value.state_bytes = json.dumps({
            "iteration": 0, "status": "running", "producer_admissions": {"schema_version": "1", "events": []},
        }).encode()
        monkeypatch.setattr(
            lineage.RSIPublicationLineage, "_snapshot_bytes", lambda *_args, **kwargs:
            b"" if kwargs["name"] == "archive-before" else value.state_bytes,
        )
    expected = EvolutionError if kind == "malformed_offspring" else NativeProducerBundleTransactionError
    code = ("population_outcomes_invalid" if kind == "malformed_offspring" else
            "producer_bundle_transaction_lineage_prefix_invalid" if kind == "admission" else
            "producer_bundle_transaction_population_history_unsupported")
    with staging._locked(value.workspace), pytest.raises(expected, match=f"^{code}$"):
        _verify(value)


def test_local_view_ignores_changed_ordinary_archive_paths(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch)
    value.strategy.archive.offspring_outcomes_path = tmp_path / "foreign-outcomes"
    outcome = OffspringOutcome(1, 0, 0, "candidate_failed")
    (value.workspace / "evolution/offspring-outcomes.jsonl").write_text(json.dumps(outcome.to_dict()) + "\n")
    with staging._locked(value.workspace), pytest.raises(
        NativeProducerBundleTransactionError,
        match="^producer_bundle_transaction_population_history_unsupported$",
    ):
        _verify(value)


@pytest.mark.parametrize("kind", ["marker", "strategy", "native", "workspace"])
@pytest.mark.parametrize("historical", [False, True])
def test_final_owner_observation_cannot_change_precommit_inputs(tmp_path, monkeypatch, kind, historical):
    value = _setup(tmp_path, monkeypatch, historical=historical)
    original = lineage.RSIPublicationLineage._check_owner

    def change_after_owner(self):
        state = original(self)
        if len(value.checks) == 2:
            if kind == "marker":
                value.marker.write_bytes(b"{}")
            elif kind == "strategy":
                value.owner._strategy = object.__new__(PopulationStrategy)
            elif kind == "native":
                value.native.strategy = object.__new__(PopulationStrategy)
            else:
                value.strategy.context.workspace = tmp_path / "foreign"
        return state

    monkeypatch.setattr(lineage.RSIPublicationLineage, "_check_owner", change_after_owner)
    code = "marker" if kind == "marker" else "strategy"
    with staging._locked(value.workspace), pytest.raises(
        RSILearningError, match=f"^rsi_publication_lineage_precommit_{code}_invalid$",
    ):
        _verify(value)
