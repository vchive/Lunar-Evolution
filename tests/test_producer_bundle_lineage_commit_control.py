"""Charge final held lineage observations to the original native control."""

from __future__ import annotations

import json
import subprocess

import pytest
from test_bundle_population import build_context
from test_producer_bundle_staging import fixture as _publication_fixture
from test_producer_bundle_transaction_control import FakeClock

from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_control import bind_native_producer_bundle_control
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage


@pytest.fixture(autouse=True)
def _no_processes(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("commit-control tests must not launch processes")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def _staged(tmp_path):
    workspace, journal, receipt, artifact = _publication_fixture(tmp_path)
    staging.stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,),
        state_after={"strategy": "population"},
    )
    batch = workspace / "evolution/producer-batches" / journal.journal_id
    staged = parse_producer_bundle_publication_journal(batch / "journal.json")
    return workspace, batch, staged


def _exposure(workspace):
    evolution = workspace / "evolution"
    return (
        (evolution / "archive.jsonl").read_bytes(),
        (evolution / "state.json").read_bytes(),
        (evolution / "producer-publication.json").read_bytes(),
        tuple(sorted(path.name for path in (evolution / "candidates").iterdir())),
    )


@pytest.mark.parametrize("boundary", ["lineage", "final_handoff"])
@pytest.mark.parametrize("reason", ["native_deadline", "parent_deadline", "cancellation"])
def test_final_lineage_observation_cannot_outlive_original_native_control(
    tmp_path, monkeypatch, boundary, reason,
):
    workspace, batch, staged = _staged(tmp_path)
    before = _exposure(workspace)
    context = build_context(tmp_path / "control")
    strategy = PopulationStrategy(context)
    clock = FakeClock()
    observations = []
    control = SolveExecutionControl(30, clock=clock, observe_stage=observations.append)
    parent_observations = []
    if reason == "parent_deadline":
        def parent_remaining(stage):
            parent_observations.append(stage)
            return 3.0
        context.bundle_pipeline.set_remaining_timeout(parent_remaining)
    owner = object.__new__(RSIPublicationLineage)
    retained_counts = []

    def stop():
        if reason == "cancellation":
            control.cancel()
        elif reason == "parent_deadline":
            clock.value += 4.0
            assert clock.value < control.deadline
        else:
            clock.value = control.deadline

    def observe_lineage(self, journal, manifest):
        # This bounded seam represents time spent reading the original held
        # lineage. The original owner authority is tested independently.
        assert self is owner and journal == staged
        assert manifest.journal_sha256 == staged.digest()
        retained_counts.append((len(observations), len(parent_observations)))
        if boundary == "lineage":
            stop()

    original_handoff = staging._verify_python_handoff

    def observe_handoff(*args, **kwargs):
        original_handoff(*args, **kwargs)
        if boundary == "final_handoff" and retained_counts:
            stop()

    monkeypatch.setattr(RSIPublicationLineage, "verify_precommit", observe_lineage)
    monkeypatch.setattr(staging, "_verify_python_handoff", observe_handoff)
    expected = SolveExecutionCancelled if reason == "cancellation" else SolveExecutionBudgetExceeded
    with bind_native_producer_bundle_control(strategy, control) as checkpoint, pytest.raises(expected):
        staging.commit_producer_bundle_publication(
            workspace, staged, checkpoint=checkpoint, lineage_owner=owner,
        )
    assert retained_counts == [(len(observations), len(parent_observations))]
    assert _exposure(workspace) == before
    assert json.loads(before[2])["status"] == "staged"
    assert (batch / "stage/candidates/candidate-1/main.py").is_file()
    assert not (batch / "terminal.json").exists()
    assert not (batch / "journal.published.json").exists()


