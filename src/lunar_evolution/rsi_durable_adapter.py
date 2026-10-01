"""Opt-in durable local solver invocations without external completion authority."""

from __future__ import annotations

import json
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_callbacks import DurableCallbackJournal
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_identity import RSIIdentityError, component_fingerprint
from .rsi_learning import RSILearningError
from .rsi_store import RSILedger

_PROTOCOL = "lunar-rsi-durable-solver-v1"
_FAILURE_STATES = frozenset({"failed", "timed_out", "cancelled", "abandoned"})


class DurableSolverGatewayError(RSILearningError):
    """Fixed public refusal codes for local invocation replay and failure settlement."""


def _fail(code: str) -> None:
    raise DurableSolverGatewayError("rsi_durable_solver_" + code)


def _database_identity(path: Path) -> tuple[int, int]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("database_invalid")
        return info.st_dev, info.st_ino
    except OSError as exc:
        raise DurableSolverGatewayError("rsi_durable_solver_database_invalid") from exc


class DurableSolverGateway:
    """Persist an ordinary gateway's complete result before returning to the controller.

    This wrapper trusts the local delegate. Source/config fingerprints detect local drift;
    neither fingerprints nor reconciliation labels authenticate an external worker. A pending
    claim never retries, and explicit settlement cannot claim successful completion.
    """

    def __init__(self, gateway: Any, ledger: RSILedger, *, scope_id: str) -> None:
        if (not isinstance(ledger, RSILedger) or type(scope_id) is not str or not scope_id.strip()
                or len(scope_id) > 4096 or any(char in scope_id for char in "\x00\r\n")
                or not callable(getattr(gateway, "run", None))):
            _fail("configuration_invalid")
        self.gateway, self.ledger, self.scope_id = gateway, ledger, scope_id
        self._journal = DurableCallbackJournal(ledger)
        self._config = canonical_json(self.rsi_fingerprint_config(), maximum=128 * 1024)

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        try:
            gateway = component_fingerprint(self.gateway)
            run = component_fingerprint(self.gateway.run)
        except (RSIIdentityError, AttributeError) as exc:
            raise DurableSolverGatewayError("rsi_durable_solver_fingerprint_invalid") from exc
        identity = _database_identity(self.ledger.database)
        return {
            "protocol": _PROTOCOL, "scope_id": self.scope_id,
            "database": str(self.ledger.database), "device": identity[0], "inode": identity[1],
            "gateway_sha256": gateway, "run_sha256": run,
        }

    def _check(self) -> None:
        if self._journal.ledger is not self.ledger:
            _fail("configuration_drift")
        if canonical_json(self.rsi_fingerprint_config(), maximum=128 * 1024) != self._config:
            _fail("fingerprint_drift")

    def _prepare(self, request: SolverRequest) -> tuple[SolverRequest, str, str, dict[str, Any]]:
        self._check()
        if not isinstance(request, SolverRequest):
            _fail("request_invalid")
        try:
            wire = json.loads(canonical_json(request.to_dict(), maximum=128 * 1024))
            # The delegate receives a separate deep copy from the binding held by the journal.
            frozen = SolverRequest.from_dict(json.loads(canonical_json(wire, maximum=128 * 1024)))
            if frozen != request:
                _fail("request_invalid")
        except (TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, DurableSolverGatewayError):
                raise
            raise DurableSolverGatewayError("rsi_durable_solver_request_invalid") from exc
        # RSI episode IDs are global in this ledger. A new caller scope must not create a
        # second execution claim for an episode whose first invocation is still uncertain.
        scope = _PROTOCOL
        callback = "episode:" + self._journal.digest({"episode_id": frozen.episode_id})
        binding = {"protocol": _PROTOCOL, "configuration": json.loads(self._config), "request": wire}
        return frozen, scope, callback, binding

    @staticmethod
    def _result(value: Mapping[str, Any], request: SolverRequest) -> SolverResult:
        try:
            result = SolverResult.from_dict(dict(value))
        except (TypeError, ValueError, RSILearningError) as exc:
            raise DurableSolverGatewayError("rsi_durable_solver_result_invalid") from exc
        if result.episode_id != request.episode_id or result.request_sha256 != request.digest():
            _fail("result_identity_drift")
        return result

    def inspect(self, request: SolverRequest) -> tuple[str, dict[str, Any]] | None:
        """Read the original claim/result with the same identity checks as invocation replay."""
        frozen, scope, callback, binding = self._prepare(request)
        checkpoint = self._journal.inspect(scope, callback)
        if checkpoint is not None:
            self._journal._binding(checkpoint[1], binding)
            if checkpoint[1]["status"] == "completed":
                self._result(checkpoint[1]["result"], frozen)
        self._check()
        return checkpoint

    def run(self, request: SolverRequest) -> SolverResult:
        frozen, scope, callback, binding = self._prepare(request)

        def check_request() -> None:
            self._check()
            if frozen.to_dict() != binding["request"]:
                _fail("request_drift")

        def call() -> dict[str, Any]:
            check_request()
            result = self.gateway.run(frozen)
            check_request()
            if not isinstance(result, SolverResult):
                _fail("result_invalid")
            return result.to_dict()

        def validate(value: Mapping[str, Any]) -> None:
            check_request()
            self._result(value, frozen)

        def before_call() -> None:
            check_request()
            if self.ledger.episode_result(frozen.episode_id) is not None:
                _fail("unclaimed_result")

        try:
            wire = self._journal.invoke(scope, callback, binding=binding, call=call, validate=validate,
                                        before_call=before_call)
        except RSILearningError as exc:
            if exc.code == "rsi_callback_reconcile_required":
                raise DurableSolverGatewayError("rsi_durable_solver_reconcile_required") from exc
            raise
        check_request()
        return self._publish(frozen, self._result(wire, frozen))

    def _publish(self, request: SolverRequest, result: SolverResult) -> SolverResult:
        self._check()
        saved = self.ledger.episode_result(request.episode_id)
        if saved is None:
            self.ledger.save_episode_result(request, result)
        elif saved != (request, result):
            _fail("result_publication_conflict")
        self._check()
        return result

    def restore_result(self, request: SolverRequest) -> SolverResult:
        """Publish only a complete saved invocation; never start a claim or call the gateway."""
        frozen, scope, callback, binding = self._prepare(request)
        checkpoint = self._journal.inspect(scope, callback)
        if checkpoint is None:
            _fail("result_missing")
        self._journal._binding(checkpoint[1], binding)
        if checkpoint[1]["status"] != "completed":
            _fail("reconcile_required")
        result = self._result(checkpoint[1]["result"], frozen)
        return self._publish(frozen, result)

    def reconcile(self, request: SolverRequest, *, expected_checkpoint_sha256: str,
                  result: SolverResult, evidence: Mapping[str, Any]) -> SolverResult:
        """Settle only a local failure; never infer successful completion from supplied hashes."""
        frozen, scope, callback, binding = self._prepare(request)
        if not isinstance(result, SolverResult):
            _fail("result_invalid")
        if result.status not in _FAILURE_STATES:
            _fail("success_reconciliation_forbidden")

        def validate(value: Mapping[str, Any]) -> None:
            self._check()
            if self._result(value, frozen).status not in _FAILURE_STATES:
                _fail("success_reconciliation_forbidden")

        wire = self._journal.reconcile(
            scope, callback, expected_checkpoint_sha256=expected_checkpoint_sha256,
            binding=binding, result=result.to_dict(), evidence=evidence, validate=validate,
        )
        self._check()
        return self._publish(frozen, self._result(wire, frozen))


__all__ = ["DurableSolverGateway", "DurableSolverGatewayError"]
