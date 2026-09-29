"""Bounded POSIX HTTP exchange and its isolated, standard-library-only worker.

Request secrets exist only in anonymous IPC. The worker shares its caller's process group;
the supervisor owns one PID and never signals that shared group.
"""

from __future__ import annotations

import base64
import http.client
import json
import math
import os
import selectors
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
from time import monotonic
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, getproxies, getproxies_environment, proxy_bypass_environment

MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_RESULT_BYTES = 12 * 1024 * 1024
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_ERROR_BYTES = 2000
MAX_TIMEOUT_SECONDS = 86400
MAX_TRANSPORT_OBSERVATION_MS = 10**12
MAX_TRANSPORT_MILESTONES = 256
_OBSERVATION_FIELDS = {"last_milestone", "http_exchange_index", "elapsed_ms"}
_MILESTONES = (
    "worker_ready", "prepare_request", "connect", "send_request",
    "wait_response_headers", "response_headers_received",
)
_PHASE_FIELDS = {"kind", "phase", "status"}
_TERMINAL_FIELDS = {"kind", "outcome", "reason", "cause", "status", "body"}
_CAUSE_REASONS = {
    "timeout": "transport_timeout", "url_timeout": "transport_timeout",
    "opaque_timeout": "transport_timeout", "cause_timeout": "transport_error",
    "url_error": "transport_error", "os_error": "transport_error",
    "local_error": "transport_error", "http_error": "http_error",
}


@dataclass(frozen=True)
class TransportObservation:
    """Last local milestone, never a provider activity or remote receipt claim."""

    last_milestone: str
    http_exchange_index: int
    elapsed_ms: int


