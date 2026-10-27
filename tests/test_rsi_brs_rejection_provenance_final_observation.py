"""Real owner must recheck P after its last dynamic observation.

Only source/ledger observers inject filesystem faults. Original owner methods,
native material validators, the publishing writer and pinned reader stay real.
"""

from __future__ import annotations

import inspect
from copy import deepcopy

import pytest
import test_rsi_brs_rejection_provenance as provenance_fixture

from lunar_evolution import rsi_brs_rejection_provenance as provenance
from lunar_evolution.rsi_learning import RSILearningError

c1 = provenance_fixture.c1
inert_only = provenance_fixture.inert_only
tmp_path = provenance_fixture.tmp_path
sealed_launch = provenance_fixture.sealed_launch


def _drift(value, fault):
    path = provenance_fixture._path(value)
    raw, inode = path.read_bytes(), path.stat().st_ino
    if fault == "same-bytes-new-inode":
        retained = path.with_name(path.name + ".original")
        path.rename(retained)
        path.write_bytes(raw)
        path.chmod(0o400)
        assert retained.read_bytes() == raw and retained.stat().st_ino == inode
        assert path.read_bytes() == raw and path.stat().st_ino != inode
    else:
        assert fault == "content-drift"
        path.chmod(0o600)
        path.write_bytes(raw + b"\n")
        path.chmod(0o400)
        assert path.stat().st_ino == inode and path.read_bytes() != raw
    return path.read_bytes(), path.stat().st_ino


def _direct_final_fixed():
    """Select the genuine ACK's final direct ledger observation, without replacing it."""
    frame = inspect.currentframe()
    try:
        # get_run <- _running <- _fixed: distinguish the later direct ACK call
        # from _observe's earlier _fixed call. Never inspect arbitrary deep stacks.
        for _ in range(5):
            frame = frame.f_back
            if frame is None:
                return False
            if frame.f_code is provenance._fixed.__code__:
                caller = frame.f_back
                return (frame.f_locals.get("expected") is not None and caller is not None
                        and caller.f_code is provenance.acknowledge_rejection_provenance.__code__)
        return False
    finally:
        del frame


@pytest.mark.parametrize(("observer", "fault"), [
    ("source", "same-bytes-new-inode"),
    ("source", "content-drift"),
    ("ledger", "same-bytes-new-inode"),
])
def test_post_c2_observation_p_drift_keeps_unknown_and_original_c1(
    tmp_path, monkeypatch, observer, fault,
):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = c1.owner_fixture._capture(value)
        write = value.ledger.write_controller_checkpoint
        read = value.ledger.controller_checkpoint
        source = value.gateway.rsi_fingerprint_config
        get_run = value.ledger.get_run
        durable, injected = [], []

        def written(run_id, state, *, expected_sha256):
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            return head

        def source_observed():
            result = source()
            if durable and not injected:
                injected.append(_drift(value, fault))
            return result

        def ledger_observed(run_id):
            result = get_run(run_id)
            if durable and not injected and _direct_final_fixed():
                injected.append(_drift(value, fault))
            return result

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", written)
        if observer == "source":
            monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source_observed)
        else:
            monkeypatch.setattr(value.ledger, "get_run", ledger_observed)

        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_provenance()

        assert len(injected) == len(durable) == 1
        assert durable[0][0] != captured[0]
        assert read(value.binding.run_id) == durable[0]
        c1.owner_fixture._unchanged(value, captured)
        assert value.owner._rejection_c1_capture == captured[:2]
        assert value.owner._rejection_provenance_c2_capture is None
        assert value.owner._phase == "rejected" and value.owner._poisoned
        assert not value.owner._retaining_rejection_provenance
        assert value.owner._rejection_provenance_deadline is None
        path = provenance_fixture._path(value)
        assert (path.read_bytes(), path.stat().st_ino) == injected[0]
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_provenance()
        assert len(durable) == 1 and read(value.binding.run_id) == durable[0]
        assert (path.read_bytes(), path.stat().st_ino) == injected[0]
        c1._quiet(value)


@pytest.mark.parametrize("fault", ["same-bytes-new-inode", "content-drift"])
def test_getter_second_source_observation_p_drift_never_returns_a_pin(
    tmp_path, monkeypatch, fault,
):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        value.owner.retain_rejection_provenance()
        captured = c1.owner_fixture._capture(value)
        c2_capture = value.owner._rejection_provenance_c2_capture
        original_pin = value.owner._rejection_provenance_file_pin
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        source = value.gateway.rsi_fingerprint_config
        observed, injected = [], []

        def source_observed():
            result = source()
            observed.append(result)
            if len(observed) == 2:
                injected.append(_drift(value, fault))
            return result

        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source_observed)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.rejection_provenance_file_pin()

        assert len(observed) == 2 and len(injected) == 1
        assert value.owner._rejection_provenance_file_pin is original_pin
        assert value.owner._rejection_provenance_c2_capture is c2_capture
        assert value.owner._phase == "rejected-provenance" and value.owner._poisoned
        c1.owner_fixture._unchanged(value, captured)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (captured[0], captured[2])
        path = provenance_fixture._path(value)
        assert (path.read_bytes(), path.stat().st_ino) == injected[0]
        c1._quiet(value)


def test_post_c2_source_installed_reader_shadow_fails_final_canonical_gate(tmp_path, monkeypatch):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = c1.owner_fixture._capture(value)
        write = value.ledger.write_controller_checkpoint
        read = value.ledger.controller_checkpoint
        source = value.gateway.rsi_fingerprint_config
        durable, injected = [], []

        def written(run_id, state, *, expected_sha256):
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            return head

        def shadow(run_id):
            return read(run_id)

        def source_observed():
            result = source()
            if durable and not injected:
                path = provenance_fixture._path(value)
                injected.append((path.read_bytes(), path.stat().st_ino))
                monkeypatch.setattr(value.ledger, "controller_checkpoint", shadow)
            return result

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", written)
        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source_observed)
        with pytest.raises(RSILearningError, match="_final_reader_drift$"):
            value.owner.retain_rejection_provenance()

        assert len(injected) == len(durable) == 1
        assert read(value.binding.run_id) == durable[0]
        c1.owner_fixture._unchanged(value, captured)
        assert value.owner._rejection_provenance_c2_capture is None
        assert value.owner._phase == "rejected" and value.owner._poisoned
        path = provenance_fixture._path(value)
        assert (path.read_bytes(), path.stat().st_ino) == injected[0]
        c1._quiet(value)


def test_final_provenance_readback_refuses_history_observer_shadow_before_invocation(tmp_path, monkeypatch):
    with c1._waiting(tmp_path, monkeypatch) as value:
        before = c1.owner_fixture._capture(value)
        calls = []

        def replacement(*_args, **_kwargs):
            calls.append("unexpected-instance-reader")
            raise AssertionError("final provenance readback invoked a shadow")

        with monkeypatch.context() as changed:
            changed.setattr(value.ledger, "_controller_checkpoint_history_observation_tx", replacement)
            with pytest.raises(RSILearningError, match="_final_reader_drift$"):
                provenance._readback(value.owner, "a" * 64, {}, b"{}", final=True)
        assert calls == []
        c1.owner_fixture._unchanged(value, before)
        c1._quiet(value)
