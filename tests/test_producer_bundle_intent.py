from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.producer_bundle_intent import (
    ProducerBundlePreparedIntentError,
    persist_producer_bundle_prepared_intent,
    verify_producer_bundle_prepared_intent,
)
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
    parse_producer_bundle_publication_journal,
)


def digest(letter: str) -> str:
    return letter * 64


def journal(**changes: object):
    candidate = ProducerBundlePublicationCandidate(
        candidate_id="candidate-0",
        bundle_id="bundle-0",
        bundle_sha256=digest("a"),
        parent_id=None,
        generation=0,
        iteration=0,
        island_id=0,
        preparation_receipt_sha256=digest("b"),
    )
    values = {
        "journal_id": "journal-0",
        "run_id": "run-0",
        "parent_task_id": "parent-0",
        "task_id": "task-0",
        "admission_sha256": digest("c"),
        "archive_prefix_sha256": digest("d"),
        "base_archive_sha256": digest("e"),
        "base_state_sha256": digest("f"),
        "contract_sha256": digest("0"),
        "evaluator_kind": "exact_harness",
        "evaluator_fingerprint": digest("1"),
        "runner_fingerprint": digest("2"),
        "dependency_sha256": digest("3"),
        "environment_sha256": digest("4"),
        "budget_sha256": digest("5"),
        "strategy": "population",
        "population_config_sha256": digest("6"),
        "num_islands": 1,
        "candidates": (candidate,),
    }
    values.update(changes)
    return build_producer_bundle_publication_journal(**values)


def workspace(tmp_path: Path, journal_id: str = "journal-0") -> Path:
    root = tmp_path / "workspace"
    (root / "evolution" / "producer-batches" / journal_id).mkdir(parents=True)
    return root


def test_persisted_intent_is_canonical_and_same_intent_is_idempotent(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = journal()

    first = persist_producer_bundle_prepared_intent(root, value)
    path = root / "evolution" / "producer-batches" / value.journal_id / "journal.prepared.json"
    before = path.stat()
    second = persist_producer_bundle_prepared_intent(root, value)
    assert first == second == value.digest()
    assert path.is_file()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_mtime_ns) == (
        after.st_dev, after.st_ino, after.st_mtime_ns,
    )
    assert stat.S_IMODE(after.st_mode) == 0o600
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed == value.to_dict()
    assert parse_producer_bundle_publication_journal(path).digest() == value.digest()
    assert verify_producer_bundle_prepared_intent(root, value) == first


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("run_id", "run-other"),
        ("parent_task_id", "parent-other"),
        ("task_id", "task-other"),
        ("budget_sha256", digest("7")),
        ("archive_prefix_sha256", digest("8")),
        ("base_archive_sha256", digest("8")),
        ("base_state_sha256", digest("8")),
        ("admission_sha256", digest("8")),
        ("evaluator_fingerprint", digest("8")),
    ],
)
def test_changed_prepared_intent_is_rejected_before_retry(
    tmp_path: Path, field: str, replacement: object,
) -> None:
    root = workspace(tmp_path)
    original = journal()
    persist_producer_bundle_prepared_intent(root, original)
    path = root / "evolution" / "producer-batches" / original.journal_id / "journal.prepared.json"
    before = path.read_bytes()

    changed = journal(**{field: replacement})
    for operation in (
        persist_producer_bundle_prepared_intent, verify_producer_bundle_prepared_intent,
    ):
        with pytest.raises(ProducerBundlePreparedIntentError) as caught:
            operation(root, changed)
        assert caught.value.code == "producer_bundle_prepared_intent_mismatch"
        assert path.read_bytes() == before


@pytest.mark.parametrize("started", ["native-drafts", "stage", "journal.json"])
def test_missing_intent_with_started_draft_requires_recovery(
    tmp_path: Path, started: str,
) -> None:
    root = workspace(tmp_path)
    batch = root / "evolution" / "producer-batches" / "journal-0"
    if started.endswith(".json"):
        (batch / started).write_bytes(b"{}")
    else:
        (batch / started).mkdir()

    with pytest.raises(ProducerBundlePreparedIntentError) as caught:
        verify_producer_bundle_prepared_intent(root, journal())
    assert caught.value.code == "producer_bundle_prepared_intent_recovery_required"
    assert not (batch / "journal.prepared.json").exists()

    with pytest.raises(ProducerBundlePreparedIntentError) as caught:
        persist_producer_bundle_prepared_intent(root, journal())
    assert caught.value.code == "producer_bundle_prepared_intent_recovery_required"


