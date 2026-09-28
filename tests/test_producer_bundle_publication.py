from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationError,
    build_producer_bundle_publication_journal,
    parse_producer_bundle_publication_journal,
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
    assert parse_producer_bundle_publication_journal(journal.to_dict()).to_dict() == journal.to_dict()
    path = tmp_path / "journal.json"
    path.write_text(json.dumps(journal.to_dict()), encoding="utf-8")
    assert parse_producer_bundle_publication_journal(path).digest() == journal.digest()


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
