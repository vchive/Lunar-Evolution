"""Private provider-free BRS rejection C1/P/C2 composition.

This module is deliberately an adapter, rather than a new lineage owner.  A
future BRS owner can hold the private original ``RSIPublicationLineage``
continuation while it is still in its running/started scope; this adapter binds
that continuation to the selected BRS owner before allowing the existing
create-only P write and C2 acknowledgement.  It never discovers an owner,
refreshes a head, settles an episode, or enables public native BRS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .rsi_learning import RSILearningError
from .rsi_native_rejection import (
    NativeRSIRejectionEvidence,
    NativeRSIRejectionFilePin,
    RejectionLineageC1Binding,
    persist_native_rsi_rejection_provenance,
    read_native_rsi_rejection_provenance,
)
from .rsi_publication_lineage import RSIPublicationLineage


class BRSRejectionCompositionError(RSILearningError):
    """Fixed refusal codes for the private BRS C1/P/C2 composition seam."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_python_brs_rejection_" + code
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise BRSRejectionCompositionError(code)


@dataclass(frozen=True, slots=True)
class BRSRejectionCompositionResult:
    """Detached readback of one owner-bound C1/P/C2 continuation."""

    lineage: RejectionLineageC1Binding
    evidence: NativeRSIRejectionEvidence
    provenance_sha256: str
    file_pin: NativeRSIRejectionFilePin


def _policy_disabled(owner: object) -> None:
    try:
        raw = object.__getattribute__(owner, "_policy_bytes")
        if type(raw) is not bytes:
            _fail("policy_invalid")
        policy = json.loads(raw)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BRSRejectionCompositionError("policy_invalid") from exc
    if (type(policy) is not dict or policy.get("protocol") != "lunar-rsi-brs-lineage-checkpoint-v1"
            or policy.get("mode") != "brs" or policy.get("max_workers") != 1
            or policy.get("online_publication") is not False
            or policy.get("production_admission") is not False):
        _fail("policy_invalid")


def _owner_identity(owner: object) -> None:
    """Require the original exact BRS owner before reading caller DTOs."""
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    if type(owner) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    _policy_disabled(owner)
    try:
        run_id = object.__getattribute__(owner, "_run_id")
        request = object.__getattribute__(owner, "_request")
        plan = object.__getattribute__(owner, "_plan")
        ledger = object.__getattribute__(owner, "_ledger")
        workspace = object.__getattribute__(owner, "_workspace")
        head = object.__getattribute__(owner, "_head")
        state = object.__getattribute__(owner, "_state")
        phase = object.__getattribute__(owner, "_phase")
        gateway = object.__getattribute__(owner, "_gateway")
    except AttributeError as exc:
        raise BRSRejectionCompositionError("owner_invalid") from exc
    from .rsi_gateway import SolverRequest
    from .rsi_native_plan import NativeRSIExecutionPlan

    if (type(run_id) is not str or type(request) is not SolverRequest
            or type(plan) is not NativeRSIExecutionPlan or ledger is None
            or type(workspace) not in {Path, type(Path())} or type(head) is not str
            or not isinstance(state, dict) or phase not in {"rejected", "rejected-provenance"}
            or gateway is None):
        _fail("owner_invalid")
    # A rejected continuation must not have a published head or an in-memory
    # population/memory promotion.  The owner remains the only CAS authority.
    wire = state.get("producer_publication_lineage")
    if type(wire) is not dict or wire.get("head") is not None:
        _fail("published_head_invalid")


