"""Provider-free controller stage for a single fresh acceptance campaign.

This is the durable launch gate, not the native solve runner.  It reserves one
campaign, revalidates the retained admission against remote main, and publishes
one create-only attempt claim.  Failures leave any reserved campaign untouched.
"""
from __future__ import annotations

import os
from typing import Any

from .acceptance_attempt_gate import (
    AcceptanceAttemptGateError,
    claim_acceptance_attempt,
    verify_acceptance_attempt_claim,
)
from .acceptance_launch import prepare_acceptance_campaign, revalidate_acceptance_campaign


def stage_acceptance_attempt(
    registration_path: str | os.PathLike[str],
    seal_path: str | os.PathLike[str],
    *,
    checkout_root: str | os.PathLike[str],
    campaign_parent: str | os.PathLike[str],
) -> dict[str, Any]:
    """Reserve, revalidate, and claim exactly one provider-free attempt.

    The caller receives the persisted claim.  A failure after reservation never
    permits this campaign root to be reused; a fresh registration and root are
    required for another attempt.  No provider, producer, or evaluator is called.
    """
    prepared = prepare_acceptance_campaign(
        registration_path, seal_path,
        checkout_root=checkout_root, campaign_parent=campaign_parent,
    )
    ready = revalidate_acceptance_campaign(
        registration_path, seal_path,
        checkout_root=checkout_root, campaign_parent=campaign_parent,
    )
    if ready["admission"] != prepared:
        raise AcceptanceAttemptGateError("attempt_admission_mismatch")
    claim = claim_acceptance_attempt(ready, campaign_parent=campaign_parent)
    return verify_acceptance_attempt_claim(claim, campaign_parent=campaign_parent)


__all__ = ["stage_acceptance_attempt"]
