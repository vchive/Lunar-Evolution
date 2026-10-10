from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationError,
    build_producer_bundle_publication_journal,
    parse_producer_bundle_publication_journal,
)
from lunar_evolution.python_producer_admission_handoff import (
    parse_python_producer_admission_handoff_file_pin,
)


def _digest(letter: str) -> str:
    return letter * 64


def _candidate(index: int = 0, *, status: str = "planned") -> ProducerBundlePublicationCandidate:
    return ProducerBundlePublicationCandidate(
        candidate_id=f"candidate-{index}",
        bundle_id=f"bundle-{index}",
        bundle_sha256=_digest("a"),
        parent_id=None,
        generation=0,
        iteration=0,
        island_id=index,
        preparation_receipt_sha256=_digest("b" if index == 0 else "7"),
        status=status,
    )


def _journal(*candidates: ProducerBundlePublicationCandidate, **changes: object):
    values = {
        "journal_id": "journal-1",
        "run_id": "run-1",
        "parent_task_id": "parent-1",
        "task_id": "task-1",
        "admission_sha256": _digest("c"),
        "archive_prefix_sha256": _digest("d"),
        "base_archive_sha256": _digest("e"),
        "base_state_sha256": _digest("f"),
        "contract_sha256": _digest("0"),
        "evaluator_kind": "exact_harness",
        "evaluator_fingerprint": _digest("1"),
        "runner_fingerprint": _digest("2"),
        "dependency_sha256": _digest("3"),
        "environment_sha256": _digest("4"),
        "budget_sha256": _digest("5"),
        "strategy": "population",
        "population_config_sha256": _digest("6"),
        "num_islands": max(1, len(candidates)),
        "candidates": candidates or (_candidate(),),
    }
    values.update(changes)
    return build_producer_bundle_publication_journal(**values)


def test_builds_canonical_journal_and_excludes_its_own_digest() -> None:
    journal = _journal(_candidate(0), _candidate(1))

    assert len(journal.journal_sha256 or "") == 64
    assert journal.digest() == journal.journal_sha256
    assert journal.to_dict()["journal_sha256"] == journal.digest()
    payload = journal.to_dict()
    payload.pop("journal_sha256")
    assert journal.digest() == __import__("hashlib").sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_round_trip_mapping_and_file_are_stable(tmp_path: Path) -> None:
    journal = _journal(_candidate())
    assert "native_execution_receipt_sha256" not in journal.to_dict()
    assert journal.digest() == "393756681e2fb529b2c92aab0959988db0f7d2b09c8650ff84a39d4a80600b3b"
    assert parse_producer_bundle_publication_journal(journal.to_dict()).to_dict() == journal.to_dict()
    path = tmp_path / "journal.json"
    path.write_text(json.dumps(journal.to_dict()), encoding="utf-8")
    assert parse_producer_bundle_publication_journal(path).digest() == journal.digest()


def test_optional_native_execution_receipt_round_trip_changes_digest() -> None:
    legacy = _journal(_candidate())
    linked = _journal(_candidate(), native_execution_receipt_sha256=_digest("9"))

    payload = linked.to_dict()
    assert payload["native_execution_receipt_sha256"] == _digest("9")
    assert parse_producer_bundle_publication_journal(payload).to_dict() == payload
    assert linked.digest() == linked.journal_sha256
    assert linked.digest() != legacy.digest()


def test_optional_python_handoff_requires_native_receipt_and_round_trips() -> None:
    legacy = _journal(_candidate())
    linked = _journal(
        _candidate(), native_execution_receipt_sha256=_digest("8"),
        python_handoff_sha256=_digest("9"),
    )
    payload = linked.to_dict()
    assert payload["python_handoff_sha256"] == _digest("9")
    assert parse_producer_bundle_publication_journal(payload).to_dict() == payload
    assert linked.digest() != legacy.digest()
    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(_candidate(), python_handoff_sha256=_digest("9"))
    assert caught.value.code == "producer_bundle_publication_python_handoff_execution_link_missing"