def _lineage_identity(owner: object, lineage_owner: object, binding: RejectionLineageC1Binding) -> None:
    """Bind BRS and original-lineage identities before P is created."""
    if type(lineage_owner) is not RSIPublicationLineage:
        _fail("lineage_owner_invalid")
    from .rsi_native_rejection import _dto_shape

    if type(binding) is not RejectionLineageC1Binding:
        _fail("c1_invalid")
    try:
        _dto_shape(binding)
    except Exception as exc:
        raise BRSRejectionCompositionError("c1_invalid") from exc
    try:
        pairs = (
            (owner._run_id, lineage_owner._run_id),
            (owner._request.episode_id, lineage_owner._request.episode_id),
            (owner._plan.journal_id, lineage_owner._plan.journal_id),
            (owner._ledger, lineage_owner._ledger),
            (owner._gateway, lineage_owner._gateway),
            (Path(owner._workspace).expanduser().absolute(), Path(lineage_owner._workspace).expanduser().absolute()),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise BRSRejectionCompositionError("owner_binding_invalid") from exc
    if any(left != right for left, right in pairs):
        _fail("owner_binding_invalid")
    if (binding.run_id != owner._run_id or binding.episode_id != owner._request.episode_id
            or binding.journal_id != owner._plan.journal_id or binding.checkpoint_sha256 != owner._head):
        _fail("head_binding_invalid")


def _require_evidence(owner: object, lineage_owner: object, evidence: object,
                      binding: RejectionLineageC1Binding) -> NativeRSIRejectionEvidence:
    from .rsi_native_rejection import _dto_shape

    if type(evidence) is not NativeRSIRejectionEvidence:
        _fail("evidence_invalid")
    try:
        _dto_shape(evidence)
        clean = NativeRSIRejectionEvidence.from_dict(evidence.to_dict())
    except Exception as exc:
        raise BRSRejectionCompositionError("evidence_invalid") from exc
    if (clean.provenance_sha256 is not None or clean.provenance_file_pin is not None
            or clean.lineage != binding or clean.plan != owner._plan or clean.claim != lineage_owner._claim
            or dict(clean.ledger_identity) != dict(lineage_owner._gateway._ledger_identity)):
        _fail("evidence_binding_invalid")
    if clean.rejected.journal_id != owner._plan.journal_id or clean.terminal.journal_id != owner._plan.journal_id:
        _fail("journal_binding_invalid")
    return clean


def _strict_file_pin(value: object) -> NativeRSIRejectionFilePin:
    """Reparse a pin only after an exact, callback-free shape inspection."""
    from .rsi_native_rejection import _dto_shape

    if type(value) is not NativeRSIRejectionFilePin:
        _fail("file_pin_invalid")
    try:
        _dto_shape(value)
        return NativeRSIRejectionFilePin.from_dict(value.to_dict())
    except Exception as exc:
        raise BRSRejectionCompositionError("file_pin_invalid") from exc


def _strict_readback(value: object) -> NativeRSIRejectionEvidence:
    """Shape-check a P readback before any caller-controlled DTO method is used.

    The native reader has already verified the provenance digest and file pin.
    Reconstructing the DTO here would repeat that cryptographic check and would
    make provider-free composition fixtures depend on a real inode.  The exact
    type and recursive shape gate still reject callback-bearing replacements
    before ``to_dict`` or any C2 call can observe them.
    """
    from .rsi_native_rejection import _dto_shape

    if type(value) is not NativeRSIRejectionEvidence:
        _fail("provenance_invalid")
    try:
        _dto_shape(value)
        return value
    except Exception as exc:
        raise BRSRejectionCompositionError("provenance_invalid") from exc


def compose_brs_rejection_c1_p_c2(
    owner: object,
    lineage_owner: object,
    evidence: NativeRSIRejectionEvidence,
) -> BRSRejectionCompositionResult:
    """Run the existing C1/P/C2 sequence under a strict private BRS adapter.

    ``lineage_owner`` is a separately held, original ``RSIPublicationLineage``
    continuation.  It is intentionally required explicitly: the adapter never
    reconstructs one from a checkpoint, latest row, mailbox response or file.
    The owner methods themselves retain/acknowledge the lineage CAS; this helper
    only composes the existing operations and the create-only provenance file.
    """
    _owner_identity(owner)
    if type(lineage_owner) is not RSIPublicationLineage:
        _fail("lineage_owner_invalid")
    try:
        # C1: read the original owner binding before any P path is touched.
        binding = RSIPublicationLineage.rejection_provenance_binding(lineage_owner)
    except Exception as exc:
        if isinstance(exc, BRSRejectionCompositionError):
            raise
        raise BRSRejectionCompositionError("c1_invalid") from exc
    if type(binding) is not RejectionLineageC1Binding:
        _fail("c1_invalid")
    _lineage_identity(owner, lineage_owner, binding)
    clean = _require_evidence(owner, lineage_owner, evidence, binding)
    batch = Path(owner._workspace).expanduser().absolute() / "evolution" / "producer-batches" / owner._plan.journal_id
    # The selected BRS owner and original lineage owner must still be captured
    # immediately before create-only P.  This prevents a callback from swapping
    # the owner/head after C1 while leaving a valid-looking evidence DTO.
    try:
        if owner._head != binding.checkpoint_sha256 or lineage_owner._head != binding.checkpoint_sha256:
            _fail("head_binding_invalid")
        digest, file_pin = persist_native_rsi_rejection_provenance(
            batch, clean, retained_bytes=binding.retained_bytes,
        )
        if type(digest) is not str or len(digest) != 64:
            _fail("provenance_invalid")
        file_pin = _strict_file_pin(file_pin)
        readback = _strict_readback(
            read_native_rsi_rejection_provenance(batch, expected_file_pin=file_pin),
        )
    except BRSRejectionCompositionError:
        raise
    except Exception as exc:
        raise BRSRejectionCompositionError("provenance_invalid") from exc
    if (readback.provenance_sha256 != digest or readback.provenance_file_pin != file_pin
            or readback.to_dict() != clean.to_dict()) or owner._head != binding.checkpoint_sha256:
        _fail("provenance_drift")
    # C2: existing owner CAS fills only the retained provenance association.
    try:
        RSIPublicationLineage.acknowledge_rejection_provenance(lineage_owner, readback, file_pin)
        acknowledged = _strict_file_pin(RSIPublicationLineage.rejection_provenance_file_pin(lineage_owner))
    except Exception as exc:
        if isinstance(exc, BRSRejectionCompositionError):
            raise
        raise BRSRejectionCompositionError("c2_invalid") from exc
    if acknowledged != file_pin:
        _fail("c2_invalid")
    return BRSRejectionCompositionResult(
        lineage=binding, evidence=readback, provenance_sha256=digest, file_pin=file_pin,
    )
