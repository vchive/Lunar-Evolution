from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lunar_evolution.native_trusted_streams import (
    NativeTrustedStreamError,
    NativeTrustedStreamObservation,
    persist_native_trusted_stream_capture,
    recover_native_trusted_stream_capture,
    start_native_trusted_stream_capture,
)
from lunar_evolution.producer_process import ProducerStreamEvidence


def test_capture_drains_both_streams_after_one_overflows() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'o' * 200000); os.write(2, b'e' * 200000)",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    capture = start_native_trusted_stream_capture(
        process, limit=1024, deadline=time.monotonic() + 5,
    )
    assert process.wait(timeout=5) == 0
    observed = capture.finish(deadline=time.monotonic() + 5)
    assert observed.complete is True
    for evidence, byte in ((observed.stdout_evidence, b"o"), (observed.stderr_evidence, b"e")):
        assert evidence.bytes_observed == 1025
        assert evidence.truncated is True
        assert evidence.capture_status == "limit_exceeded"
        assert evidence.sha256 == hashlib.sha256(byte * 1024).hexdigest()


def test_capture_sidecar_is_create_only_and_terminal_bound(tmp_path: Path) -> None:
    from test_native_trusted_attempt import _attempt

    _workspace, _producer_root, intent, attestation, _artifact, batch = _attempt(tmp_path)
    empty = ProducerStreamEvidence(
        stream="stdout", bytes_observed=0, sha256=hashlib.sha256(b"").hexdigest(),
        truncated=False, capture_status="complete",
    )
    observed = NativeTrustedStreamObservation(
        stdout_evidence=empty,
        stderr_evidence=ProducerStreamEvidence(
            stream="stderr", bytes_observed=0, sha256=hashlib.sha256(b"").hexdigest(),
            truncated=False, capture_status="complete",
        ),
        complete=True,
    )
    record = persist_native_trusted_stream_capture(
        batch,
        intent=intent,
        attestation_sha256=attestation.attestation_sha256,
        registration_sha256="a" * 64,
        deadline_sha256="b" * 64,
        observation=observed,
    )
    terminal = {
        "stream_capture_sha256": record["stream_capture_sha256"],
        "attestation_sha256": attestation.attestation_sha256,
        "registration_sha256": "a" * 64,
        "deadline_sha256": "b" * 64,
    }
    assert recover_native_trusted_stream_capture(batch, intent=intent, terminal=terminal) == record
    with pytest.raises(NativeTrustedStreamError, match="write_unknown"):
        persist_native_trusted_stream_capture(
            batch,
            intent=intent,
            attestation_sha256=attestation.attestation_sha256,
            registration_sha256="a" * 64,
            deadline_sha256="b" * 64,
            observation=observed,
        )