def test_missing_intent_without_started_work_is_distinct(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    with pytest.raises(ProducerBundlePreparedIntentError) as caught:
        verify_producer_bundle_prepared_intent(root, journal())
    assert caught.value.code == "producer_bundle_prepared_intent_missing"
    assert not (root / "evolution" / "producer-publication.lock").exists()


def test_tampered_intent_bytes_are_rejected(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = journal()
    persist_producer_bundle_prepared_intent(root, value)
    path = root / "evolution" / "producer-batches" / value.journal_id / "journal.prepared.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["task_id"] = "task-tampered"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(ProducerBundlePreparedIntentError) as caught:
        verify_producer_bundle_prepared_intent(root, value)
    assert caught.value.code == "producer_bundle_prepared_intent_mismatch"


def test_symlinked_intent_is_rejected_without_following(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = journal()
    path = root / "evolution" / "producer-batches" / value.journal_id / "journal.prepared.json"
    target = tmp_path / "outside.json"
    target.write_bytes(b"outside")
    path.symlink_to(target)
    for operation in (
        persist_producer_bundle_prepared_intent, verify_producer_bundle_prepared_intent,
    ):
        with pytest.raises(ProducerBundlePreparedIntentError) as caught:
            operation(root, value)
        assert caught.value.code == "producer_bundle_prepared_intent_path_invalid"
    assert target.read_bytes() == b"outside"


def test_hardlinked_intent_is_rejected(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = journal()
    persist_producer_bundle_prepared_intent(root, value)
    path = root / "evolution" / "producer-batches" / value.journal_id / "journal.prepared.json"
    os.link(path, tmp_path / "other-link")
    for operation in (
        persist_producer_bundle_prepared_intent, verify_producer_bundle_prepared_intent,
    ):
        with pytest.raises(ProducerBundlePreparedIntentError) as caught:
            operation(root, value)
        assert caught.value.code == "producer_bundle_prepared_intent_path_invalid"


@pytest.mark.parametrize("component", ["ancestor", "producer-batches", "journal-0"])
def test_symlinked_directory_is_rejected_without_writes(
    tmp_path: Path, component: str,
) -> None:
    root = workspace(tmp_path)
    if component == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(root.parent, target_is_directory=True)
        supplied = alias / root.name
        real_batch = root / "evolution" / "producer-batches" / "journal-0"
    else:
        selected = root / "evolution" / "producer-batches"
        if component == "journal-0":
            selected /= "journal-0"
        real = selected.with_name(selected.name + "-real")
        selected.rename(real)
        selected.symlink_to(real, target_is_directory=True)
        supplied = root
        real_batch = real / "journal-0" if component == "producer-batches" else real
    with pytest.raises(ProducerBundlePreparedIntentError):
        persist_producer_bundle_prepared_intent(supplied, journal())
    assert not (real_batch / "journal.prepared.json").exists()


def test_nonprepared_journal_is_rejected_without_intent_write(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    value = replace(journal(), state="executing", publication_phase="staged", journal_sha256=None)
    with pytest.raises(ProducerBundlePreparedIntentError) as caught:
        persist_producer_bundle_prepared_intent(root, value)
    assert caught.value.code == "producer_bundle_prepared_intent_journal_state_invalid"
    assert not (root / "evolution" / "producer-batches" / "journal-0" / "journal.prepared.json").exists()


def test_identical_intent_stays_valid_after_draft_creation_and_verify_is_read_only(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    value = journal()
    expected = persist_producer_bundle_prepared_intent(root, value)
    batch = root / "evolution" / "producer-batches" / value.journal_id
    (batch / "native-drafts").mkdir()
    assert persist_producer_bundle_prepared_intent(root, value) == expected
    lock = root / "evolution" / "producer-publication.lock"
    lock.unlink()
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert verify_producer_bundle_prepared_intent(root, value) == expected
    assert not lock.exists()
    assert before == {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_partial_write_is_retained_and_never_adopted_on_retry(tmp_path: Path, monkeypatch) -> None:
    from lunar_evolution import producer_bundle_intent

    root = workspace(tmp_path)
    value = journal()
    original_write = producer_bundle_intent.os.write
    calls = 0

    def interrupted_write(descriptor, content):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(descriptor, content[:12])
        raise OSError("injected incomplete write")

    with monkeypatch.context() as patch:
        patch.setattr(producer_bundle_intent.os, "write", interrupted_write)
        with pytest.raises(ProducerBundlePreparedIntentError) as caught:
            persist_producer_bundle_prepared_intent(root, value)
        assert caught.value.code == "producer_bundle_prepared_intent_write_failed"
    path = root / "evolution" / "producer-batches" / value.journal_id / "journal.prepared.json"
    partial = path.read_bytes()
    assert len(partial) == 12
    with pytest.raises(ProducerBundlePreparedIntentError) as caught:
        persist_producer_bundle_prepared_intent(root, value)
    assert caught.value.code == "producer_bundle_prepared_intent_mismatch"
    assert path.read_bytes() == partial
