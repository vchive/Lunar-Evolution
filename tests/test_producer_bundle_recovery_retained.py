from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from test_producer_bundle_recovery import _journal, _plan, _workspace

from lunar_evolution.producer_bundle_recovery import (
    ProducerBundleRecoveryError,
    resume_producer_bundle_publication,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _attach_retained_evidence(root: Path, journal) -> Path:
    """Add a native evidence sidecar to the existing staged recovery fixture."""
    original = root / "evolution" / "retained" / "source.txt"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"native evidence\n")
    info = original.stat()
    evidence_payload = {
        "schema_version": "1",
        "protocol": "lunar-native-retained-evidence-v1",
        "entries": [{
            "path": "evolution/retained/source.txt",
            "kind": "file",
            "size": len(b"native evidence\n"),
            "sha256": hashlib.sha256(b"native evidence\n").hexdigest(),
            "device": info.st_dev,
            "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
        }],
    }
    evidence = {**evidence_payload, "evidence_sha256": _digest(evidence_payload)}
    batch = root / "evolution" / "producer-batches" / journal.journal_id
    cid = journal.candidates[0].candidate_id
    candidate_root = batch / "stage" / "candidates" / cid
    evidence_path = candidate_root / "native-evidence.json"
    evidence_bytes = json.dumps(evidence, sort_keys=True).encode()
    evidence_path.write_bytes(evidence_bytes)

    manifest_path = batch / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    item = manifest["files"][0]
    descriptor = {
        "path": "native-evidence.json",
        "size": len(evidence_bytes),
        "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
    }
    item["paths"].append(descriptor)
    item["retained_evidence"] = {
        "path": "native-evidence.json",
        "sha256": descriptor["sha256"],
        "evidence_sha256": evidence["evidence_sha256"],
    }
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = _digest(manifest)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    return original


def test_recovery_revalidates_retained_native_bytes_and_identity(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    root = _workspace(tmp_path, plan, journal)
    original = _attach_retained_evidence(root, journal)

    result = resume_producer_bundle_publication(root, plan, journal)
    assert result.status == "resume"
    assert "native-evidence.json" in result.verified_paths

    original.write_bytes(b"tampered evidence\n")
    with pytest.raises(ProducerBundleRecoveryError, match="^producer_bundle_recovery_evidence_changed$"):
        resume_producer_bundle_publication(root, plan, journal)


def test_recovery_rejects_retained_native_inode_replacement(tmp_path: Path) -> None:
    plan = _plan()
    journal = _journal(plan)
    root = _workspace(tmp_path, plan, journal)
    original = _attach_retained_evidence(root, journal)
    before = original.stat().st_ino

    replacement = original.with_suffix(".replacement")
    replacement.write_bytes(original.read_bytes())
    os.replace(replacement, original)
    assert original.stat().st_ino != before

    with pytest.raises(ProducerBundleRecoveryError, match="^producer_bundle_recovery_evidence_changed$"):
        resume_producer_bundle_publication(root, plan, journal)