@pytest.mark.parametrize("control", ["missing_checkpoint", "missing_revalidator", "invalid_revalidator"])
def test_lineage_commit_requires_original_post_observation_control(tmp_path, control):
    workspace, _batch, staged = _staged(tmp_path)
    before = _exposure(workspace)
    owner = object.__new__(RSIPublicationLineage)
    checkpoint = None
    if control != "missing_checkpoint":
        def checkpoint(_stage):
            pytest.fail("invalid control must refuse before callback")
        if control == "invalid_revalidator":
            checkpoint.revalidate_after_observation = False
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="control_invalid"):
        staging.commit_producer_bundle_publication(
            workspace, staged, checkpoint=checkpoint, lineage_owner=owner,
        )
    assert _exposure(workspace) == before


def test_final_native_gate_does_not_replay_observer_after_evidence_or_adopt_its_shadow(
    tmp_path, monkeypatch,
):
    workspace, batch, staged = _staged(tmp_path)
    before = _exposure(workspace)
    strategy = PopulationStrategy(build_context(tmp_path / "control"))
    clock = FakeClock()
    owner = object.__new__(RSIPublicationLineage)
    observed = []
    retained_count = []
    control = SolveExecutionControl(30, clock=clock)

    def observe_lineage(self, _journal, _manifest):
        assert self is owner
        retained_count.append(len(observed))
        clock.value = control.deadline

    monkeypatch.setattr(RSIPublicationLineage, "verify_precommit", observe_lineage)
    with bind_native_producer_bundle_control(strategy, control) as checkpoint:
        def shadow_after_checkpoint(stage):
            observed.append(stage)
            if stage == "producer_commit_verified":
                checkpoint.revalidate_after_observation = lambda _stage: 999.0

        control._observe_stage = shadow_after_checkpoint
        with pytest.raises(SolveExecutionBudgetExceeded):
            staging.commit_producer_bundle_publication(
                workspace, staged, checkpoint=checkpoint, lineage_owner=owner,
            )
    assert retained_count == [len(observed)]
    assert _exposure(workspace) == before
    assert (batch / "stage/candidates/candidate-1").is_dir()


def test_checkpoint_callback_cannot_remove_stage_before_final_native_gate(tmp_path, monkeypatch):
    workspace, batch, staged = _staged(tmp_path)
    before = _exposure(workspace)
    strategy = PopulationStrategy(build_context(tmp_path / "control"))
    owner = object.__new__(RSIPublicationLineage)

    def remove_stage(stage):
        if stage == "producer_commit_verified":
            (batch / "stage/candidates/candidate-1/main.py").unlink(missing_ok=True)

    control = SolveExecutionControl(30, clock=FakeClock(), observe_stage=remove_stage)
    monkeypatch.setattr(RSIPublicationLineage, "verify_precommit", lambda *args: None)
    with (
        bind_native_producer_bundle_control(strategy, control) as checkpoint,
        pytest.raises(staging.ProducerBundlePublicationStagingError),
    ):
        staging.commit_producer_bundle_publication(
            workspace, staged, checkpoint=checkpoint, lineage_owner=owner,
        )
    assert _exposure(workspace) == before
    assert not (batch / "terminal.json").exists()


def test_positive_original_control_publishes_without_post_evidence_callbacks(tmp_path, monkeypatch):
    workspace, _batch, staged = _staged(tmp_path)
    strategy = PopulationStrategy(build_context(tmp_path / "control"))
    owner = object.__new__(RSIPublicationLineage)
    observations = []
    retained_count = []
    control = SolveExecutionControl(30, clock=FakeClock(), observe_stage=observations.append)

    def observe_lineage(self, _journal, _manifest):
        assert self is owner
        retained_count.append(len(observations))

    monkeypatch.setattr(RSIPublicationLineage, "verify_precommit", observe_lineage)
    with bind_native_producer_bundle_control(strategy, control) as checkpoint:
        final = staging.commit_producer_bundle_publication(
            workspace, staged, checkpoint=checkpoint, lineage_owner=owner,
        )
    assert final.state == "published"
    assert retained_count == [len(observations)]
    assert not (workspace / "evolution/producer-publication.json").exists()
    assert (workspace / "evolution/candidates/candidate-1/main.py").is_file()
