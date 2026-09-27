"""Controller-owned request execution boundary.

The request ledger records controller observations, but it cannot interrupt an
arbitrary blocking callable.  This module adds the small transport contract
needed by a controlled runtime: a transport returns a handle with explicit
``wait`` and ``cancel`` operations.  A timeout is host-enforced only after the
handle acknowledges cancellation and confirms that I/O stopped as ``cancelled``.
The transport must bound its own ``start``, ``wait``, and cancellation calls;
this synchronous broker cannot interrupt a transport that ignores its timeout.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from .producer_request_transport import (
    HostRequestEvent,
    HostRequestLedger,
    RequestAdmission,
)

_MAX_CANCEL_GRACE_SECONDS = 60.0
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_ResponseT_co = TypeVar("_ResponseT_co", covariant=True)


class ControllerRequestBrokerError(ValueError):
    """Fixed-code failure at the controller-owned transport boundary."""

    def __init__(self, code: str, *, event: HostRequestEvent | None = None) -> None:
        self.code = code
        self.event = event
        super().__init__(code)


class ControllerRequestHandle(Protocol[_ResponseT_co]):
    """Controlled transport handle with host-visible cancellation."""

    def wait(self, timeout_seconds: float) -> str | None:
        """Return a terminal status, or ``None`` after the bounded wait elapses."""

    def cancel(self) -> bool:
        """Request cancellation and report whether the transport accepted it."""

    def result(self) -> _ResponseT_co:
        """Return the local response after completion, without further I/O."""


class ControllerRequestTransport(Protocol[_ResponseT_co]):
    """Transport owned by the controller, not by the producer process."""

    def start(
        self, admission: RequestAdmission, payload: object,
    ) -> ControllerRequestHandle[_ResponseT_co]:
        """Return a valid handle after admission; clean up partial I/O on failure."""


@dataclass(frozen=True, slots=True)
class BrokerRequestResult(Generic[_ResponseT_co]):
    """Controller observation for one request handled by a controlled transport."""

    admission: RequestAdmission
    event: HostRequestEvent
    cancellation_requested: bool
    cancellation_acknowledged: bool
    host_timeout_enforced: bool
    response: _ResponseT_co | None = None


class ControllerOwnedRequestBroker(Generic[_ResponseT_co]):
    """Run requests through a transport that exposes cancellation semantics.

    The broker never stores ``payload``.  A transport that cannot acknowledge
    cancellation is rejected as uncertain at the deadline; the result cannot be
    upgraded to host-enforced evidence by polling after the call returns.
    """

    def __init__(
        self,
        ledger: HostRequestLedger,
        transport: ControllerRequestTransport[_ResponseT_co],
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        cancel_grace_seconds: float = 0.1,
    ) -> None:
        if type(ledger) is not HostRequestLedger:
            raise ControllerRequestBrokerError("producer_request_broker_ledger_invalid")
        if not callable(getattr(transport, "start", None)):
            raise ControllerRequestBrokerError("producer_request_broker_transport_invalid")
        if (
            type(cancel_grace_seconds) is not float
            or not math.isfinite(cancel_grace_seconds)
            or not 0.0 < cancel_grace_seconds <= _MAX_CANCEL_GRACE_SECONDS
        ):
            raise ControllerRequestBrokerError("producer_request_broker_cancel_grace_invalid")
        if not callable(monotonic_ns):
            raise ControllerRequestBrokerError("producer_request_broker_clock_invalid")
        self._ledger = ledger
        self._transport = transport
        self._clock = monotonic_ns
        self._cancel_grace_seconds = cancel_grace_seconds

    def execute(self, request_id: str, payload: object) -> BrokerRequestResult[_ResponseT_co]:
        """Admit, run, and finish one controller-owned request.

        The transport receives the exact controller-issued admission, including
        its deadline.  Invalid transport behavior fails the request before any
        result can be treated as complete.
        """
        admission = self._ledger.admit(request_id)
        try:
            self._remaining_seconds(admission)
        except ControllerRequestBrokerError:
            self._finish_failed(admission)
            raise
        try:
            handle = self._transport.start(admission, payload)
        except Exception as exc:
            raise ControllerRequestBrokerError(
                "producer_request_broker_transport_start_failed",
            ) from exc
        try:
            valid_handle = (
                callable(getattr(handle, "wait", None))
                and callable(getattr(handle, "cancel", None))
            )
        except Exception:  # noqa: BLE001 - malformed transport handle
            valid_handle = False
        if not valid_handle:
            raise ControllerRequestBrokerError(
                "producer_request_broker_handle_invalid",
            )

        try:
            remaining = self._remaining_seconds(admission)
        except ControllerRequestBrokerError:
            self._abort_unreliable_handle(admission, handle)
            raise
        try:
            status = handle.wait(remaining)
        except Exception as exc:
            event = self._abort_unreliable_handle(admission, handle)
            raise ControllerRequestBrokerError(
                "producer_request_broker_wait_failed", event=event,
            ) from exc
        if type(status) is str and status in _TERMINAL:
            response = None
            if status == "completed":
                try:
                    response = handle.result()
                except Exception as exc:
                    event = self._finish(admission, "failed")
                    raise ControllerRequestBrokerError(
                        "producer_request_broker_result_failed", event=event,
                    ) from exc
            event = self._finish(admission, status)
            return BrokerRequestResult(
                admission, event, False, False, False,
                response if event.status == "completed" else None,
            )
        if status is not None:
            event = self._abort_unreliable_handle(admission, handle)
            raise ControllerRequestBrokerError(
                "producer_request_broker_status_invalid", event=event,
            )

        # The transport did not finish before the controller deadline.  A
        # cancellation acknowledgement and terminal confirmation are both
        # required before this becomes host-observed timeout evidence.
        try:
            acknowledged = handle.cancel() is True
        except Exception as exc:  # noqa: BLE001 - cancellation failures are boundary errors
            acknowledged = False
            cancel_error = exc
        else:
            cancel_error = None
        if not acknowledged:
            error = ControllerRequestBrokerError(
                "producer_request_broker_timeout_unconfirmed",
            )
            if cancel_error is not None:
                raise error from cancel_error
            raise error
        try:
            terminal = handle.wait(self._cancel_grace_seconds)
        except Exception as exc:
            raise ControllerRequestBrokerError(
                "producer_request_broker_cancellation_wait_failed",
            ) from exc
        if type(terminal) is not str or terminal not in _TERMINAL:
            raise ControllerRequestBrokerError(
                "producer_request_broker_timeout_unconfirmed",
            )
        if terminal != "cancelled":
            raise ControllerRequestBrokerError(
                "producer_request_broker_timeout_unconfirmed",
            )
        event = self._expire(admission)
        if event is None:
            # The controller clock did not reach the admission deadline, so a
            # transport cannot manufacture host timeout evidence by returning
            # ``cancelled`` early.
            event = self._finish(admission, "cancelled")
            raise ControllerRequestBrokerError(
                "producer_request_broker_deadline_not_reached", event=event,
            )
        return BrokerRequestResult(admission, event, True, True, event.status == "timed_out")

    def _remaining_seconds(self, admission: RequestAdmission) -> float:
        try:
            now = self._clock()
        except Exception as exc:
            raise ControllerRequestBrokerError(
                "producer_request_broker_clock_invalid",
            ) from exc
        if type(now) is not int or now < admission.started_ns or now > 2**63 - 1:
            raise ControllerRequestBrokerError(
                "producer_request_broker_clock_invalid",
            )
        return max(0.0, (admission.deadline_ns - now) / 1_000_000_000)

    def _abort_unreliable_handle(
        self, admission: RequestAdmission, handle: ControllerRequestHandle[_ResponseT_co],
    ) -> HostRequestEvent | None:
        terminal: object = None
        try:
            if handle.cancel() is True:
                terminal = handle.wait(self._cancel_grace_seconds)
        except Exception:  # noqa: BLE001 - preserve the original boundary error
            terminal = None
        else:
            if type(terminal) is str and terminal == "cancelled":
                return self._finish(admission, "cancelled")
        return None

    def _finish(self, admission: RequestAdmission, status: str) -> HostRequestEvent:
        try:
            return self._ledger.finish(admission, status=status)
        except Exception as exc:
            raise ControllerRequestBrokerError("producer_request_broker_finish_failed") from exc

    def _finish_failed(self, admission: RequestAdmission) -> HostRequestEvent:
        return self._finish(admission, "failed")

    def _expire(self, admission: RequestAdmission) -> HostRequestEvent | None:
        try:
            expired = self._ledger.expire(admission=admission)
        except Exception as exc:
            raise ControllerRequestBrokerError("producer_request_broker_expire_failed") from exc
        for event in expired:
            if event.sequence == admission.sequence:
                return event
        return None


__all__ = [
    "BrokerRequestResult",
    "ControllerOwnedRequestBroker",
    "ControllerRequestBrokerError",
    "ControllerRequestHandle",
    "ControllerRequestTransport",
]
