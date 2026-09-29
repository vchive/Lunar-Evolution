"""Bounded clean-room verification for retained native RSI episodes.

``NativeIndependentVerifier`` owns the actual candidate/evaluator replay.  This module keeps
the P1 boundary explicit for callers that need to inspect the identity being re-opened before
admitting a memory item: all four host pins and the candidate source digest are recomputed from
the retained workspace, then the existing native verifier performs its isolated replay.

The verifier is deliberately local and bounded.  It does not discover an OS-wide dependency
closure, accept a solver score as authority, or publish memory itself.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import PracticeEpisode, RSILearningError, VerifierCheck, VerifierDecision
from .rsi_native import (
    NativeEvaluationProfile,
    NativeIndependentVerifier,
    _episode_root,
    _hash,
    _inspect,
    native_dependency_fingerprint,
    native_environment_fingerprint,
)

_PROTOCOL = "lunar-rsi-clean-room-v1"


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RSILearningError(f"rsi_clean_room_{name}_invalid")
    return value


@dataclass(frozen=True)
class CleanRoomFingerprints:
    """Recomputed identity for one retained candidate workspace."""

    source_sha256: str
    dependency_sha256: str
    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.source_sha256, "source_sha256"),
            (self.dependency_sha256, "dependency_sha256"),
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
        ):
            _digest(value, name)

    def to_dict(self) -> dict[str, str]:
        return {
            "protocol": _PROTOCOL,
            "source_sha256": self.source_sha256,
            "dependency_sha256": self.dependency_sha256,
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=4096)).hexdigest()


class CleanRoomRSIVerifier:
    """Reopen retained native evidence and perform one independent exact replay.

    The native verifier remains the authority for workspace and evaluator evidence.  This class
    adds a small public identity surface so callers can compare the recomputed pins with the
    immutable ``SolverRequest`` and ``SolverResult`` before allowing a memory commit.
    """

    def __init__(
        self,
        profile: NativeEvaluationProfile,
        workspace_root: str | Path,
        *,
        verification_root: str | Path | None = None,
    ) -> None:
        if not isinstance(profile, NativeEvaluationProfile):
            raise TypeError("profile must be NativeEvaluationProfile")
        self.profile = profile
        self.workspace_root = Path(workspace_root).absolute()
        self._delegate = NativeIndependentVerifier(
            profile,
            self.workspace_root,
            verification_root=verification_root,
        )

    def fingerprint(self) -> str:
        """Return the verifier identity used by RSI episode records."""

        return self._delegate.fingerprint()

    def reopen_fingerprints(
        self,
        episode: PracticeEpisode,
        request: SolverRequest,
        result: SolverResult,
    ) -> CleanRoomFingerprints:
        """Reopen and validate retained material, returning recomputed host pins.

        ``_inspect`` checks every retained file descriptor, source byte, admission binding and
        evaluator receipt.  The explicit values returned here are recomputed from the current
        host profile and parsed source bundle, so a caller never has to trust a digest-shaped
        value supplied by a solver.
        """

        root = _episode_root(self.workspace_root, request.episode_id, create=False)
        bundle, _sources, _evaluation = _inspect(self.profile, root, request, result)
        fingerprints = CleanRoomFingerprints(
            source_sha256=bundle.digest(),
            dependency_sha256=native_dependency_fingerprint(
                self.profile.dependency_root,
                self.profile.dependency_paths,
            ),
            contract_sha256=self.profile.contract.digest(),
            evaluator_sha256=self.profile.pipeline.evaluator.digest(),
            environment_sha256=native_environment_fingerprint(self.profile.pipeline),
        )
        self._check_identity(episode, request, result, fingerprints)
        return fingerprints

    @staticmethod
    def _check_identity(
        episode: PracticeEpisode,
        request: SolverRequest,
        result: SolverResult,
        fingerprints: CleanRoomFingerprints,
    ) -> None:
        expected = {
            "contract_sha256": request.contract_sha256,
            "evaluator_sha256": request.evaluator_sha256,
            "environment_sha256": request.environment_sha256,
        }
        actual = {
            "contract_sha256": fingerprints.contract_sha256,
            "evaluator_sha256": fingerprints.evaluator_sha256,
            "environment_sha256": fingerprints.environment_sha256,
        }
        if expected != actual:
            raise RSILearningError("rsi_clean_room_host_fingerprint_mismatch")
        if fingerprints.source_sha256 != result.candidate_source_sha256:
            raise RSILearningError("rsi_clean_room_source_fingerprint_mismatch")
        if fingerprints.dependency_sha256 != result.dependency_sha256:
            raise RSILearningError("rsi_clean_room_dependency_fingerprint_mismatch")
        if episode.candidate_source_sha256 not in {None, fingerprints.source_sha256}:
            raise RSILearningError("rsi_clean_room_episode_source_mismatch")
        if episode.dependency_sha256 not in {None, fingerprints.dependency_sha256}:
            raise RSILearningError("rsi_clean_room_episode_dependency_mismatch")

    @staticmethod
    def _augment(
        decision: VerifierDecision,
        fingerprints: CleanRoomFingerprints | None,
        *,
        outcome: str | None = None,
        diagnosis: str | None = None,
    ) -> VerifierDecision:
        checks = list(decision.checks)
        if fingerprints is not None:
            digest = fingerprints.digest()
            checks.extend(
                VerifierCheck(name, "pass", digest)
                for name in (
                    "source_fingerprint",
                    "dependency_fingerprint",
                    "contract_fingerprint",
                    "environment_fingerprint",
                )
            )
        target_outcome = outcome or decision.outcome
        target_diagnosis = diagnosis or decision.diagnosis
        evidence = {
            "protocol": _PROTOCOL,
            "decision": decision.to_dict(),
            "fingerprints": fingerprints.to_dict() if fingerprints is not None else None,
            "checks": [check.to_dict() for check in checks],
            "outcome": target_outcome,
        }
        receipt = _hash(evidence)
        return replace(
            decision,
            outcome=target_outcome,
            diagnosis=target_diagnosis,
            checks=tuple(checks),
            receipt_sha256=receipt,
            evidence_sha256=receipt,
        )

    def verify(
        self,
        episode: PracticeEpisode,
        request: SolverRequest,
        result: SolverResult,
    ) -> VerifierDecision:
        """Recompute pins, then delegate to the isolated native evaluator replay.

        All integrity ambiguity is non-admitting.  A malformed or changed workspace therefore
        produces ``unresolved`` rather than an exception that could be mistaken for approval.
        """

        fingerprints: CleanRoomFingerprints | None = None
        try:
            fingerprints = self.reopen_fingerprints(episode, request, result)
            decision = self._delegate.verify(episode, request, result)
            # Reopen once more after the independent replay.  This catches material changed by
            # a concurrent writer while the evaluator was running.
            after = self.reopen_fingerprints(episode, request, result)
            if after != fingerprints:
                raise RSILearningError("rsi_clean_room_material_changed")
            return self._augment(decision, fingerprints)
        except Exception as exc:  # noqa: BLE001 - fail closed at the verifier boundary
            if fingerprints is not None:
                check = VerifierCheck("clean_room_integrity", "unresolved", fingerprints.digest())
                base = VerifierDecision(
                    episode_id=episode.episode_id,
                    outcome="unresolved",
                    receipt_sha256=check.receipt_sha256,
                    diagnosis="clean-room evidence could not be verified",
                    verifier_fingerprint=self.fingerprint(),
                    checks=(check,),
                    contract_sha256=request.contract_sha256,
                    evaluator_sha256=request.evaluator_sha256,
                    environment_sha256=request.environment_sha256,
                    official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
                    evidence_sha256=check.receipt_sha256,
                    candidate_receipt_sha256=result.candidate_receipt_sha256,
                    execution_receipt_sha256=result.execution_receipt_sha256,
                )
                return self._augment(base, fingerprints, diagnosis=f"clean-room verification unresolved: {type(exc).__name__}")
            # Reuse the existing verifier's bounded unresolved shape for failures before the
            # retained workspace could be reopened.  It never grants memory authority.
            return self._delegate.verify(episode, request, result)


__all__ = ["CleanRoomFingerprints", "CleanRoomRSIVerifier"]
