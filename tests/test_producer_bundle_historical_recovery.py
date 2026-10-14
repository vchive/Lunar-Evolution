"""Compatibility for the terminal split; no historical lineage is authorized here."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_bundle_recovery import _d, _journal, _plan, _workspace
from test_producer_bundle_recovery_retained import _attach_retained_evidence

from lunar_evolution import producer_bundle_recovery as recovery


def _digest(body: object) -> str:
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


def _save_json(path: Path, body: object) -> None:
    path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")


def _snapshot(root: Path) -> dict[Path, tuple[bytes, tuple[int, ...]]]:
    return {
        path.relative_to(root): (
            path.read_bytes(),
            tuple(getattr(path.lstat(), field) for field in (
                "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns",
            )),
        )
        for path in root.rglob("*") if path.is_file()
    }


@pytest.fixture(autouse=True)
def _forbid_process_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("process start forbidden"))


def _published_workspace(tmp_path: Path, *, retained: bool = False):
    """Advance the existing inert staged fixture through its original terminal wire."""
    plan = _plan()
    staged = _journal(plan)
    root = _workspace(tmp_path, plan, staged)
    source = _attach_retained_evidence(root, staged) if retained else None
    batch = root / "evolution/producer-batches" / staged.journal_id
    cid = staged.candidates[0].candidate_id
    admitted = replace(
        staged.candidates[0], execution_receipt_sha256=_d("8"),
        evaluation_receipt_sha256=_d("9"), publication_receipt_sha256=_d("c"), status="admitted",
    )
    publishing = replace(staged, candidates=(admitted,), state="publishing", journal_sha256=None)
    _save_json(batch / "journal.json", publishing.to_dict())
    final_root = root / "evolution/candidates" / cid
    final_root.parent.mkdir(parents=True)
    (batch / "stage/candidates" / cid).replace(final_root)
    for name in ("archive.jsonl", "state.json"):
        (batch / "stage" / name).replace(root / "evolution" / name)
    archive_sha = hashlib.sha256((root / "evolution/archive.jsonl").read_bytes()).hexdigest()
    state_sha = hashlib.sha256((root / "evolution/state.json").read_bytes()).hexdigest()
    manifest = json.loads((batch / "manifest.json").read_bytes())
    manifest.pop("manifest_sha256")
    manifest.update(journal_sha256=publishing.digest(), archive_after_sha256=archive_sha,
                    state_after_sha256=state_sha)
    manifest["manifest_sha256"] = _digest(manifest)
    _save_json(batch / "manifest.json", manifest)
    terminal = {
        "schema_version": "1", "protocol": "lunar-producer-bundle-publication-v1",
        "journal_id": staged.journal_id, "staged_journal_sha256": publishing.digest(),
        "manifest_sha256": manifest["manifest_sha256"], "archive_after_sha256": archive_sha,
        "state_after_sha256": state_sha, "status": "published",
    }
    terminal["terminal_marker_sha256"] = _digest(terminal)
    _save_json(batch / "terminal.json", terminal)
    final = replace(
        publishing, state="published", publication_phase="committed",
        terminal_marker_sha256=terminal["terminal_marker_sha256"],
        archive_after_sha256=archive_sha, state_after_sha256=state_sha, journal_sha256=None,
    )
    _save_json(batch / "journal.published.json", final.to_dict())
    return root, batch, plan, final, manifest["manifest_sha256"], source


def _replace_terminal(batch: Path, journal, **changes):
    terminal = json.loads((batch / "terminal.json").read_bytes())
    terminal.pop("terminal_marker_sha256")
    terminal.update(changes)
    terminal["terminal_marker_sha256"] = _digest(terminal)
    _save_json(batch / "terminal.json", terminal)
    changed = replace(journal, terminal_marker_sha256=terminal["terminal_marker_sha256"], journal_sha256=None)
    _save_json(batch / "journal.published.json", changed.to_dict())
    return changed


def test_original_published_recovery_is_read_only_after_terminal_split(tmp_path: Path) -> None:
    root, batch, plan, journal, manifest_sha, _source = _published_workspace(tmp_path)
    before = _snapshot(root)
    evidence = recovery._verify_terminal_batch_evidence(root, batch, journal, manifest_sha)
    result = recovery.resume_producer_bundle_publication(root, plan, journal)
    assert evidence.journal_id == journal.journal_id
    assert evidence.terminal_marker_sha256 == journal.terminal_marker_sha256
    assert evidence.archive_after_sha256 == journal.archive_after_sha256
    assert evidence.state_after_sha256 == journal.state_after_sha256
    assert result.status == "published"
    assert result.journal_sha256 == journal.digest()
    assert _snapshot(root) == before


@pytest.mark.parametrize("name,contents", [
    ("archive.jsonl", b'{"unverified_successor":true}\n'),
    ("state.json", b'{"strategy":"population","unverified_successor":true}\n'),
])
def test_immutable_terminal_does_not_authorize_current_head_drift(
    tmp_path: Path, name: str, contents: bytes,
) -> None:
    root, batch, plan, journal, manifest_sha, _source = _published_workspace(tmp_path)
    original = recovery._verify_terminal_batch_evidence(root, batch, journal, manifest_sha)
    (root / "evolution" / name).write_bytes(contents)
    before = _snapshot(root)
    assert recovery._verify_terminal_batch_evidence(root, batch, journal, manifest_sha) == original
    with pytest.raises(recovery.ProducerBundleRecoveryError, match="^producer_bundle_recovery_after_digest_mismatch$"):
        recovery.resume_producer_bundle_publication(root, plan, journal)
    assert _snapshot(root) == before


@pytest.mark.parametrize("field,value,code", [
    ("schema_version", "2", "terminal_invalid"),
    ("protocol", "another-protocol", "terminal_invalid"),
    ("status", "unknown", "terminal_invalid"),
    ("extra", True, "terminal_invalid"),
    ("journal_id", "foreign-batch", "terminal_mismatch"),
    ("staged_journal_sha256", _d("a"), "terminal_mismatch"),
    ("manifest_sha256", _d("b"), "terminal_mismatch"),
    ("archive_after_sha256", _d("c"), "terminal_mismatch"),
    ("state_after_sha256", _d("d"), "terminal_mismatch"),
    ("journal_sha256", _d("e"), "terminal_mismatch"),
])
def test_rehashed_terminal_cannot_change_original_batch_associations(
    tmp_path: Path, field: str, value: object, code: str,
) -> None:
    root, batch, plan, journal, _manifest_sha, _source = _published_workspace(tmp_path)
    changed = _replace_terminal(batch, journal, **{field: value})
    before = _snapshot(root)
    with pytest.raises(recovery.ProducerBundleRecoveryError, match=f"^producer_bundle_recovery_{code}$"):
        recovery.resume_producer_bundle_publication(root, plan, changed)
    assert _snapshot(root) == before


def test_equal_legacy_terminal_journal_alias_retains_original_compatibility(tmp_path: Path) -> None:
    root, batch, plan, journal, manifest_sha, _source = _published_workspace(tmp_path)
    terminal = json.loads((batch / "terminal.json").read_bytes())
    changed = _replace_terminal(batch, journal, journal_sha256=terminal["staged_journal_sha256"])
    before = _snapshot(root)
    evidence = recovery._verify_terminal_batch_evidence(root, batch, changed, manifest_sha)
    assert evidence.staged_journal_sha256 == terminal["staged_journal_sha256"]
    assert recovery.resume_producer_bundle_publication(root, plan, changed).status == "published"
    assert _snapshot(root) == before


def test_changed_terminal_self_digest_cannot_become_batch_evidence(tmp_path: Path) -> None:
    root, batch, plan, journal, _manifest_sha, _source = _published_workspace(tmp_path)
    terminal = json.loads((batch / "terminal.json").read_bytes())
    terminal["terminal_marker_sha256"] = _d("f")
    _save_json(batch / "terminal.json", terminal)
    before = _snapshot(root)
    with pytest.raises(recovery.ProducerBundleRecoveryError, match="^producer_bundle_recovery_terminal_digest_mismatch$"):
        recovery.resume_producer_bundle_publication(root, plan, journal)
    assert _snapshot(root) == before


def test_valid_terminal_cannot_replace_held_original_terminal_digest(tmp_path: Path) -> None:
    root, batch, plan, journal, _manifest_sha, _source = _published_workspace(tmp_path)
    terminal = json.loads((batch / "terminal.json").read_bytes())
    _replace_terminal(batch, journal, journal_sha256=terminal["staged_journal_sha256"])
    _save_json(batch / "journal.published.json", journal.to_dict())
    before = _snapshot(root)
    with pytest.raises(recovery.ProducerBundleRecoveryError, match="^producer_bundle_recovery_terminal_mismatch$"):
        recovery.resume_producer_bundle_publication(root, plan, journal)
    assert _snapshot(root) == before


@pytest.mark.parametrize("material", ["record.json", "receipt.json", "retained-source"])
def test_head_drift_does_not_hide_original_material_failure(tmp_path: Path, material: str) -> None:
    root, _batch, plan, journal, _manifest_sha, source = _published_workspace(tmp_path, retained=True)
    if material == "retained-source":
        assert source is not None
        source.write_bytes(b"altered retained source\n")
        code = "evidence_changed"
    else:
        (root / "evolution/candidates" / journal.candidates[0].candidate_id / material).write_bytes(b"{}\n")
        code = "evidence_mismatch"
    (root / "evolution/archive.jsonl").write_bytes(b"unverified successor\n")
    before = _snapshot(root)
    with pytest.raises(recovery.ProducerBundleRecoveryError, match=f"^producer_bundle_recovery_{code}$"):
        recovery.resume_producer_bundle_publication(root, plan, journal)
    assert _snapshot(root) == before


def test_unknown_marker_still_precedes_terminal_and_current_head_checks(tmp_path: Path) -> None:
    root, _batch, plan, journal, manifest_sha, _source = _published_workspace(tmp_path)
    marker = {
        "schema_version": "1", "protocol": "lunar-producer-bundle-publication-v1",
        "journal_id": journal.journal_id, "journal_sha256": journal.digest(),
        "manifest_sha256": manifest_sha, "status": "unknown",
    }
    marker["marker_sha256"] = _digest(marker)
    _save_json(root / "evolution/producer-publication.json", marker)
    (root / "evolution/archive.jsonl").write_bytes(b"unverified successor\n")
    before = _snapshot(root)
    with pytest.raises(recovery.ProducerBundleRecoveryError, match="^producer_bundle_recovery_unknown_terminal$"):
        recovery.resume_producer_bundle_publication(root, plan, journal)
    assert _snapshot(root) == before
