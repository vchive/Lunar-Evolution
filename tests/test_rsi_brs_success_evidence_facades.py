"""Original BRS success evidence facades over explicit inert native files only."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from threading import Thread
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_brs_staged_terminal_checkpoint as retained
import test_rsi_python_brs_publication_recovery as native_recovered

from lunar_evolution import RSILearningError
from lunar_evolution import producer_bundle_recovery as recovery
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution import rsi_producer_staging_capsule as capsule
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("u")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    # Reuse the explicit transaction, evaluator, subprocess and socket refusal.
    retained.inert_only.__wrapped__(monkeypatch)


class _FixtureBoundary(Exception):
    pass


def _stop_fixture(*_args, **_kwargs):
    raise _FixtureBoundary


@contextmanager
def _waiting(tmp_path, monkeypatch):
    with native_recovered._waiting(tmp_path, monkeypatch) as value:
        value.owner.checkpoint_before(owner_fixture._before(value))
        record = value.controller._pin_python_admission_for_original_brs_owner(
            value.owner, expected_anchor_sha256=value.anchor.anchor_sha256,
        )
        value.owner.acknowledge_prepared(value.journal, record)
        assert not value.wave.channel._requests and not value.wave.channel._queue
        assert not value.ready.is_set() and value.messages.empty()
        yield value


def _stage(value, monkeypatch, **kwargs):
    # Stop the old inert file builder before its first lineage snapshot create.
    # The owner below must create every after snapshot and success descriptor.
    with monkeypatch.context() as patch:
        patch.setattr(retained, "persist_lineage_snapshot", _stop_fixture)
        with pytest.raises(_FixtureBoundary):
            retained._staged(value, **kwargs)
    value.staged = recovery._read_journal(value.batch / "journal.staged.json")
    value.manifest = staging._load_manifest(value.batch)
    return value.staged, value.manifest


def _publish_fixture(value, monkeypatch):
    # Explicit fixture file installation only. Product stage/commit stay blocked.
    with monkeypatch.context() as patch:
        patch.setattr(retained, "persist_lineage_descriptor", _stop_fixture)
        with pytest.raises(_FixtureBoundary):
            retained._terminal(value)
    for name in ("archive.jsonl", "state.json"):
        (value.batch / "stage" / name).replace(value.workspace / "evolution" / name)
    root = value.workspace / "evolution/candidates"
    root.mkdir()
    for candidate in value.staged.candidates:
        (value.batch / "stage/candidates" / candidate.candidate_id).rename(root / candidate.candidate_id)
    return recovery._read_journal(value.batch / "journal.published.json")


def _marker(value, *, status="staged", manifest_sha=None):
    path = value.workspace / "evolution/producer-publication.json"
    path.write_bytes(staging._marker_bytes(staging.marker_payload(journal_id=value.staged.journal_id,
        journal_sha256=value.staged.digest(), manifest_sha256=manifest_sha or value.manifest.digest(), status=status)))
    path.chmod(0o600)
    return path


def _lineage_files(value):
    root = value.batch / "lineage"
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def _controlled(monkeypatch, *, on_predicate=None):
    calls, now, cancelled = [], [0.0], [False]
    def observe(stage):
        assert not staging._HELD_PUBLICATION_LOCKS.get(), "control hook ran under publication lock"
        calls.append(stage)
    def clock():
        observe("clock")
        return now[0]
    def predicate():
        observe("cancel")
        if on_predicate is not None:
            on_predicate()
        return cancelled[0]
    control = SolveExecutionControl(1000, started_at=0, clock=clock,
        cancellation_callbacks=(predicate,), observe_stage=observe)
    setup = native_recovered._setup
    def controlled(root, patch):
        value = setup(root, patch)
        object.__setattr__(value.native, "execution_control", control)
        object.__setattr__(value.native, "cancelled", predicate)
        return value
    monkeypatch.setattr(native_recovered, "_setup", controlled)
    return control, now, cancelled, calls


def test_retains_exact_native_success_files_and_only_two_adjacent_cas(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        before = owner_fixture._capture(value)
        original, writes = value.ledger.write_controller_checkpoint, []
        def observe(run_id, state, *, expected_sha256):
            writes.append((expected_sha256, deepcopy(state)))
            return original(run_id, state, expected_sha256=expected_sha256)
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observe)
        staged, manifest = _stage(value, monkeypatch)
        assert set(_lineage_files(value)) == {"before.json", "archive-before.snapshot", "state-before.snapshot"}
        value.owner.retain_staged(staged, manifest)
        stage_head = value.owner._head
        entry = value.wave.state["producer_publication_lineage"]["batches"][0]
        for name in ("archive", "state"):
            filename = name + (".jsonl" if name == "archive" else ".json")
            assert (value.batch / "lineage" / (name + "-after.snapshot")).read_bytes() == (value.batch / "stage" / filename).read_bytes()
        assert entry["staged"]["journal_sha256"] == staged.digest()
        published = _publish_fixture(value, monkeypatch)
        value.owner.retain_terminal(published, manifest)
        assert [write[0] for write in writes] == [before[0], stage_head]
        assert value.owner._phase == "terminal" and not value.owner._poisoned
        assert value.wave.state == before[2] | {"producer_publication_lineage": writes[-1][1]["producer_publication_lineage"]}
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (value.owner._head, value.wave.state)
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
        assert value.ledger.episode_result(value.episode_id) is None
        assert json.loads(value.owner._policy_bytes)["online_publication"] is False
        assert json.loads(value.owner._policy_bytes)["production_admission"] is False


def test_precommit_observes_real_lock_and_evidence_without_any_user_callback(tmp_path, monkeypatch):
    _control, _now, _cancelled, calls = _controlled(monkeypatch)
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch)
        value.owner.retain_staged(staged, manifest)
        _marker(value)
        before, files = owner_fixture._capture(value), _lineage_files(value)
        original = value.gateway.rsi_fingerprint_config
        def no_hooks(*args, **kwargs):
            pytest.fail("precommit replayed an original source/config callback")
        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", no_hooks)
        previous = list(calls)
        with staging._locked(value.workspace):
            value.owner.verify_precommit(staged, manifest)
            value.owner._success_fixed("fixture")
        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", original)
        owner_fixture._unchanged(value, before)
        assert _lineage_files(value) == files and not value.owner._poisoned
        assert calls == previous and previous


@pytest.mark.parametrize("method", ["retain_staged", "retain_terminal"])
def test_retention_refuses_publication_lock_before_source_callbacks(tmp_path, monkeypatch, method):
    with _waiting(tmp_path, monkeypatch) as value:
        before, files = owner_fixture._capture(value), _lineage_files(value)
        with staging._locked(value.workspace), pytest.raises(RSILearningError, match="before_unlocked_owner_required"):
            getattr(value.owner, method)(object(), object())
        owner_fixture._unchanged(value, before)
        assert _lineage_files(value) == files and value.owner._poisoned


@pytest.mark.parametrize("failure", ["missing-lock", "missing-marker", "unknown-marker", "wrong-manifest", "source-replaced", "staged-bytes", "closed-channel"])
def test_precommit_fails_closed_without_checkpoint_or_head_refresh(tmp_path, monkeypatch, failure):
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch)
        value.owner.retain_staged(staged, manifest)
        if failure not in {"missing-marker", "missing-lock"}:
            _marker(value, status="unknown" if failure == "unknown-marker" else "staged",
                manifest_sha="f" * 64 if failure == "wrong-manifest" else None)
        if failure == "source-replaced":
            path = value.workspace / "evolution/state.json"
            other = path.with_suffix(".other")
            other.write_bytes(path.read_bytes())
            other.chmod(0o600)
            other.replace(path)
        if failure == "staged-bytes":
            (value.batch / "stage/state.json").write_bytes(b"{}")
        if failure == "closed-channel":
            value.wave.channel.close()
        before, files = owner_fixture._capture(value), _lineage_files(value)
        if failure == "missing-lock":
            with pytest.raises(RSILearningError, match="publication_lock_required"):
                value.owner.verify_precommit(staged, manifest)
        else:
            with staging._locked(value.workspace), pytest.raises((RSILearningError, ValueError)):
                value.owner.verify_precommit(staged, manifest)
        owner_fixture._unchanged(value, before)
        assert _lineage_files(value) == files and value.owner._poisoned


@pytest.mark.parametrize("method", ["retain_staged", "retain_terminal", "verify_precommit"])
def test_foreign_success_dtos_do_not_gain_authority_or_create_evidence(tmp_path, monkeypatch, method):
    with _waiting(tmp_path, monkeypatch) as value:
        before, files = owner_fixture._capture(value), _lineage_files(value)
        with pytest.raises((RSILearningError, ValueError)):
            getattr(value.owner, method)(object(), None)
        owner_fixture._unchanged(value, before)
        assert _lineage_files(value) == files and value.owner._poisoned


@pytest.mark.parametrize("bad_projection,record_mismatch", [(True, False), (False, True)])
def test_invalid_native_candidate_projection_preserves_created_evidence(tmp_path, monkeypatch, bad_projection, record_mismatch):
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch, bad_projection=bad_projection, record_mismatch=record_mismatch)
        before = owner_fixture._capture(value)
        with pytest.raises(RSILearningError, match="(projection|material_record)_drift"):
            value.owner.retain_staged(staged, manifest)
        owner_fixture._unchanged(value, before)
        assert "staged.json" in _lineage_files(value) and value.owner._poisoned


@pytest.mark.parametrize("phase", ["staged", "terminal"])
def test_create_conflict_preserves_existing_bytes_without_cas(tmp_path, monkeypatch, phase):
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch)
        if phase == "terminal":
            value.owner.retain_staged(staged, manifest)
            journal = _publish_fixture(value, monkeypatch)
        else:
            journal = staged
        path = value.batch / "lineage" / ("archive-after.snapshot" if phase == "staged" else "terminal.json")
        retained._write(path, b"preserve conflict")
        before = owner_fixture._capture(value)
        with pytest.raises(ValueError):
            getattr(value.owner, "retain_" + phase)(journal, manifest)
        owner_fixture._unchanged(value, before)
        assert path.read_bytes() == b"preserve conflict" and value.owner._poisoned


def test_success_owner_is_not_transferrable_to_foreign_thread(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch)
        before, files, errors = owner_fixture._capture(value), _lineage_files(value), []
        def run():
            try:
                value.owner.retain_staged(staged, manifest)
            except RSILearningError as exc:
                errors.append(exc)
        thread = Thread(target=run)
        thread.start()
        thread.join(5)
        assert not thread.is_alive() and len(errors) == 1 and isinstance(errors[0], RSILearningError)
        owner_fixture._unchanged(value, before)
        assert _lineage_files(value) == files and value.owner._poisoned


def test_shared_ready_allowance_and_after_snapshots_are_bounded_before_creates(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch)
        before, files = owner_fixture._capture(value), _lineage_files(value)
        old_size = sum(pin["size"] for pin in value.wave.state["producer_publication_lineage"]["batches"][0]["snapshots"].values())
        after_size = sum((value.batch / "stage" / name).stat().st_size for name in ("archive.jsonl", "state.json"))
        monkeypatch.setattr(capsule, "retained_ready_capsule_bytes",
            lambda _state: brs.MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - old_size - after_size + 1)
        with pytest.raises(RSILearningError, match="capacity_exceeded"):
            value.owner.retain_staged(staged, manifest)
        owner_fixture._unchanged(value, before)
        assert _lineage_files(value) == files and value.owner._poisoned


@pytest.mark.parametrize("entry", ["marker", "read", "projection", "owner"])
def test_new_live_precommit_dependencies_refuse_foreign_globals(monkeypatch, entry):
    from lunar_evolution import evolution

    target, name = {"marker": (staging, "_load_marker"), "read": (staging, "_read"),
        "projection": (evolution.PopulationStrategy, "_rank"),
        "owner": (brs._BRSLineageCheckpointOwner, "_success_entry")}[entry]
    original = getattr(target, name)
    clone = FunctionType(original.__code__, dict(original.__globals__), original.__name__, original.__defaults__, original.__closure__)
    monkeypatch.setattr(target, name, clone)
    expected = ("^rsi_brs_publication_lineage_native_reader_binding_drift$"
                if entry == "read" else "native_reader_globals_drift")
    with pytest.raises(RSILearningError, match=expected):
        brs._policy()


@pytest.mark.parametrize("fault", ["source-reset", "control-extend"])
def test_full_callbacks_cannot_refresh_this_retention_numeric_cap(tmp_path, monkeypatch, fault):
    holder, changed = [], []
    def tamper():
        if not holder or changed:
            return
        value = holder[0]
        if (value.batch / "lineage/staged.json").exists() and value.owner._success_deadline is not None:
            value.owner._success_deadline = None if fault == "source-reset" else value.owner._success_deadline + 1000.0
            changed.append(True)
    _controlled(monkeypatch, on_predicate=tamper if fault == "control-extend" else None)
    with _waiting(tmp_path, monkeypatch) as value:
        holder.append(value)
        staged, manifest = _stage(value, monkeypatch)
        before = owner_fixture._capture(value)
        configuration = value.gateway.rsi_fingerprint_config
        def source():
            if fault == "source-reset":
                tamper()
            return configuration()
        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source)
        with pytest.raises(RSILearningError, match="success_allowance_drift"):
            value.owner.retain_staged(staged, manifest)
        owner_fixture._unchanged(value, before)
        assert changed and "staged.json" in _lineage_files(value) and value.owner._poisoned
        assert value.ledger.controller_checkpoint(value.binding.run_id)[0] == before[0]


@pytest.mark.parametrize("phase", ["staged", "terminal"])
@pytest.mark.parametrize("fault", ["competing-cas", "missing-readback", "wrong-payload", "post-close", "post-cancel"])
def test_success_uncertain_cas_preserves_evidence_and_original_capture(tmp_path, monkeypatch, phase, fault):
    control, _now, _cancelled, _calls = _controlled(monkeypatch)
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch)
        if phase == "terminal":
            value.owner.retain_staged(staged, manifest)
            journal = _publish_fixture(value, monkeypatch)
        else:
            journal = staged
        before, write, read, durable = owner_fixture._capture(value), value.ledger.write_controller_checkpoint, value.ledger.controller_checkpoint, []
        def checkpoint(run_id, state, *, expected_sha256):
            if fault == "competing-cas":
                foreign = deepcopy(value.wave.state) | {"foreign": True}
                durable.append((write(run_id, foreign, expected_sha256=expected_sha256), foreign))
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            if fault == "post-close":
                value.wave.channel.close()
            if fault == "post-cancel":
                control.cancel()
            return head
        def readback(run_id):
            if durable and fault in {"missing-readback", "wrong-payload"}:
                return None if fault == "missing-readback" else (durable[0][0], {"foreign": True})
            return read(run_id)
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", checkpoint)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", readback)
        with pytest.raises((RSILearningError, ValueError)):
            getattr(value.owner, "retain_" + phase)(journal, manifest)
        owner_fixture._unchanged(value, before)
        assert len(durable) == 1 and read(value.binding.run_id) == durable[0]
        assert phase + ".json" in _lineage_files(value) and value.owner._poisoned
        with pytest.raises(RSILearningError):
            getattr(value.owner, "retain_" + phase)(journal, manifest)
        assert len(durable) == 1


@pytest.mark.parametrize("phase", ["staged", "terminal"])
def test_final_fixed_evidence_latency_exhausts_temporary_cap_before_cas(tmp_path, monkeypatch, phase):
    import sys
    import time

    from lunar_evolution import producer_request_transport

    _control, now, _cancelled, _calls = _controlled(monkeypatch)
    enabled, elapsed_injected = [], []
    original_monotonic, frozen, elapsed = time.monotonic, [None], [0.0]
    def monotonic():
        return (original_monotonic() if frozen[0] is None else frozen[0]) + elapsed[0]
    # Install one stable clock before policy capture, including the reader's
    # canonical default binding. Freeze only this retention's elapsed time so
    # a busy machine cannot consume its five-second allowance before injection.
    monkeypatch.setattr(time, "monotonic", monotonic)
    monkeypatch.setitem(producer_request_transport.read_host_request_journal.__kwdefaults__,
                        "monotonic", monotonic)
    original_read = brs._files.read_regular_file
    def observe_read(*args, **kwargs):
        result = original_read(*args, **kwargs)
        if enabled and not elapsed_injected:
            frame = sys._getframe()
            try:
                while frame is not None:
                    if frame.f_code.co_name == "_success_entry" and frame.f_locals.get("fixed") is True:
                        elapsed_injected.append(True)
                        elapsed[0] += 6.0
                        break
                    frame = frame.f_back
            finally:
                del frame
        return result
    # Stable inert I/O double, installed before the original owner/policy capture.
    monkeypatch.setattr(brs._files, "read_regular_file", observe_read)
    with _waiting(tmp_path, monkeypatch) as value:
        staged, manifest = _stage(value, monkeypatch)
        if phase == "terminal":
            value.owner.retain_staged(staged, manifest)
            journal = _publish_fixture(value, monkeypatch)
        else:
            journal = staged
        before = owner_fixture._capture(value)
        now[0] = 995.0  # Original fixed native deadline has five seconds remaining.
        frozen[0] = original_monotonic()
        enabled.append(True)
        with pytest.raises(RSILearningError, match="success_allowance_exhausted"):
            getattr(value.owner, "retain_" + phase)(journal, manifest)
        owner_fixture._unchanged(value, before)
        assert elapsed_injected == [True] and phase + ".json" in _lineage_files(value) and value.owner._poisoned
        assert value.ledger.controller_checkpoint(value.binding.run_id)[0] == before[0]