def _file_pin(**changes: object):
    payload = {
        "schema_version": "1",
        "protocol": "lunar-python-producer-admission-handoff-file-pin-v1",
        "run_id": "run-1", "journal_id": "journal-1",
        "parent_task_id": "parent-1", "task_id": "task-1",
        "handoff_sha256": _digest("9"), "raw_sha256": _digest("a"), "raw_size": 123,
        "file_device": 0, "file_inode": 101, "file_mode": 0o600, "file_nlink": 1,
        "file_mtime_ns": 1_000_000, "file_ctime_ns": 1_000_001,
        "parent_device": 0, "parent_inode": 100,
    }
    payload.update(changes)
    payload["pin_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return parse_python_producer_admission_handoff_file_pin(payload)


def test_original_handoff_file_pin_is_bound_by_journal_digest() -> None:
    digest_only = _journal(native_execution_receipt_sha256=_digest("8"),
                           python_handoff_sha256=_digest("9"))
    pin = _file_pin()
    linked = _journal(native_execution_receipt_sha256=_digest("8"),
                      python_handoff_sha256=_digest("9"), python_handoff_file_pin=pin)
    assert linked.python_handoff_file_pin == pin
    assert linked.to_dict()["python_handoff_file_pin"] == pin.to_dict()
    assert parse_producer_bundle_publication_journal(linked.to_dict()) == linked
    assert linked.digest() != digest_only.digest()
    assert "python_handoff_file_pin" not in digest_only.to_dict()
    advancing = replace(linked, state="unknown", publication_phase="recovery_required",
                        journal_sha256=None)
    assert advancing.python_handoff_file_pin == pin
    assert advancing.digest() != linked.digest()


@pytest.mark.parametrize("field,value", [
    ("run_id", "run-other"), ("journal_id", "journal-other"),
    ("parent_task_id", "parent-other"), ("task_id", "task-other"),
    ("handoff_sha256", _digest("b")),
])
def test_journal_refuses_resigned_file_pin_identity_drift(field: str, value: str) -> None:
    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(native_execution_receipt_sha256=_digest("8"),
                 python_handoff_sha256=_digest("9"),
                 python_handoff_file_pin=_file_pin(**{field: value}))
    assert caught.value.code == "producer_bundle_publication_python_handoff_pin_mismatch"


def test_journal_pin_cannot_omit_handoff_link_or_adopt_tampered_pin() -> None:
    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(native_execution_receipt_sha256=_digest("8"), python_handoff_file_pin=_file_pin())
    assert caught.value.code == "producer_bundle_publication_python_handoff_pin_mismatch"
    pin = _file_pin()
    object.__setattr__(pin, "file_inode", 999)
    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(native_execution_receipt_sha256=_digest("8"),
                 python_handoff_sha256=_digest("9"), python_handoff_file_pin=pin)
    assert caught.value.code == "producer_bundle_publication_python_handoff_pin_invalid"


def test_journal_wire_pin_null_or_modified_metadata_refuses() -> None:
    journal = _journal(native_execution_receipt_sha256=_digest("8"),
                       python_handoff_sha256=_digest("9"), python_handoff_file_pin=_file_pin())
    null_pin = {**journal.to_dict(), "python_handoff_file_pin": None}
    with pytest.raises(ProducerBundlePublicationError) as caught:
        parse_producer_bundle_publication_journal(null_pin)
    assert caught.value.code == "producer_bundle_publication_python_handoff_pin_invalid"
    changed = journal.to_dict()
    changed["python_handoff_file_pin"]["file_inode"] += 1
    with pytest.raises(ProducerBundlePublicationError) as caught:
        parse_producer_bundle_publication_journal(changed)
    assert caught.value.code == "producer_bundle_publication_python_handoff_pin_invalid"


def test_mutated_journal_pin_cannot_invoke_a_caller_serialization_callback() -> None:
    journal = _journal(native_execution_receipt_sha256=_digest("8"),
                       python_handoff_sha256=_digest("9"), python_handoff_file_pin=_file_pin())
    calls = []

    class CallbackPin:
        def to_dict(self):
            calls.append("untrusted")
            pytest.fail("journal invoked an unvalidated pin callback")

    object.__setattr__(journal, "python_handoff_file_pin", CallbackPin())
    for operation in (journal.to_dict, journal.digest):
        with pytest.raises(ProducerBundlePublicationError) as caught:
            operation()
        assert caught.value.code == "producer_bundle_publication_python_handoff_pin_invalid"
    assert calls == []


@pytest.mark.parametrize("pin_kind", ["callback-mapping", "json-string"])
def test_journal_mapping_cannot_normalize_an_invalid_nested_pin(pin_kind: str) -> None:
    journal = _journal(native_execution_receipt_sha256=_digest("8"),
                       python_handoff_sha256=_digest("9"), python_handoff_file_pin=_file_pin())
    calls = []

    class CallbackMapping(dict):
        def items(self):
            calls.append("untrusted")
            pytest.fail("journal normalized a callback pin before validating its type")

    raw = journal.to_dict()
    raw["python_handoff_file_pin"] = (
        CallbackMapping(raw["python_handoff_file_pin"]) if pin_kind == "callback-mapping"
        else json.dumps(raw["python_handoff_file_pin"], sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(ProducerBundlePublicationError) as caught:
        parse_producer_bundle_publication_journal(raw)
    assert caught.value.code == "producer_bundle_publication_python_handoff_pin_invalid"
    assert calls == []


def test_rejects_digest_tampering_and_unknown_fields() -> None:
    journal = _journal(_candidate())
    tampered = journal.to_dict()
    tampered["journal_sha256"] = _digest("f")
    with pytest.raises(ProducerBundlePublicationError) as caught:
        parse_producer_bundle_publication_journal(tampered)
    assert caught.value.code == "producer_bundle_publication_journal_digest_mismatch"

    unknown = journal.to_dict()
    unknown["unexpected"] = True
    with pytest.raises(ProducerBundlePublicationError) as caught:
        parse_producer_bundle_publication_journal(unknown)
    assert caught.value.code == "producer_bundle_publication_schema_invalid"


def test_rejects_duplicate_ids_paths_and_invalid_state() -> None:
    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(_candidate(0), _candidate(0))
    assert caught.value.code == "producer_bundle_publication_candidate_duplicate"

    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(_candidate(), state="unknown", publication_phase="committed")
    assert caught.value.code == "producer_bundle_publication_state_phase_invalid"

    with pytest.raises(ProducerBundlePublicationError) as caught:
        ProducerBundlePublicationCandidate(
            "candidate", "bundle", _digest("a"), "candidate", 0, 0, 0, _digest("b")
        )
    assert caught.value.code == "producer_bundle_publication_parent_cycle"


def test_rejects_invalid_candidate_receipts_and_island_mapping() -> None:
    with pytest.raises(ProducerBundlePublicationError) as caught:
        ProducerBundlePublicationCandidate(
            "candidate", "bundle", _digest("a"), None, 0, 0, 0, "bad"
        )
    assert caught.value.code == "producer_bundle_publication_preparation_receipt_invalid"

    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(_candidate(), num_islands=0)
    assert caught.value.code == "producer_bundle_publication_num_islands_invalid"


def test_all_rejected_terminal_binds_receipts_and_unchanged_after_digests() -> None:
    candidate = _candidate(0)
    candidate = ProducerBundlePublicationCandidate(
        **{
            **candidate.to_dict(),
            "status": "rejected",
            "execution_receipt_sha256": _digest("8"),
            "evaluation_receipt_sha256": _digest("9"),
        }
    )
    journal = _journal(
        candidate,
        state="all_rejected",
        publication_phase="committed",
        terminal_marker_sha256=_digest("a"),
        archive_after_sha256=_digest("e"),
        state_after_sha256=_digest("f"),
    )
    assert journal.state == "all_rejected"
    assert journal.archive_after_sha256 == journal.base_archive_sha256
    assert journal.state_after_sha256 == journal.base_state_sha256
    assert journal.candidates[0].status == "rejected"


def test_all_rejected_terminal_requires_both_native_receipts() -> None:
    with pytest.raises(ProducerBundlePublicationError) as caught:
        _journal(
            ProducerBundlePublicationCandidate(
                **{**_candidate(0).to_dict(), "status": "rejected"}
            ),
            state="all_rejected",
            publication_phase="committed",
            terminal_marker_sha256=_digest("a"),
            archive_after_sha256=_digest("e"),
            state_after_sha256=_digest("f"),
        )
    assert caught.value.code == "producer_bundle_publication_terminal_evidence_invalid"


def test_rejects_duplicate_json_keys_and_oversized_files(tmp_path: Path) -> None:
    journal = _journal(_candidate()).to_dict()
    encoded = json.dumps(journal, separators=(",", ":"))
    duplicate = encoded[:-1] + ',"state":"prepared"}'
    path = tmp_path / "duplicate.json"
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ProducerBundlePublicationError):
        parse_producer_bundle_publication_journal(path)

    path.write_bytes(b"{" + b"x" * (256 * 1024) + b"}")
    with pytest.raises(ProducerBundlePublicationError) as caught:
        parse_producer_bundle_publication_journal(path)
    assert caught.value.code in {
        "producer_bundle_publication_too_large", "producer_bundle_publication_journal_invalid",
    }
