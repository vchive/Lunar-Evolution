"""Durable producer budgets across real local process restarts and failed evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_bundle_intent import journal, workspace
from test_producer_bundle_transaction_control import FakeClock, _batch, _call, _fixture, _prefix

from lunar_evolution import producer_bundle_deadline as deadline
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.producer_bundle_deadline import (
    ProducerBundleDeadlineError,
    persist_controlled_producer_bundle_intent,
    restore_producer_bundle_execution_control,
)
from lunar_evolution.producer_bundle_intent import persist_producer_bundle_prepared_intent


def _persist(root, value, control):
    return persist_controlled_producer_bundle_intent(root, value, control, checkpoint=control.check)


def _path(root, value):
    return root / "evolution" / "producer-batches" / value.journal_id / "execution.deadline.json"


def _child_env():
    return {**os.environ, "PYTHONPATH": os.pathsep.join((str(Path("src").resolve()), str(Path("tests").resolve())))}


def test_same_boot_real_subprocess_restart_keeps_absolute_deadline(tmp_path):
    root, value = workspace(tmp_path), journal()
    script = """
import json, sys
from test_producer_bundle_intent import journal
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.producer_bundle_deadline import persist_controlled_producer_bundle_intent
control = SolveExecutionControl(30)
held = persist_controlled_producer_bundle_intent(sys.argv[1], journal(), control, checkpoint=control.check)
print(json.dumps({'deadline': control.deadline, 'started': control.started_at, 'remaining': held.check('child')}))
"""
    child = subprocess.run([sys.executable, "-c", script, str(root)], env=_child_env(), check=True, capture_output=True, text=True)
    original = json.loads(child.stdout)
    restored = restore_producer_bundle_execution_control(root, value)
    assert restored.timeout_seconds == 30
    assert restored.started_at == original["started"]
    assert restored.deadline == original["deadline"]
    assert 0 < restored.remaining() < original["remaining"]
    fresh = SolveExecutionControl(30)
    resumed = _persist(root, value, fresh)
    assert resumed.check("retry") < fresh.remaining()
    assert json.loads(resumed.raw)["deadline_monotonic"] == restored.deadline
    assert fresh.deadline > restored.deadline


def test_concurrent_processes_choose_one_deadline_and_exact_prepared_intent(tmp_path):
    root, value = workspace(tmp_path), journal()
    script = """
