"""Local durable callback results and explicit recovery of uncertain calls.

The journal records intent before invoking a callback. A started call without a
published result is never retried automatically: a trusted local operator must
provide a result and evidence bound to that exact intent. Evidence identifies
the operator's source; it does not authenticate a remote service or guarantee
distributed exactly-once execution.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError
from .rsi_store import RSILedger

_BINDING_BYTES = 512 * 1024
_RESULT_BYTES = 1024 * 1024
_EVIDENCE_BYTES = 128 * 1024
_STATE_FIELDS = frozenset({
    "schema_version", "kind", "scope_id", "callback_id", "status", "binding",
    "binding_sha256", "result", "result_sha256", "started_checkpoint_sha256",
    "reconciliation",
})


def _identifier(value: object) -> str:
    if (
        type(value) is not str or not value.strip() or len(value) > 4096
        or any(char in value for char in "\x00\r\n")
    ):
        raise RSILearningError("rsi_callback_identity_invalid")
    return value


def _hex_digest(value: object, *, code: str) -> str:
    if (
        type(value) is not str or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise RSILearningError(code)
    return value


def _json_shape(value: object) -> None:
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError("JSON object keys must be strings")
        for item in value.values():
            _json_shape(item)
    elif isinstance(value, list):
        for item in value:
            _json_shape(item)
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise ValueError("JSON value required")


def _clean(value: Mapping[str, Any], *, maximum: int, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RSILearningError(code)
    try:
        plain = dict(value)
        _json_shape(plain)
        return json.loads(canonical_json(plain, maximum=maximum))
    except Exception as exc:
        raise RSILearningError(code) from exc


class DurableCallbackJournal:
    """Use a private controller journal and lock for each scoped callback."""

    def __init__(self, ledger: RSILedger) -> None:
        self.ledger = ledger

    @staticmethod
    def digest(value: object) -> str:
        """Digest strict canonical JSON for constructing local recovery evidence."""
        try:
            if isinstance(value, Mapping):
                value = dict(value)
            _json_shape(value)
            return hashlib.sha256(canonical_json(value, maximum=2 * _RESULT_BYTES)).hexdigest()
        except Exception as exc:
            raise RSILearningError("rsi_callback_digest_invalid") from exc

    @staticmethod
    def identity(scope_id: str, callback_id: str) -> str:
        return "rsi-callback:" + DurableCallbackJournal.digest({
            "scope_id": _identifier(scope_id), "callback_id": _identifier(callback_id),
        })

    @classmethod
    def _evidence(
        cls, evidence: Mapping[str, Any], *, binding_sha256: str, result_sha256: str,
    ) -> dict[str, Any]:
        code = "rsi_callback_evidence_invalid"
        clean = _clean(evidence, maximum=_EVIDENCE_BYTES, code=code)
        source = clean.get("source")
        if (
            type(source) is not str or not source.strip() or len(source) > 4096
            or any(char in source for char in "\x00\r\n")
            or clean.get("binding_sha256") != binding_sha256
            or clean.get("result_sha256") != result_sha256
        ):
            raise RSILearningError(code)
        _hex_digest(clean.get("receipt_sha256"), code=code)
        return clean

    @staticmethod
    def validate_evidence(
        binding: Mapping[str, Any], result: Mapping[str, Any], evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate local evidence without writing or consuming a caller's budget."""
        clean_binding = _clean(binding, maximum=_BINDING_BYTES, code="rsi_callback_binding_invalid")
        clean_result = _clean(result, maximum=_RESULT_BYTES, code="rsi_callback_result_invalid")
        return DurableCallbackJournal._evidence(
            evidence, binding_sha256=DurableCallbackJournal.digest(clean_binding),
            result_sha256=DurableCallbackJournal.digest(clean_result),
        )

    def _state(self, state: Mapping[str, Any], scope_id: str, callback_id: str) -> None:
        code = "rsi_callback_checkpoint_corrupt"
        if (
            set(state) != _STATE_FIELDS or state["schema_version"] != "1"
            or state["kind"] != "durable_callback" or state["scope_id"] != scope_id
            or state["callback_id"] != callback_id or type(state["status"]) is not str
            or state["status"] not in {"started", "completed"}
        ):
            raise RSILearningError(code)
        binding = _clean(state["binding"], maximum=_BINDING_BYTES, code=code)
        if state["binding_sha256"] != self.digest(binding):
            raise RSILearningError(code)
        if state["status"] == "started":
            if any(state[key] is not None for key in (
                "result", "result_sha256", "started_checkpoint_sha256", "reconciliation",
            )):
                raise RSILearningError(code)
        else:
            result = _clean(state["result"], maximum=_RESULT_BYTES, code=code)
            if state["result_sha256"] != self.digest(result):
                raise RSILearningError(code)
            _hex_digest(state["started_checkpoint_sha256"], code=code)
            if state["reconciliation"] is not None:
                try:
                    self._evidence(
                        state["reconciliation"], binding_sha256=state["binding_sha256"],
                        result_sha256=state["result_sha256"],
                    )
                except RSILearningError as exc:
                    raise RSILearningError(code) from exc

    def inspect(self, scope_id: str, callback_id: str) -> tuple[str, dict[str, Any]] | None:
        """Read and verify the hash chain and the started-to-completed transition."""
        namespace = self.identity(scope_id, callback_id)
        history = self.ledger.controller_checkpoint_history(namespace)
        if not history:
            return None
        code = "rsi_callback_checkpoint_corrupt"
        if len(history) not in {1, 2}:
            raise RSILearningError(code)
        for _digest, state in history:
            self._state(state, scope_id, callback_id)
        started_digest, started = history[0]
        if started["status"] != "started":
            raise RSILearningError(code)
        if len(history) == 2:
            _completed_digest, completed = history[1]
            if (
                completed["status"] != "completed"
                or completed["started_checkpoint_sha256"] != started_digest
                or completed["binding_sha256"] != started["binding_sha256"]
                or completed["binding"] != started["binding"]
            ):
                raise RSILearningError(code)
        return history[-1]

    @staticmethod
    def _binding(state: Mapping[str, Any], binding: Mapping[str, Any]) -> None:
        if state["binding_sha256"] != DurableCallbackJournal.digest(binding):
            raise RSILearningError("rsi_callback_binding_drift")

    def invoke(
        self, scope_id: str, callback_id: str, *, binding: Mapping[str, Any],
        call: Callable[[], Mapping[str, Any]], validate: Callable[[Mapping[str, Any]], None],
        before_call: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        namespace = self.identity(scope_id, callback_id)
        clean_binding = _clean(binding, maximum=_BINDING_BYTES, code="rsi_callback_binding_invalid")
        with self.ledger.controller_lock(namespace):
            checkpoint = self.inspect(scope_id, callback_id)
            if checkpoint is not None:
                _digest, state = checkpoint
                self._binding(state, clean_binding)
                if state["status"] == "started":
                    raise RSILearningError("rsi_callback_reconcile_required")
                result = state["result"]
                validate(deepcopy(result))
                return result
            if before_call is not None:
                before_call()
            started = {
                "schema_version": "1", "kind": "durable_callback", "scope_id": scope_id,
                "callback_id": callback_id, "status": "started", "binding": clean_binding,
                "binding_sha256": self.digest(clean_binding), "result": None,
                "result_sha256": None, "started_checkpoint_sha256": None, "reconciliation": None,
            }
            started_digest = self.ledger.write_controller_checkpoint(
                namespace, started, expected_sha256=None,
            )
            result = _clean(call(), maximum=_RESULT_BYTES, code="rsi_callback_result_invalid")
            validate(deepcopy(result))
            completed = {
                **started, "status": "completed", "result": result,
                "result_sha256": self.digest(result), "started_checkpoint_sha256": started_digest,
            }
            self.ledger.write_controller_checkpoint(namespace, completed, expected_sha256=started_digest)
            return result

    def reconcile(
        self, scope_id: str, callback_id: str, *, expected_checkpoint_sha256: str,
        binding: Mapping[str, Any], result: Mapping[str, Any], evidence: Mapping[str, Any],
        validate: Callable[[Mapping[str, Any]], None],
    ) -> dict[str, Any]:
        namespace = self.identity(scope_id, callback_id)
        clean_binding = _clean(binding, maximum=_BINDING_BYTES, code="rsi_callback_binding_invalid")
        _hex_digest(expected_checkpoint_sha256, code="rsi_callback_checkpoint_conflict")
        with self.ledger.controller_lock(namespace):
            checkpoint = self.inspect(scope_id, callback_id)
            if checkpoint is None:
                raise RSILearningError("rsi_callback_not_started")
            current_digest, state = checkpoint
            self._binding(state, clean_binding)
            clean_result = _clean(result, maximum=_RESULT_BYTES, code="rsi_callback_result_invalid")
            clean_evidence = self._evidence(
                evidence, binding_sha256=self.digest(clean_binding), result_sha256=self.digest(clean_result),
            )
            if state["status"] == "completed":
                if expected_checkpoint_sha256 not in {current_digest, state["started_checkpoint_sha256"]}:
                    raise RSILearningError("rsi_callback_checkpoint_conflict")
                if (
                    state["reconciliation"] is None
                    or self.digest(state["reconciliation"]) != self.digest(clean_evidence)
                    or state["result_sha256"] != self.digest(clean_result)
                ):
                    raise RSILearningError("rsi_callback_reconcile_conflict")
                validate(deepcopy(clean_result))
                return clean_result
            if expected_checkpoint_sha256 != current_digest:
                raise RSILearningError("rsi_callback_checkpoint_conflict")
            validate(deepcopy(clean_result))
            completed = {
                **state, "status": "completed", "result": clean_result,
                "result_sha256": self.digest(clean_result), "started_checkpoint_sha256": current_digest,
                "reconciliation": clean_evidence,
            }
            self.ledger.write_controller_checkpoint(namespace, completed, expected_sha256=current_digest)
            return clean_result
