"""Pure detached owner/worker handoff pins for the first native BRS child.

The handoff is an in-memory value only. Creating or validating it never accesses a
controller, ledger, workspace, file, process, callback, or admission channel. A future
owner integration must atomically consume the nonce under its existing owner lock.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from threading import get_ident
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json
from .rsi_python_brs_child_policy import (
    BRSChildPolicyError,
    BRSNativeChildPreflight,
    BRSNativeChildSelection,
)

HANDOFF_PROTOCOL = "lunar-rsi-python-brs-selected-child-handoff-v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
class BRSChildHandoffError(BRSChildPolicyError):
    """Stable refusal raised by the detached handoff constructor and gate."""

    def __init__(self, code: str) -> None:
        super().__init__("handoff_" + code)


def _fail(code: str) -> NoReturn:
    raise BRSChildHandoffError(code)


def _identity(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(f"{field}_invalid")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(f"{field}_invalid")
    return value


def _int(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{field}_invalid")
    return value


def _selection_digest(selection: BRSNativeChildSelection) -> str:
    return hashlib.sha256(canonical_json(selection.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class BRSChildHandoffContext:
    """Caller-supplied current pins; contains only immutable IDs and fingerprints."""

    controller_id: str
    ledger_id: str
    workspace_id: str
    sidecar_id: str
    owner_thread_id: int
    head_sha256: str
    state_sha256: str
    source_sha256: str
    policy_sha256: str
    execution_control_sha256: str
    max_workers: int = 1

    def __post_init__(self) -> None:
        for field in ("controller_id", "ledger_id", "workspace_id", "sidecar_id"):
            _identity(getattr(self, field), field)
        _int(self.owner_thread_id, "owner_thread_id", minimum=1)
        for field in (
            "head_sha256", "state_sha256", "source_sha256", "policy_sha256",
            "execution_control_sha256",
        ):
            _digest(getattr(self, field), field)
        if type(self.max_workers) is not int or self.max_workers != 1:
            _fail("max_workers_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "controller_id": self.controller_id,
            "ledger_id": self.ledger_id,
            "workspace_id": self.workspace_id,
            "sidecar_id": self.sidecar_id,
            "owner_thread_id": self.owner_thread_id,
            "head_sha256": self.head_sha256,
            "state_sha256": self.state_sha256,
            "source_sha256": self.source_sha256,
            "policy_sha256": self.policy_sha256,
            "execution_control_sha256": self.execution_control_sha256,
            "max_workers": self.max_workers,
        }


@dataclass(frozen=True, slots=True)
class BRSSelectedChildHandoff:
    """Canonical detached identity for one selected child; not a dispatch API."""

    run_id: str
    wave: int
    ordinal: int
    episode_id: str
    request_sha256: str
    root_snapshot_sha256: str
    selection_sha256: str
    controller_id: str
    ledger_id: str
    workspace_id: str
    sidecar_id: str
    owner_thread_id: int
    head_sha256: str
    state_sha256: str
    source_sha256: str
    policy_sha256: str
    execution_control_sha256: str
    max_workers: int
    lease_nonce: str
    protocol: str = HANDOFF_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != HANDOFF_PROTOCOL:
            _fail("protocol_invalid")
        _identity(self.run_id, "run_id")
        _int(self.wave, "wave")
        _int(self.ordinal, "ordinal")
        _identity(self.episode_id, "episode_id")
        if self.episode_id != f"{self.run_id}-practice-{self.wave}-{self.ordinal}":
            _fail("episode_identity_invalid")
        for field in (
            "request_sha256", "root_snapshot_sha256", "selection_sha256", "head_sha256",
            "state_sha256", "source_sha256", "policy_sha256", "execution_control_sha256",
        ):
            _digest(getattr(self, field), field)
        for field in ("controller_id", "ledger_id", "workspace_id", "sidecar_id"):
            _identity(getattr(self, field), field)
        _int(self.owner_thread_id, "owner_thread_id", minimum=1)
        if type(self.max_workers) is not int or self.max_workers != 1:
            _fail("max_workers_invalid")
        if type(self.lease_nonce) is not str or _NONCE.fullmatch(self.lease_nonce) is None:
            _fail("lease_nonce_invalid")

    @classmethod
    def from_selection(
        cls,
        selection: BRSNativeChildSelection,
        context: BRSChildHandoffContext,
        *,
        lease_nonce: str | None = None,
    ) -> BRSSelectedChildHandoff:
        """Capture an already preflighted selection and immutable current pins."""
        if type(selection) is not BRSNativeChildSelection or selection.authority is not False:
            _fail("selection_invalid")
        if type(context) is not BRSChildHandoffContext:
            _fail("context_invalid")
        nonce = secrets.token_urlsafe(24) if lease_nonce is None else lease_nonce
        return cls(
            run_id=selection.run_id,
            wave=selection.wave,
            ordinal=selection.ordinal,
            episode_id=selection.episode_id,
            request_sha256=selection.request_sha256,
            root_snapshot_sha256=selection.root_snapshot_sha256,
            selection_sha256=_selection_digest(selection),
            **context.to_dict(),
            lease_nonce=nonce,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "run_id": self.run_id,
            "wave": self.wave,
            "ordinal": self.ordinal,
            "episode_id": self.episode_id,
            "request_sha256": self.request_sha256,
            "root_snapshot_sha256": self.root_snapshot_sha256,
            "selection_sha256": self.selection_sha256,
            "controller_id": self.controller_id,
            "ledger_id": self.ledger_id,
            "workspace_id": self.workspace_id,
            "sidecar_id": self.sidecar_id,
            "owner_thread_id": self.owner_thread_id,
            "head_sha256": self.head_sha256,
            "state_sha256": self.state_sha256,
            "source_sha256": self.source_sha256,
            "policy_sha256": self.policy_sha256,
            "execution_control_sha256": self.execution_control_sha256,
            "max_workers": self.max_workers,
            "lease_nonce": self.lease_nonce,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def validate_brs_child_handoff(
    handoff: BRSSelectedChildHandoff,
    preflight: BRSNativeChildPreflight,
    current: BRSChildHandoffContext,
    *,
    consumed_nonces: tuple[str, ...] = (),
) -> str:
    """Purely gate a handoff against the original preflight and current owner pins.

    The caller must atomically record ``handoff.lease_nonce`` as consumed immediately
    after this succeeds and before any worker effect. This function intentionally does
    not own mutable state or controller locks, so it cannot by itself provide exactly-
    once dispatch under concurrent callers.
    """
    if type(handoff) is not BRSSelectedChildHandoff:
        _fail("shape_invalid")
    if type(preflight) is not BRSNativeChildPreflight:
        _fail("preflight_invalid")
    if type(current) is not BRSChildHandoffContext:
        _fail("context_invalid")
    if get_ident() != handoff.owner_thread_id:
        _fail("owner_thread_drift")
    if type(consumed_nonces) is not tuple or any(type(item) is not str for item in consumed_nonces):
        _fail("nonce_state_invalid")
    if handoff.lease_nonce in consumed_nonces:
        _fail("nonce_replayed")
    try:
        handoff = BRSSelectedChildHandoff(**handoff.to_dict())
        current = BRSChildHandoffContext(**current.to_dict())
        preflight = BRSNativeChildPreflight.from_wire(preflight.to_dict())
    except (BRSChildPolicyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, BRSChildHandoffError):
            raise
        raise BRSChildHandoffError("shape_invalid") from exc
    if preflight.max_workers != 1 or current.max_workers != 1 or handoff.max_workers != 1:
        _fail("max_workers_invalid")
    selection = preflight.select_next_pending()
    if selection is None:
        _fail("selection_exhausted")
    if (
        handoff.run_id != selection.run_id
        or handoff.wave != selection.wave
        or handoff.ordinal != selection.ordinal
        or handoff.episode_id != selection.episode_id
        or handoff.request_sha256 != selection.request_sha256
        or handoff.root_snapshot_sha256 != selection.root_snapshot_sha256
        or handoff.selection_sha256 != _selection_digest(selection)
    ):
        _fail("selection_drift")
    captured = {
        key: getattr(handoff, key)
        for key in (
            "controller_id", "ledger_id", "workspace_id", "sidecar_id", "owner_thread_id",
            "head_sha256", "state_sha256", "source_sha256", "policy_sha256",
            "execution_control_sha256", "max_workers",
        )
    }
    if captured != current.to_dict():
        _fail("owner_or_fingerprint_drift")
    # Re-serialize from strict primitive fields to establish one canonical form.
    if type(handoff.canonical_bytes) is not bytes or len(handoff.canonical_bytes) > 4096:
        _fail("canonical_wire_invalid")
    return handoff.sha256


__all__ = [
    "HANDOFF_PROTOCOL",
    "BRSChildHandoffContext",
    "BRSSelectedChildHandoff",
    "validate_brs_child_handoff",
]