import json, sys
from test_producer_bundle_intent import journal
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.producer_bundle_deadline import persist_controlled_producer_bundle_intent
control = SolveExecutionControl(30)
held = persist_controlled_producer_bundle_intent(sys.argv[1], journal(), control, checkpoint=control.check)
print(held.raw.decode())
"""
    children = [subprocess.Popen([sys.executable, "-c", script, str(root)], env=_child_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    outputs = []
    for child in children:
        output, error = child.communicate(timeout=15)
        assert child.returncode == 0, error
        outputs.append(output)
    assert outputs[0] == outputs[1] == outputs[2]
    assert json.loads(_path(root, value).read_bytes())["journal_sha256"] == value.digest()
    assert (root / "evolution/producer-batches" / value.journal_id / "journal.prepared.json").is_file()


def test_reboot_and_monotonic_rollback_fail_closed(tmp_path, monkeypatch):
    root, value, clock = workspace(tmp_path), journal(), FakeClock()
    retained = _persist(root, value, SolveExecutionControl(30, clock=clock))
    with monkeypatch.context() as patch:
        patch.setattr(deadline, "_boot_id", lambda: "00000000-0000-0000-0000-000000000000")
        with pytest.raises(ProducerBundleDeadlineError, match="boot_changed"):
            retained.check("retry")
    clock.value -= 1
    with pytest.raises(ProducerBundleDeadlineError, match="clock_rollback"):
        retained.check("retry")


def test_injected_clock_is_explicitly_not_cross_process_restorable(tmp_path):
    root, value = workspace(tmp_path), journal()
    _persist(root, value, SolveExecutionControl(30, clock=FakeClock()))
    with pytest.raises(ProducerBundleDeadlineError, match="clock_unrestorable"):
        restore_producer_bundle_execution_control(root, value)


@pytest.mark.parametrize("damage", ["missing", "truncated", "edited", "noncanonical", "symlink", "hardlink", "inode", "mode"])
def test_retained_clock_damage_never_resets_budget_or_accepts_evidence(tmp_path, damage):
    root, value = workspace(tmp_path), journal()
    control = SolveExecutionControl(30)
    retained = _persist(root, value, control)
    path = _path(root, value)
    raw = path.read_bytes()
    if damage == "missing":
        path.unlink()
    elif damage == "truncated":
        path.write_bytes(b"{")
    elif damage == "edited":
        path.write_bytes(raw.replace(b'"timeout_seconds":30.0', b'"timeout_seconds":31.0'))
    elif damage == "noncanonical":
        path.write_bytes(raw + b"\n")
    elif damage == "symlink":
        source = tmp_path / "external"
        source.write_bytes(raw)
        path.unlink()
        path.symlink_to(source)
    elif damage == "hardlink":
        os.link(path, tmp_path / "external")
    elif damage == "inode":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(raw)
        replacement.chmod(0o600)
        os.replace(replacement, path)
    else:
        path.chmod(0o644)
    with pytest.raises(ProducerBundleDeadlineError):
        retained.check("retry")
    with pytest.raises(ProducerBundleDeadlineError):
        _persist(root, value, SolveExecutionControl(30))
    assert not path.exists() if damage == "missing" else path.read_bytes() != b""


def test_prepared_intent_without_clock_is_not_migrated(tmp_path):
    root, value = workspace(tmp_path), journal()
    persist_producer_bundle_prepared_intent(root, value)
    with pytest.raises(ProducerBundleDeadlineError, match="recovery_required"):
        _persist(root, value, SolveExecutionControl(30))
    assert not _path(root, value).exists()


def test_deadline_only_interruption_keeps_original_deadline(tmp_path, monkeypatch):
    root, value = workspace(tmp_path), journal()
    def interrupted(*_args):
        raise RuntimeError("interrupted before intent")
    with monkeypatch.context() as patch:
        patch.setattr(deadline, "_write_intent", interrupted)
        with pytest.raises(RuntimeError, match="interrupted"):
            _persist(root, value, SolveExecutionControl(30))
    raw = _path(root, value).read_bytes()
    restored = _persist(root, value, SolveExecutionControl(30))
    assert restored.raw == raw
    assert (root / "evolution/producer-batches" / value.journal_id / "journal.prepared.json").is_file()


def test_partial_write_is_retained_and_cannot_be_reinitialized(tmp_path, monkeypatch):
    root, value = workspace(tmp_path), journal()
    real_write = os.write
    calls = 0
    def partial_write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:8])
        raise OSError("fixture disk failure")
    with monkeypatch.context() as patch:
        patch.setattr(deadline.os, "write", partial_write)
        with pytest.raises(ProducerBundleDeadlineError, match="write_failed"):
            _persist(root, value, SolveExecutionControl(30))
    assert _path(root, value).read_bytes() == b'{"boot_i'
    with pytest.raises(ProducerBundleDeadlineError, match="invalid"):
        _persist(root, value, SolveExecutionControl(30))


def test_changed_journal_or_allowance_cannot_adopt_retained_clock(tmp_path):
    root, value = workspace(tmp_path), journal()
    _persist(root, value, SolveExecutionControl(30))
    with pytest.raises(ProducerBundleDeadlineError, match="journal_mismatch"):
        _persist(root, replace(value, parent_task_id="other", journal_sha256=None), SolveExecutionControl(30))
    with pytest.raises(ProducerBundleDeadlineError, match="allowance_mismatch"):
        _persist(root, value, SolveExecutionControl(31))


@pytest.mark.parametrize("reason", ["expired", "cancelled"])
def test_stop_before_preparation_creates_no_deadline(tmp_path, reason):
    root, value, clock = workspace(tmp_path), journal(), FakeClock()
    control = SolveExecutionControl(30, clock=clock)
    if reason == "expired":
        clock.value = control.deadline
    else:
        control.cancel()
    expected = SolveExecutionBudgetExceeded if reason == "expired" else SolveExecutionCancelled
    with pytest.raises(expected):
        _persist(root, value, control)
    assert not _path(root, value).exists()


def test_fresh_control_same_allowance_cannot_restart_expired_transaction(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    clock, evaluated = FakeClock(), []
    before = _prefix(context)
    def interrupted(*_args, **_kwargs):
        evaluated.append(True)
        raise RuntimeError("interrupted")
    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing", interrupted)
    first = SolveExecutionControl(30, clock=clock)
    with pytest.raises(transaction.NativeProducerBundleTransactionError, match="recovery_required"):
        _call(fixture, first)
    retained_path = _batch(context, journal_id) / "execution.deadline.json"
    raw = retained_path.read_bytes()
    clock.value = first.deadline
    fresh = SolveExecutionControl(30, clock=clock)
    with pytest.raises(SolveExecutionBudgetExceeded):
        _call(fixture, fresh)
    assert fresh.remaining() == 30
    assert first.deadline < fresh.deadline
    assert evaluated == [True]
    assert retained_path.read_bytes() == raw
    assert _prefix(context) == before


def test_no_control_transaction_keeps_historical_behavior(tmp_path):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    assert _call(fixture, None).publication_status == "published"
    assert not (_batch(context, journal_id) / "execution.deadline.json").exists()


def test_native_boot_identity_is_stable_and_platform_scoped():
    if sys.platform not in {"darwin", "linux"}:
        pytest.skip("native boot source supported on Linux and Darwin")
    assert deadline._boot_id() == deadline._boot_id()
    assert len(deadline._boot_id()) == 36


def test_expired_retained_clock_cannot_wait_on_new_control_budget(tmp_path, monkeypatch):
    import fcntl
    from threading import Thread

    root, value, clock = workspace(tmp_path), journal(), FakeClock()
    first = SolveExecutionControl(30, clock=clock)
    _persist(root, value, first)
    clock.value = first.deadline
    outputs = []
    lock_path = root / "evolution/producer-publication.lock"
    def retry():
        try:
            outputs.append(_persist(root, value, SolveExecutionControl(30, clock=clock)))
        except Exception as exc:  # noqa: BLE001 - expose any thread failure to the test
            outputs.append(exc)
    with lock_path.open("r+b") as locked:
        fcntl.flock(locked.fileno(), fcntl.LOCK_EX)
        worker = Thread(target=retry, daemon=True)
        worker.start()
        worker.join(1)
        try:
            assert not worker.is_alive(), "retained expiry must stop while the publication lock remains owned"
        finally:
            fcntl.flock(locked.fileno(), fcntl.LOCK_UN)
            worker.join(3)
    assert len(outputs) == 1 and isinstance(outputs[0], SolveExecutionBudgetExceeded)


def test_changed_deadline_after_first_evaluation_stops_transaction(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, values=(9, 8))
    context, _strategy, _drafts, _plan, journal_id = fixture
    original = context.bundle_pipeline.evaluate_draft_non_publishing
    completed = []
    def mutate_clock(*args, **kwargs):
        result = original(*args, **kwargs)
        completed.append(kwargs["ordinal"])
        path = _batch(context, journal_id) / "execution.deadline.json"
        path.write_bytes(path.read_bytes() + b"\n")
        return result
    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing", mutate_clock)
    with pytest.raises(transaction.NativeProducerBundleTransactionError, match="deadline_"):
        _call(fixture, SolveExecutionControl(30))
    assert completed == [0]
    assert not (_batch(context, journal_id) / "stage").exists()


def test_same_process_new_injected_clock_cannot_reuse_old_deadline(tmp_path):
    root, value = workspace(tmp_path), journal()
    original = FakeClock()
    control = SolveExecutionControl(30, clock=original)
    _persist(root, value, control)
    original.value = control.deadline
    replacement = FakeClock()
    assert replacement.value == control.started_at
    with pytest.raises(ProducerBundleDeadlineError, match="clock_mismatch|clock_unrestorable"):
        _persist(root, value, SolveExecutionControl(30, clock=replacement))
    with pytest.raises(ProducerBundleDeadlineError, match="clock_unrestorable"):
        restore_producer_bundle_execution_control(root, value)


def test_restore_requires_exact_prepared_journal(tmp_path):
    root, value = workspace(tmp_path), journal()
    control = SolveExecutionControl(30)
    _persist(root, value, control)
    path = root / "evolution/producer-batches" / value.journal_id / "journal.prepared.json"
    path.unlink()
    with pytest.raises(ProducerBundleDeadlineError, match="prepared_intent"):
        restore_producer_bundle_execution_control(root, value)


def test_injected_clock_registry_keeps_strong_reference(tmp_path):
    import gc
    import weakref

    root, value = workspace(tmp_path), journal()
    clock = FakeClock()
    reference = weakref.ref(clock)
    _persist(root, value, SolveExecutionControl(30, clock=clock))
    token = json.loads(_path(root, value).read_bytes())["clock_token"]
    del clock
    gc.collect()
    assert reference() is not None
    assert deadline._clock_for_token(token) is reference()


def test_restore_rejects_modified_prepared_intent(tmp_path):
    root, value = workspace(tmp_path), journal()
    _persist(root, value, SolveExecutionControl(30))
    path = root / "evolution/producer-batches" / value.journal_id / "journal.prepared.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ProducerBundleDeadlineError, match="prepared_intent_invalid"):
        restore_producer_bundle_execution_control(root, value)