def normalize_transport_observation(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _OBSERVATION_FIELDS:
        raise ValueError("invalid transport observation fields")
    milestone, index, elapsed = (
        value["last_milestone"], value["http_exchange_index"], value["elapsed_ms"],
    )
    if type(milestone) is not str or milestone not in _MILESTONES:
        raise ValueError("invalid transport milestone")
    if (type(index) is not int or not 0 <= index <= MAX_TRANSPORT_MILESTONES
            or (index == 0) != (milestone == "worker_ready")):
        raise ValueError("invalid transport exchange index")
    if type(elapsed) is not int or not 0 <= elapsed <= MAX_TRANSPORT_OBSERVATION_MS:
        raise ValueError("invalid transport observation time")
    return dict(value)


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes
    observation: TransportObservation | None = None


class TransportFailure(Exception):
    """Fixed transport projection; no arbitrary remote exception or text crosses IPC."""

    def __init__(
        self, phase="open_response", reason="transport_error", status=None,
        cause="local_error", body=b"", observation=None,
    ):
        super().__init__("HTTP transport failed")
        self.phase, self.reason, self.status = phase, reason, status
        self.cause, self.body = cause, body
        self.observation = observation


def validate_timeout(timeout: object) -> float:
    if (type(timeout) not in (int, float) or not 0 < timeout <= MAX_TIMEOUT_SECONDS
            or not math.isfinite(timeout)):
        raise ValueError("HTTP transport timeout must be finite and in (0, 86400]")
    return float(timeout)


def _status(value):
    return type(value) is int and 100 <= value <= 599


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate transport field")
        value[key] = item
    return value


def _load(raw):
    try:
        return json.loads(raw, object_pairs_hook=_object,
                          parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite IPC")))
    except RecursionError:
        raise ValueError("transport IPC nesting is invalid") from None


def _bytes(value, maximum):
    if type(value) is not str or len(value) > 4 * ((maximum + 2) // 3):
        raise ValueError("invalid transport body encoding")
    raw = base64.b64decode(value, validate=True)
    if len(raw) > maximum:
        raise ValueError("transport body too large")
    return raw


def _phase(frame, previous):
    if type(frame) is not dict or set(frame) != _PHASE_FIELDS or frame["kind"] != "phase":
        raise ValueError("invalid transport phase")
    phase, status = frame["phase"], frame["status"]
    if previous is None:
        if phase != "open_response" or status is not None:
            raise ValueError("invalid initial transport phase")
    elif previous != ("open_response", None) or phase not in {"read_response_body", "read_http_error_body"}:
        raise ValueError("invalid transport phase order")
    elif not _status(status) or (phase == "read_http_error_body" and 200 <= status <= 299):
        raise ValueError("invalid transport phase status")
    return phase, status


class _Progress:
    """Validate bounded legacy/coarse and optional detailed worker progress together."""

    def __init__(self):
        self.phase = None
        self.observation = None
        self.count = 0
        self.unavailable = False

    def accept(self, frame):
        if type(frame) is not dict:
            raise ValueError("invalid transport progress")
        if frame.get("kind") == "phase":
            if (self.observation is not None
                    and self.observation.last_milestone != "response_headers_received"):
                raise ValueError("body phase before observed response headers")
            self.phase = _phase(frame, self.phase)
            return
        if self.phase != ("open_response", None) or self.unavailable:
            raise ValueError("invalid transport observation order")
        if frame == {"kind": "observation_unavailable"}:
            self.observation, self.unavailable = None, True
            return
        if set(frame) != _OBSERVATION_FIELDS | {"kind"} or frame["kind"] != "milestone":
            raise ValueError("invalid transport milestone fields")
        if self.count >= MAX_TRANSPORT_MILESTONES:
            raise ValueError("too many transport milestones")
        value = normalize_transport_observation({key: frame[key] for key in _OBSERVATION_FIELDS})
        observation = TransportObservation(**value)
        previous = self.observation
        if previous is None:
            expected = ("worker_ready", 0)
        elif previous.last_milestone in {"worker_ready", "response_headers_received"}:
            expected = ("prepare_request", previous.http_exchange_index + 1)
        else:
            expected = (_MILESTONES[_MILESTONES.index(previous.last_milestone) + 1],
                        previous.http_exchange_index)
        if (observation.last_milestone, observation.http_exchange_index) != expected:
            raise ValueError("invalid transport milestone order")
        if previous is not None and observation.elapsed_ms < previous.elapsed_ms:
            raise ValueError("decreasing transport observation time")
        self.observation = observation
        self.count += 1


def _decode_result(raw: bytes) -> TransportResponse:
    if len(raw) > MAX_RESULT_BYTES or not raw.endswith(b"\n"):
        raise ValueError("invalid transport result size or framing")
    lines = raw.splitlines()
    if not 2 <= len(lines) <= MAX_TRANSPORT_MILESTONES + 4:
        raise ValueError("invalid transport frame count")
    progress = _Progress()
    for line in lines[:-1]:
        if len(line) > 512:
            raise ValueError("transport phase too large")
        progress.accept(_load(line))
    phase = progress.phase
    if phase is None:
        raise ValueError("missing transport phase")
    item = _load(lines[-1])
    if type(item) is not dict or set(item) != _TERMINAL_FIELDS or item["kind"] != "terminal":
        raise ValueError("invalid transport terminal")
    if item["status"] != phase[1] or type(item["status"]) is not type(phase[1]):
        raise ValueError("inconsistent transport status")
    if item["outcome"] == "response":
        if phase[0] != "read_response_body" or item["reason"] is not None or item["cause"] is not None:
            raise ValueError("inconsistent transport response")
        return TransportResponse(item["status"], _bytes(item["body"], MAX_BODY_BYTES),
                                 progress.observation)
    if item["outcome"] != "failure" or type(item["cause"]) is not str:
        raise ValueError("invalid transport failure")
    reason = _CAUSE_REASONS.get(item["cause"])
    if reason is None or item["reason"] != reason:
        raise ValueError("inconsistent transport failure reason")
    if reason == "http_error":
        if phase[0] != "read_http_error_body":
            raise ValueError("HTTP failure without observed status")
        body = _bytes(item["body"], MAX_ERROR_BYTES)
    else:
        if phase[0] not in {"open_response", "read_response_body"} or item["body"] != "":
            raise ValueError("invalid transport failure body or phase")
        body = b""
    raise TransportFailure(phase[0], reason, phase[1], item["cause"], body, progress.observation)


def _deadline_failure(raw: bytes) -> TransportFailure:
    progress = _Progress()
    try:
        if len(raw) > MAX_RESULT_BYTES:
            raise ValueError("oversized progress")
        # A partial terminal is expected when a deadline interrupts stdout IPC. Only complete
        # small phase frames can provide observations; a terminal can never become late success.
        for line in raw.split(b"\n")[:-1]:
            if len(line) > 512:
                break
            value = _load(line)
            if type(value) is dict and value.get("kind") == "terminal":
                break
            progress.accept(value)
    except (ValueError, TypeError, KeyError, UnicodeError):
        progress = _Progress()
    phase = progress.phase
    if phase is not None and phase[0] == "read_http_error_body":
        return TransportFailure(phase[0], "http_error", phase[1], "http_error",
                                observation=progress.observation)
    phase = phase or ("open_response", None)
    return TransportFailure(phase[0], "transport_timeout", phase[1], "timeout",
                            observation=progress.observation)


def _worker_command(lifeline: int) -> list[str]:
    return [sys.executable, "-I", "-S", "-B", str(Path(__file__).resolve()), str(lifeline)]


def _configuration():
    environment_proxies = getproxies_environment()
    return {
        "proxies": environment_proxies or getproxies(),
        "proxy_source": "environment" if environment_proxies else "system",
        "trust": {name: os.environ[name] for name in ("SSL_CERT_FILE", "SSL_CERT_DIR") if name in os.environ},
    }


def exchange(request: Request, timeout: float) -> TransportResponse:
    seconds = validate_timeout(timeout)
    if os.name != "posix" or not hasattr(os, "pipe"):
        raise TransportFailure()
    deadline = monotonic() + seconds
    payload = {
        "endpoint": request.full_url, "method": request.get_method(),
        "headers": dict(request.header_items()),
        "body": base64.b64encode(request.data or b"").decode("ascii"),
        "timeout": seconds, "deadline": deadline, "configuration": _configuration(),
        "redirect_policy": "follow",
    }
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("HTTP transport request exceeds 64 MiB")
    if monotonic() >= deadline:
        raise _deadline_failure(b"")
    reader, writer = os.pipe()
    process = None
    output = b""
    try:
        process = Popen(
            _worker_command(reader), stdin=PIPE, stdout=PIPE, stderr=DEVNULL,
            env={}, close_fds=True, pass_fds=(reader,),
        )
        os.close(reader)
        reader = None
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise _deadline_failure(b"")
        try:
            output, _ = process.communicate(input=encoded, timeout=remaining)
        except TimeoutExpired as exc:
            output = exc.output or b""
            raise _deadline_failure(output) from None
        if monotonic() >= deadline:
            raise _deadline_failure(output)
        if process.returncode != 0:
            raise TransportFailure()
        try:
            result = _decode_result(output)
        except TransportFailure:
            if monotonic() >= deadline:
                raise _deadline_failure(output) from None
            raise
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise TransportFailure() from None
        if monotonic() >= deadline:
            raise _deadline_failure(output)
        return result
    except OSError:
        raise TransportFailure() from None
    finally:
        try:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait()
        finally:
            if process is not None:
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
            if reader is not None:
                os.close(reader)
            os.close(writer)


def _emit(value):
    sys.stdout.buffer.write(json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n")
    sys.stdout.buffer.flush()


def _terminal(status, body, *, cause=None):
    _emit({"kind": "terminal", "outcome": "failure" if cause else "response",
           "reason": _CAUSE_REASONS[cause] if cause else None, "cause": cause,
           "status": status, "body": base64.b64encode(body).decode("ascii")})


def _transport_cause(error):
    current = error
    seen = set()
    timeout = False
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            timeout = True
            break
        current = current.reason if type(current) is URLError and isinstance(current.reason, BaseException) else current.__cause__
    # The legacy observer follows __cause__, not URLError.reason, and the new model error
    # occupies its first of eight nodes. Keep those two timeout observations distinct.
    current, seen = error, set()
    for _ in range(7):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return "timeout" if timeout else "cause_timeout"
        current = current.__cause__
    if isinstance(error, URLError):
        return "url_timeout" if timeout else "url_error"
    return "opaque_timeout" if timeout else "os_error"


def _guardian(lifeline):
    try:
        os.read(lifeline, 1)
    finally:
        # This thread never sends HTTP. Closing the owner's lifeline ends the entire worker,
        # including a main thread blocked in DNS or socket I/O.
        os._exit(73)


class _MilestoneEmitter:
    def __init__(self, started):
        self.started = started
        self.index = 0
        self.count = 0
        self.elapsed = 0

    def emit(self, milestone, index):
        if self.count > MAX_TRANSPORT_MILESTONES:
            return
        try:
            elapsed = math.floor((monotonic() - self.started) * 1000)
            value = normalize_transport_observation({
                "last_milestone": milestone, "http_exchange_index": index, "elapsed_ms": elapsed,
            })
            if self.count == MAX_TRANSPORT_MILESTONES or elapsed < self.elapsed:
                raise ValueError("transport observation unavailable")
        except Exception:  # noqa: BLE001 - optional clock observation cannot change the request
            # Neither observation limits nor an invalid clock should alter the request outcome.
            self.count = MAX_TRANSPORT_MILESTONES + 1
            _emit({"kind": "observation_unavailable"})
            return
        _emit({"kind": "milestone", **value})
        self.elapsed = elapsed
        self.count += 1

    def begin_exchange(self):
        self.index += 1
        self.emit("prepare_request", self.index)
        return self.index


class _ObservedConnection:
    """Wrap native calls; do not replace sockets, TLS contexts or proxy tunneling."""

    def connect(self):
        self._milestones.emit("connect", self._exchange_index)
        result = super().connect()
        self._milestones.emit("send_request", self._exchange_index)
        return result

    def request(self, *args, **kwargs):
        result = super().request(*args, **kwargs)
        # Only a local write-return observation: remote receipt/execution is unknown.
        self._milestones.emit("wait_response_headers", self._exchange_index)
        return result

    def getresponse(self):
        response = super().getresponse()
        # This may be a redirect. Never project this intermediate status as the final status.
        self._milestones.emit("response_headers_received", self._exchange_index)
        return response


class _ObservedHTTPConnection(_ObservedConnection, http.client.HTTPConnection):
    pass


class _ObservedHTTPSConnection(_ObservedConnection, http.client.HTTPSConnection):
    pass


class _ObservedHandler:
    def __init__(self, milestones):
        self._milestones = milestones
        super().__init__()

    def do_open(self, http_class, req, **kwargs):
        index = self._milestones.begin_exchange()
        observed_class = {
            http.client.HTTPConnection: _ObservedHTTPConnection,
            http.client.HTTPSConnection: _ObservedHTTPSConnection,
        }[http_class]

        def connection(*args, **kw):
            instance = observed_class(*args, **kw)
            instance._milestones = self._milestones
            instance._exchange_index = index
            return instance

        # Inherit https_open unchanged: Python versions differ in context/check_hostname/ALPN.
        return super().do_open(connection, req, **kwargs)


class _ObservedHTTPHandler(_ObservedHandler, urllib_request.HTTPHandler):
    pass


class _ObservedHTTPSHandler(_ObservedHandler, urllib_request.HTTPSHandler):
    pass


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _worker(lifeline):
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    threading.Thread(target=_guardian, args=(lifeline,), daemon=True).start()
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("request IPC too large")
    item = _load(raw)
    if type(item) is not dict or set(item) != {"endpoint", "method", "headers", "body", "timeout", "deadline", "configuration", "redirect_policy"}:
        raise ValueError("invalid request IPC")
    if type(item["redirect_policy"]) is not str or item["redirect_policy"] not in {"follow", "deny"}:
        raise ValueError("invalid redirect policy")
    seconds = validate_timeout(item["timeout"])
    deadline = item["deadline"]
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("invalid transport deadline")
    if type(item["endpoint"]) is not str or urlsplit(item["endpoint"]).scheme not in {"http", "https"}:
        raise ValueError("invalid endpoint scheme")
    if item["method"] != "POST" or type(item["headers"]) is not dict or any(
        type(key) is not str or type(value) is not str for key, value in item["headers"].items()
    ):
        raise ValueError("invalid request method/headers")
    body = _bytes(item["body"], MAX_REQUEST_BYTES)
    config = item["configuration"]
    if type(config) is not dict or set(config) != {"proxies", "proxy_source", "trust"}:
        raise ValueError("invalid HTTP configuration")
    proxies, trust = config["proxies"], config["trust"]
    if (type(proxies) is not dict or type(trust) is not dict
            or config["proxy_source"] not in {"environment", "system"}
            or set(trust) - {"SSL_CERT_FILE", "SSL_CERT_DIR"}
            or any(type(key) is not str or type(value) is not str
                   for mapping in (proxies, trust) for key, value in mapping.items())):
        raise ValueError("invalid proxy/trust projection")
    os.environ.update(trust)
    if config["proxy_source"] == "environment":
        urllib_request.proxy_bypass = lambda host: proxy_bypass_environment(host, proxies)
    milestones = _MilestoneEmitter(deadline - seconds)
    request = Request(item["endpoint"], data=body, headers=item["headers"], method=item["method"])
    status = None
    _emit({"kind": "phase", "phase": "open_response", "status": None})
    milestones.emit("worker_ready", 0)
    opener = urllib_request.build_opener(
        urllib_request.ProxyHandler(proxies),
        _ObservedHTTPHandler(milestones), _ObservedHTTPSHandler(milestones),
        _NoRedirectHandler() if item["redirect_policy"] == "deny" else urllib_request.HTTPRedirectHandler(),
    )
    remaining = deadline - monotonic()
    if remaining <= 0:
        _terminal(None, b"", cause="timeout")
        return
    with selectors.DefaultSelector() as watcher:
        watcher.register(lifeline, selectors.EVENT_READ)
        if watcher.select(0):
            os._exit(73)
    try:
        with opener.open(request, timeout=min(seconds, remaining)) as response:
            status = response.getcode()
            if not _status(status):
                raise ValueError("invalid observed response status")
            _emit({"kind": "phase", "phase": "read_response_body", "status": status})
            raw = response.read(MAX_BODY_BYTES)
    except HTTPError as error:
        status = error.code
        if not _status(status) or 200 <= status <= 299:
            raise ValueError("invalid observed HTTP error status")
        _emit({"kind": "phase", "phase": "read_http_error_body", "status": status})
        try:
            raw = error.read(MAX_ERROR_BYTES)
        except OSError:
            raw = b""
        _terminal(status, raw, cause="http_error")
    except (TimeoutError, URLError, OSError) as error:
        _terminal(status, b"", cause=_transport_cause(error))
    else:
        _terminal(status, raw)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("missing lifeline")
        _worker(int(sys.argv[1]))
    except BaseException:  # noqa: BLE001 - isolated worker must never print arbitrary exception data
        # The parent receives a fixed nonzero result, never exception prose or request data.
        raise SystemExit(70) from None
