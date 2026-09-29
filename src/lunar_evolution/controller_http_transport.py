"""Controller-owned HTTP transport for brokered POST requests.

Each admission owns one isolated HTTP worker.  The handle uses the admission's
absolute deadline for both worker I/O and parent-side waiting; cancellation
acknowledges a stop only after that exact worker has been reaped.
"""

from __future__ import annotations

import base64
import json
import math
import os
import selectors
import signal
import time
from dataclasses import dataclass
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
from urllib.parse import urlsplit

from . import http_transport
from .http_transport import TransportFailure, TransportResponse
from .producer_request_transport import RequestAdmission

_CANCEL_WAIT_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class ControllerHttpRequest:
    """A single non-streaming POST accepted by the isolated HTTP worker."""

    endpoint: str
    headers: dict[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if type(self.endpoint) is not str or urlsplit(self.endpoint).scheme not in {"http", "https"}:
            raise ValueError("controller_http_endpoint_invalid")
        if type(self.headers) is not dict or any(
            type(key) is not str or type(value) is not str
            for key, value in self.headers.items()
        ):
            raise ValueError("controller_http_headers_invalid")
        if type(self.body) is not bytes:
            raise ValueError("controller_http_body_invalid")
        if (
            len(self.body) > http_transport.MAX_REQUEST_BYTES
            or len(self.endpoint) > http_transport.MAX_REQUEST_BYTES
            or sum(len(key) + len(value) for key, value in self.headers.items())
            > http_transport.MAX_REQUEST_BYTES
        ):
            raise ValueError("controller_http_request_too_large")


class ControllerHttpHandle:
    """Broker-compatible handle, used serially, with in-memory response access."""

    def __init__(
        self, admission: RequestAdmission, process: Popen[bytes] | None,
        lifeline: int | None, encoded: bytes | None,
    ) -> None:
        self.admission = admission
        self.response: TransportResponse | None = None
        self.failure: TransportFailure | None = None
        self._process = process
        self._lifeline = lifeline
        self._encoded = encoded
        self._input_offset = 0
        self._output = bytearray()
        self._stdout_eof = False
        self._kill_sent = False
        self._status: str | None = None

    def wait(self, timeout_seconds: float) -> str | None:
        if self._status is not None:
            return self._status
        if (
            type(timeout_seconds) not in (int, float)
            or not 0 <= timeout_seconds <= http_transport.MAX_TIMEOUT_SECONDS
            or not math.isfinite(timeout_seconds)
        ):
            raise ValueError("controller_http_wait_invalid")
        process = self._process
        if process is None:
            return None
        now = time.monotonic_ns()
        wait_deadline = min(
            self.admission.deadline_ns, now + int(timeout_seconds * 1_000_000_000),
        )
        if now >= wait_deadline:
            return None
        try:
            if not self._exchange_until(wait_deadline):
                return None
        except TimeoutExpired:
            return None
        except (OSError, ValueError):
            if not self.cancel():
                raise
            if time.monotonic_ns() >= self.admission.deadline_ns:
                self._status = None
                return None
            self._status = "failed"
            self.failure = TransportFailure()
            return self._status

        self._close_descriptors()
        if time.monotonic_ns() >= self.admission.deadline_ns:
            return None
        if process.returncode != 0:
            self.failure = TransportFailure()
            self._status = "failed"
            return self._status
        try:
            self.response = http_transport._decode_result(bytes(self._output))
        except TransportFailure as exc:
            self.failure = exc
            self._status = "failed"
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.failure = TransportFailure()
            self._status = "failed"
        else:
            self._status = "completed"
        self._output.clear()
        if time.monotonic_ns() >= self.admission.deadline_ns:
            self.response = None
            self.failure = None
            self._status = None
        return self._status

    def result(self) -> TransportResponse:
        """Return the response only for a confirmed, on-time completed request."""
        if self._status != "completed" or self.response is None:
            raise ValueError("controller_http_response_unavailable")
        return self.response

    def _exchange_until(self, deadline_ns: int) -> bool:
        process = self._process
        assert process is not None and process.stdin is not None and process.stdout is not None
        with selectors.DefaultSelector() as watcher:
            if not self._stdout_eof:
                watcher.register(process.stdout, selectors.EVENT_READ)
            if not process.stdin.closed:
                watcher.register(process.stdin, selectors.EVENT_WRITE)
            while watcher.get_map():
                remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
                if remaining <= 0:
                    return False
                for key, _ in watcher.select(remaining):
                    if time.monotonic_ns() >= deadline_ns:
                        return False
                    if key.fileobj is process.stdin:
                        encoded = self._encoded
                        assert encoded is not None
                        try:
                            sent = os.write(key.fd, encoded[self._input_offset:self._input_offset + 65536])
                        except BrokenPipeError:
                            sent = 0
                            self._input_offset = len(encoded)
                        except BlockingIOError:
                            continue
                        self._input_offset += sent
                        if self._input_offset == len(encoded):
                            watcher.unregister(process.stdin)
                            process.stdin.close()
                            self._encoded = None
                    else:
                        try:
                            received = os.read(key.fd, min(
                                65536, http_transport.MAX_RESULT_BYTES + 1 - len(self._output),
                            ))
                        except BlockingIOError:
                            continue
                        if not received:
                            watcher.unregister(process.stdout)
                            self._stdout_eof = True
                        else:
                            self._output.extend(received)
                            if len(self._output) > http_transport.MAX_RESULT_BYTES:
                                raise ValueError("controller_http_result_too_large")
        remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
        if remaining <= 0:
            return False
        process.wait(timeout=remaining)
        return True

    def cancel(self) -> bool:
        if self._status == "cancelled":
            return True
        if self._status in {"completed", "failed"}:
            return False
        process = self._process
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    return False
                except OSError:
                    return False
                self._kill_sent = True
            try:
                process.wait(timeout=_CANCEL_WAIT_SECONDS)
            except TimeoutExpired:
                return False
            if not self._kill_sent or process.returncode != -signal.SIGKILL:
                self._close_descriptors()
                self._output.clear()
                self.response = None
                self.failure = TransportFailure()
                self._status = "failed"
                return False
        self._close_descriptors()
        self.response = None
        self.failure = None
        self._output.clear()
        self._status = "cancelled"
        return True

    def _close_descriptors(self) -> None:
        process = self._process
        if process is not None:
            for stream in (process.stdin, process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()
        if self._lifeline is not None:
            os.close(self._lifeline)
            self._lifeline = None
        self._encoded = None


class ControllerHttpTransport:
    """Start HTTP I/O only for an already-issued controller admission."""

    def start(self, admission: RequestAdmission, payload: object) -> ControllerHttpHandle:
        if os.name != "posix" or not hasattr(os, "pipe"):
            raise ValueError("controller_http_platform_unsupported")
        if type(admission) is not RequestAdmission or type(payload) is not ControllerHttpRequest:
            raise ValueError("controller_http_request_invalid")
        if os.name != "posix":
            raise ValueError("controller_http_platform_unsupported")
        if (
            type(admission.started_ns) is not int
            or type(admission.deadline_ns) is not int
            or admission.started_ns < 0
            or admission.deadline_ns <= admission.started_ns
            or admission.deadline_ns > 2**63 - 1
            or admission.deadline_ns - admission.started_ns
            > http_transport.MAX_TIMEOUT_SECONDS * 1_000_000_000
        ):
            raise ValueError("controller_http_admission_invalid")
        now = time.monotonic_ns()
        if now < admission.started_ns:
            raise ValueError("controller_http_admission_invalid")
        remaining_ns = admission.deadline_ns - now
        if remaining_ns <= 0:
            return ControllerHttpHandle(admission, None, None, None)
        seconds = remaining_ns / 1_000_000_000
        if len(payload.body) > http_transport.MAX_REQUEST_BYTES:
            raise ValueError("controller_http_request_too_large")
        request = {
            "endpoint": payload.endpoint,
            "method": "POST",
            "headers": dict(payload.headers),
            "body": base64.b64encode(payload.body).decode("ascii"),
            "timeout": seconds,
            "deadline": admission.deadline_ns / 1_000_000_000,
            "configuration": {
                "proxies": {}, "proxy_source": "environment",
                "trust": {name: os.environ[name] for name in ("SSL_CERT_FILE", "SSL_CERT_DIR")
                          if name in os.environ},
            },
            "redirect_policy": "deny",
        }
        encoded = json.dumps(
            request, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        ).encode()
        if len(encoded) > http_transport.MAX_REQUEST_BYTES:
            raise ValueError("controller_http_request_too_large")
        if time.monotonic_ns() >= admission.deadline_ns:
            return ControllerHttpHandle(admission, None, None, None)

        reader, writer = os.pipe()
        try:
            process = Popen(
                http_transport._worker_command(reader),
                stdin=PIPE, stdout=PIPE, stderr=DEVNULL,
                env={}, close_fds=True, pass_fds=(reader,), bufsize=0,
            )
        except BaseException:
            os.close(writer)
            raise
        finally:
            os.close(reader)
        handle = ControllerHttpHandle(admission, process, writer, encoded)
        try:
            assert process.stdin is not None and process.stdout is not None
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
        except BaseException:
            handle.cancel()
            raise
        return handle


__all__ = ["ControllerHttpHandle", "ControllerHttpRequest", "ControllerHttpTransport"]
