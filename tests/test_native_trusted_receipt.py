from __future__ import annotations

import sys
from pathlib import Path

import pytest
from test_native_trusted_attempt import _attempt

from lunar_evolution.native_trusted_attempt import run_native_trusted_attempt
from lunar_evolution.native_trusted_receipt import (
    NativeTrustedReceiptError,
    build_native_trusted_execution_receipt,
)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_receipt_projection_stays_fail_closed_without_output_evidence(tmp_path: Path) -> None:
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    result = run_native_trusted_attempt(
        workspace,
        producer_root=producer_root,
        intent=intent,
        attestation=attestation,
        artifact=artifact,
    )
    assert result.status == "recovery_required"
    with pytest.raises(NativeTrustedReceiptError) as failure:
        build_native_trusted_execution_receipt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code in {
        "native_trusted_receipt_output_invalid",
        "native_trusted_receipt_broker_incomplete",
        "native_trusted_receipt_cleanup_invalid",
    }
    assert not (batch / "execution-receipt.json").exists()
