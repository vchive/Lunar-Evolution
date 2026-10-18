"""Pre-arm reference checks over genuine inert waiting C1/P/C2 owners."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from threading import Thread

import pytest
import test_rsi_brs_rejection_c1 as c1
import test_rsi_brs_rejection_provenance as provenance

from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_rejection_ready_ledger import read_rejection_ready_rows
from lunar_evolution.rsi_brs_rejection_ready_reference import validate_existing_rejection_reference
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_admission import RSIPythonAdmissionRecord

inert_only = c1.inert_only
tmp_path = c1.tmp_path
sealed_launch = provenance.sealed_launch


@contextmanager
def _rejected(tmp_path, monkeypatch, *, count=1):
    with c1._waiting(tmp_path, monkeypatch, count=count) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        value.owner.retain_rejection_provenance()
        yield value


def _raw(value):
    return read_rejection_ready_rows(
        str(value.ledger.database), run_id=value.binding.run_id, episode_ids=value.wave.episode_ids,
    )


@pytest.mark.parametrize("count", [1, 2])
def test_original_c2_reference_returns_immutable_bytes_without_ready_or_mutation(tmp_path, monkeypatch, count):
    with _rejected(tmp_path, monkeypatch, count=count) as value:
        captures = c1.owner_fixture._capture(value)
        rows, files = _raw(value), c1._native_material_snapshot(value)
        c2 = value.owner._rejection_provenance_c2_capture

        result = validate_existing_rejection_reference(value.owner)

        assert type(result) is tuple and len(result) == 4
        reference, record, digest, episodes = result
        assert type(reference) is bytes and type(record) is bytes and type(digest) is str
        assert type(episodes) is tuple and episodes == tuple(sorted(value.wave.episode_ids))
        selected = value.wave.state["python_admission_refs"][value.episode_id]
        assert reference == canonical_json(selected)
        retained = RSIPythonAdmissionRecord.from_json(record)
        assert digest == selected["record_sha256"] == retained.record_sha256
        assert retained.native_plan_sha256 == value.plan.plan_sha256
        assert retained.prepared_journal_sha256 == value.journal.digest()
        with pytest.raises(TypeError):
            result[0] = b"replacement"
        assert validate_existing_rejection_reference(value.owner) == result
        assert value.owner._rejection_provenance_c2_capture is c2
        c1.owner_fixture._unchanged(value, captures)
        assert _raw(value) == rows and c1._native_material_snapshot(value) == files
        assert value.owner._phase == "rejected-provenance" and value.owner._poisoned is False
        c1._quiet(value)


@pytest.mark.parametrize("kind", ["foreign", "subclass", "phase", "poisoned", "retaining", "thread"])
def test_nonoriginal_or_inactive_owner_refuses_without_mutating_original(tmp_path, monkeypatch, kind):
    with _rejected(tmp_path, monkeypatch) as value:
        owner = value.owner
        if kind == "foreign":
            owner = object()
        elif kind == "subclass":
            class Foreign(brs._BRSLineageCheckpointOwner):
                pass
            owner = object.__new__(Foreign)
        elif kind == "phase":
            value.owner._phase = "rejected"
        elif kind == "poisoned":
            value.owner._poisoned = True
        elif kind == "retaining":
            value.owner._retaining_rejection_provenance = True
        rows, captures = _raw(value), c1.owner_fixture._capture(value)
        if kind == "thread":
            errors = []

            def work():
                try:
                    validate_existing_rejection_reference(owner)
                except RSILearningError as error:
                    errors.append(error)

            thread = Thread(target=work)
            thread.start()
            thread.join(15)
            assert not thread.is_alive() and len(errors) == 1
        else:
            with pytest.raises(RSILearningError):
                validate_existing_rejection_reference(owner)
        c1.owner_fixture._unchanged(value, captures)
        assert _raw(value) == rows
        c1._quiet(value)


@pytest.mark.parametrize("field", ["_run_head", "_episode_head", "_head", "_payload"])
def test_held_original_head_or_payload_drift_refuses_without_refresh(tmp_path, monkeypatch, field):
    with _rejected(tmp_path, monkeypatch) as value:
        original = getattr(value.owner, field)
        replacement = b"{}" if field == "_payload" else "f" * 64
        monkeypatch.setattr(value.owner, field, replacement)
        rows = _raw(value)
        with pytest.raises(RSILearningError):
            validate_existing_rejection_reference(value.owner)
        assert getattr(value.owner, field) == replacement
        assert _raw(value) == rows and value.owner._poisoned is False
        monkeypatch.setattr(value.owner, field, original)
        c1._quiet(value)


def test_same_payload_later_checkpoint_is_refused_and_never_adopted(tmp_path, monkeypatch):
    with _rejected(tmp_path, monkeypatch) as value:
        original = c1.owner_fixture._capture(value)
        later = value.ledger.write_controller_checkpoint(
            value.binding.run_id, deepcopy(value.wave.state), expected_sha256=value.owner._head,
        )
        rows = _raw(value)
        assert later != value.owner._head
        with pytest.raises(RSILearningError):
            validate_existing_rejection_reference(value.owner)
        c1.owner_fixture._unchanged(value, original)
        assert _raw(value) == rows and value.owner._poisoned is False
        c1._quiet(value)


@pytest.mark.parametrize("fault", ["missing-record", "record-payload", "native-claim", "result"])
def test_real_sqlite_evidence_drift_is_refused_without_repair(tmp_path, monkeypatch, fault):
    with _rejected(tmp_path, monkeypatch) as value:
        with sqlite3.connect(value.ledger.database) as connection:
            if fault == "missing-record":
                connection.execute("DELETE FROM rsi_python_admissions WHERE episode_id=?", (value.episode_id,))
            elif fault == "record-payload":
                connection.execute("UPDATE rsi_python_admissions SET payload='{}' WHERE episode_id=?",
                                   (value.episode_id,))
            elif fault == "native-claim":
                connection.execute("UPDATE rsi_native_episode_claims SET plan_sha256=? WHERE episode_id=?",
                                   ("f" * 64, value.episode_id))
            else:
                connection.execute("INSERT INTO rsi_episode_results VALUES (?,?,?,?,?,?)",
                                   (value.episode_id, value.request.digest(), "{}", "{}", "f" * 64, "fixture"))
        rows, captured = _raw(value), c1.owner_fixture._capture(value)
        with pytest.raises((RSILearningError, ValueError)):
            validate_existing_rejection_reference(value.owner)
        assert _raw(value) == rows
        c1.owner_fixture._unchanged(value, captured)
        assert value.owner._poisoned is False
        assert not value.ready.is_set() and value.messages.empty()


@pytest.mark.parametrize("name", ["journal.prepared.json", "python-producer-admission-anchor.json",
                                 "python-producer-admission-handoff.json"])
def test_selected_original_file_drift_refuses_without_replacing_it(tmp_path, monkeypatch, name):
    with _rejected(tmp_path, monkeypatch) as value:
        path = value.batch / name
        assert path.is_file()
        path.chmod(0o600)
        path.write_bytes(b"{}")
        rows, captures = _raw(value), c1.owner_fixture._capture(value)
        with pytest.raises((RSILearningError, ValueError)):
            validate_existing_rejection_reference(value.owner)
        assert path.read_bytes() == b"{}" and _raw(value) == rows
        c1.owner_fixture._unchanged(value, captures)
        assert value.owner._poisoned is False
        c1._quiet(value)


@pytest.mark.parametrize("target,name", [
    ("controller", "_python_admission_evidence"), ("controller", "_python_admission_inputs"),
    ("controller", "_validate_python_admission_references"),
    ("ledger", "python_admission_record"), ("ledger", "controller_checkpoint"),
    ("ledger", "_connect"), ("ledger", "_python_admission_state_tx"),
])
def test_reader_instance_shadows_refuse_before_invoking_replacement(tmp_path, monkeypatch, target, name):
    with _rejected(tmp_path, monkeypatch) as value:
        calls = []

        def replacement(*_args, **_kwargs):
            calls.append("forged-read")
            raise AssertionError("instance replacement invoked")

        with monkeypatch.context() as changed:
            changed.setattr(getattr(value, target), name, replacement)
            with pytest.raises(RSILearningError, match="reader_shadow"):
                validate_existing_rejection_reference(value.owner)
        assert calls == []
        c1._quiet(value)


def test_returned_reference_preserves_all_original_reference_fields(tmp_path, monkeypatch):
    with _rejected(tmp_path, monkeypatch) as value:
        reference, record, digest, episodes = validate_existing_rejection_reference(value.owner)
        wire = json.loads(reference)
        assert set(wire) == {"journal_id", "attempt_id", "record_sha256", "native_plan", "prepared_journal"}
        assert wire["native_plan"] == value.plan.to_dict()
        assert wire["prepared_journal"] == value.journal.to_dict()
        assert json.loads(record)["record_sha256"] == digest
        assert value.episode_id in episodes and value.sibling_id in episodes
        c1._quiet(value)
