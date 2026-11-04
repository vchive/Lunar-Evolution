"""Opt-in, fixed-field local request logs; never provider activity evidence."""

from __future__ import annotations

import json
import logging
import math
import re
import secrets
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from time import monotonic

from .http_transport import (
    MAX_BODY_BYTES,
    MAX_REQUEST_BYTES,
    _transport_error_category_value,
    normalize_transport_observation,
)

LOGGER_NAME = "lunar_evolution.model_requests"
_LOGGER = logging.getLogger(LOGGER_NAME)
_MAX_MS = 10**12
_PHASES = {"open_response", "read_response_body", "read_http_error_body"}
_REASONS = {
    "http_error", "transport_timeout", "transport_error", "invalid_json",
    "invalid_response_shape", "empty_response", "invalid_tool_calls",
    "invalid_model_identity", "invalid_usage", "local_error",
}
_WAIT_FIELDS = {
    "phase", "status", "last_milestone", "http_exchange_index",
    "milestone_elapsed_ms", "elapsed_ms",
}


def _integer(value, maximum=_MAX_MS):
    return type(value) is int and 0 <= value <= maximum


def _status(value):
    return value is None or type(value) is int and 100 <= value <= 599


def _tool_argument_decode_fields(value):
    """Project only owned, bounded storage; optional detail never owns the outcome."""
    try:
        from .runtime import (
            ToolArgumentDecodeObservation,
            ToolArgumentDecoderCategory,
            _tool_argument_decoder_category_value,
            _tool_argument_finish_reason_category_value,
        )

        if type(value) is not ToolArgumentDecodeObservation:
            return {}
        stored = object.__getattribute__(value, "__dict__")
        allowed = {"decoder_category", "argument_characters", "position", "line", "column",
                   "finish_reason_category"}
        if (type(stored) is not dict or len(stored) > len(allowed)
                or any(type(key) is not str for key in stored) or not set(stored) <= allowed):
            return {}
        fields = {}
        decoder = stored.get("decoder_category")
        category = _tool_argument_decoder_category_value(decoder)
        if category is not None:
            fields["decoder_category"] = category
        characters = stored.get("argument_characters")
        if _integer(characters, MAX_BODY_BYTES):
            fields["argument_characters"] = characters
            position, line, column = (stored.get(key) for key in ("position", "line", "column"))
            if (decoder is ToolArgumentDecoderCategory.JSON_SYNTAX
                    and _integer(position, characters)
                    and _integer(line, characters + 1) and line >= 1
                    and _integer(column, characters + 1) and column >= 1
                    and line + column <= position + 2
                    and (line != 1 or column == position + 1)):
                fields.update(position=position, line=line, column=column)
        finish = _tool_argument_finish_reason_category_value(stored.get("finish_reason_category"))
        if finish is not None:
            fields["finish_reason_category"] = finish
        return fields
    except Exception:  # noqa: BLE001 - malformed optional storage cannot suppress terminal evidence
        return {}


@contextmanager
def model_request_log_to_stderr(enabled: bool = False):
    """Scope a plain-message stderr handler to one explicitly selected CLI call."""
    if not enabled:
        yield
        return
    previous, handler = None, None
    try:
        previous = (_LOGGER.handlers[:], _LOGGER.level, _LOGGER.propagate, _LOGGER.disabled)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        _LOGGER.handlers = [handler]
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.propagate, _LOGGER.disabled = False, False
    except Exception:  # noqa: BLE001 - failed optional setup still executes the command
        _restore_logger(previous, handler)
        previous, handler = None, None
    try:
        yield
    finally:
        _restore_logger(previous, handler)


def _restore_logger(previous, handler):
    try:
        if previous is not None:
            _LOGGER.handlers, _LOGGER.level, _LOGGER.propagate, _LOGGER.disabled = previous
            _LOGGER.manager._clear_cache()
    except Exception:  # noqa: BLE001 - cleanup must preserve the adapter outcome
        previous = None
    if handler is not None:
        try:
            handler.close()
        except Exception:  # noqa: BLE001 - no arbitrary handler exception crosses CLI
            return


