"""Default-off original native-attempt wiring for incomplete pycache diagnostics.

The request describes a finite precreated layout and a trusted diagnostic
observer. Original grant identities come only from the still-live native
attempt. No terminal, EOF, caller boolean or clean scan establishes coverage.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from .producer_grant_anchors import HeldProducerGrantPlan
from .static_python_pycache_grants import (
    ORIGINAL_GRANT_DIAGNOSTIC_PROFILE,
    GrantBoundPycacheMonitor,
)
from .static_python_pycache_monitor import (
    FINITE_WRITE_VIEW_SCHEMA,
    MAX_DIRECTORIES,
    FinitePycacheMonitor,
)

_ORIGINAL_READER_RELEASE = FinitePycacheMonitor._release


class NativePycacheDiagnosticError(ValueError):
    """A fixed diagnostic refusal without supplied paths or exception prose."""


def _fail(reason: str) -> None:
    raise NativePycacheDiagnosticError("native_pycache_diagnostic_" + reason)


def _directories(value: tuple[str, ...]) -> None:
    if (type(value) is not tuple or not 0 < len(value) <= MAX_DIRECTORIES
            or any(type(item) is not str for item in value)
            or value != tuple(sorted(set(value))) or "." not in value):
        _fail("layout_invalid")
    for item in value:
        if item != "." and (not item or len(item) > 4096 or "\x00" in item
                            or any(part in {"", ".", ".."} for part in item.split("/"))
                            or "/" in item and item.rpartition("/")[0] not in value):
            _fail("layout_invalid")


@dataclass(frozen=True, slots=True)
class NativePycacheDiagnosticRequest:
    """Explicit configuration, never an original observation or authority."""

    observer: Callable
    diagnostic_profile: str = ORIGINAL_GRANT_DIAGNOSTIC_PROFILE
    working_directories: tuple[str, ...] = (".",)
    output_directories: tuple[str, ...] = (".",)

    def validate(self) -> None:
        if (type(self) is not NativePycacheDiagnosticRequest
                or type(self.diagnostic_profile) is not str
                or self.diagnostic_profile != ORIGINAL_GRANT_DIAGNOSTIC_PROFILE
                or not callable(self.observer)):
            _fail("request_invalid")
        _directories(self.working_directories)
        _directories(self.output_directories)
        if len(self.working_directories) + len(self.output_directories) > MAX_DIRECTORIES:
            _fail("layout_invalid")


class _NativePycacheDiagnosticScope:
    def __init__(self, request, owner, working, output, deadline_ns):
        NativePycacheDiagnosticRequest.validate(request)
        if type(owner) is not HeldProducerGrantPlan:
            _fail("original_grants_required")
        self._request = request
        self._pin = (request.observer, request.diagnostic_profile,
                     request.working_directories, request.output_directories)
        self._owner, self._working, self._output = owner, str(working), str(output)
        self._deadline = deadline_ns
        self._capture = None
        self._original_reader = None
        self._context_supplier = None
        self._context = None
        self._deliver = False

    def _check_request(self) -> None:
        request = self._request
        NativePycacheDiagnosticRequest.validate(request)
        if any(value is not original for value, original in zip(
            (request.observer, request.diagnostic_profile,
             request.working_directories, request.output_directories), self._pin, strict=True,
        )):
            _fail("request_changed")

    def arm_before_target(self, context_supplier: Callable) -> None:
        """Called by the original attempt only, before releasing its target gate."""
        self._check_request()
        if self._capture is not None or self._context_supplier is not None:
            _fail("already_armed")
        self._owner.validate()
        manifest = self._owner.manifest
        if self._working == self._output and self._pin[2] != self._pin[3]:
            _fail("layout_invalid")
        layouts = {self._working: self._pin[2], self._output: self._pin[3]}
        roots = [{"grant_id": f"original-write-{index}", "path": path,
                  "directories": list(directories)}
                 for index, (path, directories) in enumerate(sorted(layouts.items()))]
        raw = json.dumps({"schema": FINITE_WRITE_VIEW_SCHEMA,
                          "original_grants_sha256": manifest.manifest_sha256,
                          "unknown_write_capabilities": [], "roots": roots},
                         sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        context = context_supplier()
        capture = None
        try:
            capture = GrantBoundPycacheMonitor.arm_before_target(
                held_grants=self._owner, reviewed_grants_bytes=raw,
                expected_grants_sha256=hashlib.sha256(raw).hexdigest(),
                deadline_monotonic_ns=self._deadline, diagnostic_profile=self._pin[1],
            )
            # Retain immediately: a failed post-arm check must still release the
            # actual reader when the native attempt finishes its process cleanup.
            self._original_reader = capture._original_capture
        except BaseException as exc:
            # Before this transfer succeeds, scope exit has no original reader
            # to retire. Candidate code is still gated; release only the actual
            # acquisition and preserve an interrupted/allocation-failed transfer.
            if capture is not None:
                try:
                    _ORIGINAL_READER_RELEASE(capture._original_capture)
                except BaseException:  # noqa: BLE001 - keep the original acquisition/transfer failure
                    exc.add_note("native_pycache_diagnostic_original_reader_cleanup_unknown")
            raise
        self._capture = capture
        self._context_supplier, self._context = context_supplier, context
        self._check_request()
        self._owner.validate()
        if self._owner.manifest != manifest or context_supplier() != context:
            _fail("original_context_changed")
        capture.snapshot()

    def permit_diagnostic_delivery(self) -> None:
        """Permit a diagnostic callback after normal original process cleanup.

        This controls delivery only; it supplies no writer-quiescence fact.
        Timeout, cancellation and unknown native outcomes never select it.
        """
        self._deliver = True

    def close_after_native_cleanup(self, primary: BaseException | None) -> None:
        if self._original_reader is None:
            return
        try:
            observed = self._capture.finish()
            if primary is not None or not self._deliver:
                return
            self._check_request()
            if time.monotonic_ns() >= self._deadline:
                _fail("deadline")
            context = self._context_supplier()
            if context != self._context:
                _fail("original_context_changed")
            delivered = replace(context)
            try:
                if self._pin[0](delivered, observed) is not None:
                    _fail("observer_failed")
            except Exception as exc:
                raise NativePycacheDiagnosticError("native_pycache_diagnostic_observer_failed") from exc
            self._check_request()
            self._owner.validate()
            if (delivered != self._context or self._context_supplier() != self._context
                    or self._capture.snapshot() != observed):
                _fail("original_context_changed")
            if time.monotonic_ns() >= self._deadline:
                _fail("deadline")
        except BaseException as exc:
            try:
                # Use the actual original acquisition and original resource
                # retirement entry point even if a finish callable failed
                # before releasing it. This never finishes native writers or
                # supplies a replacement diagnostic/validation observation.
                _ORIGINAL_READER_RELEASE(self._original_reader)
            except BaseException:  # noqa: BLE001 - preserve the original native/finish exception
                (primary if primary is not None else exc).add_note(
                    "native_pycache_diagnostic_original_reader_cleanup_unknown",
                )
            if primary is not None:
                primary.add_note("native_pycache_diagnostic_cleanup_or_delivery_unknown")
            elif self._deliver:
                raise NativePycacheDiagnosticError(
                    "native_pycache_diagnostic_cleanup_or_delivery_unknown",
                ) from exc
            # A previously recorded failed/unknown native outcome remains the
            # result. This incomplete diagnostic supplies no substitute result.


@contextmanager
def original_native_pycache_diagnostic_scope(
    request: NativePycacheDiagnosticRequest | None, *, held_grants: HeldProducerGrantPlan | None,
    working, output, deadline_ns: int,
) -> Iterator[_NativePycacheDiagnosticScope | None]:
    """Finish after native cleanup and before the original grant context closes."""
    if request is None:
        yield None
        return
    scope = _NativePycacheDiagnosticScope(request, held_grants, working, output, deadline_ns)
    try:
        yield scope
    except BaseException as primary:
        scope.close_after_native_cleanup(primary)
        raise
    else:
        scope.close_after_native_cleanup(None)
