from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_producer_process import _fixture

from lunar_evolution.native_trusted_cleanup import (
    NativeTrustedCleanupError,
    persist_native_trusted_cleanup,
    recover_native_trusted_cleanup,
)
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_process import _digest_without


def _cleanup() -> ProcessCleanupResult:
    return ProcessCleanupResult(
        label="native-bootstrap",
        pid=2001,
        pgid=2001,
        status=ProcessCleanupStatus.CLEANED,
        term_sent=True,
        kill_sent=False,
        alive_after=False,
    )


def test_cleanup_sidecar_is_create_only_and_terminal_bound(tmp_path: Path) -> None:
    _producer_root, intent, _attestation = _fixture(tmp_path, mode="success")
    batch = tmp_path / "evolution/producer-batches" / intent.journal_id
    batch.mkdir(parents=True, exist_ok=True)
    record = persist_native_trusted_cleanup(
        tmp_path,
        intent=intent,
        registration_sha256="a" * 64,
        deadline_sha256="b" * 64,
        cleanup=_cleanup(),
    )
    assert record["publication_eligible"] is False
    assert record["cleanup_sha256"] == _digest_without(record, "cleanup_sha256")
    terminal = {
        "registration_sha256": "a" * 64,
        "deadline_sha256": "b" * 64,
        "pid": 2001,
        "pgid": 2001,
        "cleanup_status": "cleaned",
        "process_status": "exited_zero",
    }
    assert recover_native_trusted_cleanup(tmp_path, intent=intent, terminal=terminal) == record
    with pytest.raises(NativeTrustedCleanupError) as conflict:
        persist_native_trusted_cleanup(
            tmp_path,
            intent=intent,
            registration_sha256="a" * 64,
            deadline_sha256="b" * 64,
            cleanup=ProcessCleanupResult(
                label="native-bootstrap", pid=2001, pgid=2001,
                status=ProcessCleanupStatus.ALREADY_EXITED,
            ),
        )
    assert conflict.value.code == "native_trusted_cleanup_write_unknown"


def test_cleanup_sidecar_rejects_terminal_rebinding_or_tamper(tmp_path: Path) -> None:
    _producer_root, intent, _attestation = _fixture(tmp_path, mode="success")
    batch = tmp_path / "evolution/producer-batches" / intent.journal_id
    batch.mkdir(parents=True, exist_ok=True)
    persist_native_trusted_cleanup(
        tmp_path,
        intent=intent,
        registration_sha256="a" * 64,
        deadline_sha256="b" * 64,
        cleanup=_cleanup(),
    )
    terminal = {
        "registration_sha256": "c" * 64,
        "deadline_sha256": "b" * 64,
        "pid": 2001,
        "pgid": 2001,
        "cleanup_status": "cleaned",
        "process_status": "exited_zero",
    }
    with pytest.raises(NativeTrustedCleanupError) as mismatch:
        recover_native_trusted_cleanup(tmp_path, intent=intent, terminal=terminal)
    assert mismatch.value.code == "native_trusted_cleanup_terminal_mismatch"
    path = batch / "native-trusted-cleanup.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["cleanup_status"] = "already_exited"
    path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(NativeTrustedCleanupError) as tamper:
        recover_native_trusted_cleanup(
            tmp_path,
            intent=intent,
            terminal={**terminal, "registration_sha256": "a" * 64},
        )
    assert tamper.value.code == "native_trusted_cleanup_invalid"