class ModelRequestLog:
    """Best-effort observation, with no request, response or arbitrary error text."""

    def __init__(self, *, timeout, bounded):
        self.enabled = False
        self.finished = False
        self.waits = 0
        try:
            if not _LOGGER.isEnabledFor(logging.INFO):
                return
            if type(bounded) is not bool:
                return
            if timeout is None:
                timeout_ms = None
            elif (type(timeout) in (int, float) and math.isfinite(timeout)
                  and 0 < timeout <= 86400):
                timeout_ms = math.floor(timeout * 1000)
            else:
                return
            request_id, started = secrets.token_hex(16), monotonic()
            if (type(request_id) is not str or re.fullmatch(r"[0-9a-f]{32}", request_id) is None
                    or type(started) not in (int, float) or not math.isfinite(started)):
                return
            self.started = started
            self.base = {"schema_version": "1", "request_id": request_id,
                         "request_timeout_ms": timeout_ms,
                         "transport": "bounded" if bounded else "direct"}
            self.enabled = True
            self._emit("model_request_started", elapsed_ms=0)
        except Exception:  # noqa: BLE001 - diagnostics cannot affect execution
            self.enabled = False

    def _elapsed(self):
        now = monotonic()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self.started:
            raise ValueError("invalid diagnostic clock")
        elapsed = math.floor((now - self.started) * 1000)
        if not _integer(elapsed):
            raise ValueError("invalid diagnostic elapsed time")
        return elapsed

    def _emit(self, event, **fields):
        if self.enabled:
            try:
                _LOGGER.info(json.dumps({**self.base, "event": event,
                                        "observed_utc": datetime.now(UTC).isoformat(),
                                        **fields},
                                        sort_keys=True, allow_nan=False, separators=(",", ":")))
            except Exception:  # noqa: BLE001 - never log arbitrary logger exception text
                return

    def wait(self, snapshot):
        if not self.enabled or self.finished or self.waits >= 2880:
            return
        try:
            if (type(snapshot) is not dict or any(type(key) is not str for key in snapshot)
                    or set(snapshot) != _WAIT_FIELDS):
                return
            phase, status = snapshot["phase"], snapshot["status"]
            if type(phase) is not str or phase not in _PHASES or not _status(status):
                return
            if (phase == "open_response") != (status is None):
                return
            elapsed = snapshot["elapsed_ms"]
            if not _integer(elapsed):
                return
            milestone = snapshot["last_milestone"]
            if milestone is None:
                if any(snapshot[key] is not None for key in ("http_exchange_index", "milestone_elapsed_ms")):
                    return
                waiting = None
            else:
                observed = normalize_transport_observation({
                    "last_milestone": milestone,
                    "http_exchange_index": snapshot["http_exchange_index"],
                    "elapsed_ms": snapshot["milestone_elapsed_ms"],
                })
                if observed["elapsed_ms"] > elapsed:
                    return
                waiting = elapsed - observed["elapsed_ms"]
            self.waits += 1
            self._emit("model_request_waiting", **snapshot, milestone_wait_ms=waiting)
        except Exception:  # noqa: BLE001 - malformed optional observations are omitted
            return

    def finish(self, outcome, *, failure=None, response_status=None):
        if not self.enabled or self.finished:
            return
        self.finished = True
        try:
            if type(outcome) is not str or outcome not in {"completed", "failed"}:
                return
            fields = {"elapsed_ms": self._elapsed()}
            if _status(response_status):
                fields["response_status"] = response_status
            if outcome == "failed":
                # Imported only after runtime has defined its concrete evidence classes.
                from .runtime import (
                    ModelFailureEvidence,
                    ModelRequestFailure,
                    ModelRequestFingerprint,
                    _tool_call_error_category_value,
                )

                reason = "local_error"
                if (type(failure) is ModelRequestFailure
                        and type(failure.evidence) is ModelFailureEvidence):
                    if (type(failure.evidence.reason) is str
                            and failure.evidence.reason in _REASONS):
                        reason = failure.evidence.reason
                    if _status(failure.evidence.response_status):
                        fields["response_status"] = failure.evidence.response_status
                    fingerprint = failure.request_fingerprint
                    if (type(fingerprint) is ModelRequestFingerprint
                            and _integer(fingerprint.body_bytes, MAX_REQUEST_BYTES)
                            and fingerprint.body_bytes > 0
                            and type(fingerprint.body_sha256) is str
                            and re.fullmatch(r"[0-9a-f]{64}", fingerprint.body_sha256)):
                        fields["request_fingerprint"] = {
                            "body_bytes": fingerprint.body_bytes,
                            "body_sha256": fingerprint.body_sha256,
                        }
                    if reason in {"transport_error", "transport_timeout"}:
                        try:
                            category = _transport_error_category_value(
                                failure.transport_error_category,
                            )
                        except Exception:  # noqa: BLE001 - omit only malformed optional detail
                            category = None
                        if category is not None:
                            fields["transport_error_category"] = category
                    if reason == "invalid_tool_calls":
                        try:
                            # Read owned instance storage only: optional objects and class
                            # properties must never supply diagnostic prose or callbacks.
                            metadata = object.__getattribute__(failure, "__dict__")
                            value = (metadata.get("tool_call_error_category")
                                     if type(metadata) is dict and len(metadata) <= 16
                                     and all(type(key) is str for key in metadata) else None)
                            category = _tool_call_error_category_value(value)
                        except Exception:  # noqa: BLE001 - omit only malformed optional detail
                            category = None
                        if category is not None:
                            fields["tool_call_error_category"] = category
                        if category == "arguments_invalid_json":
                            try:
                                detail = _tool_argument_decode_fields(
                                    metadata.get("tool_argument_observation"),
                                )
                            except Exception:  # noqa: BLE001 - retain existing failure evidence
                                detail = {}
                            if detail:
                                fields["tool_argument_decode"] = detail
                fields["reason"] = reason
            self._emit("model_request_" + outcome, **fields)
        except Exception:  # noqa: BLE001 - preserve original outcome, including bad clocks
            return
