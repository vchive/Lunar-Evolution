"""Private original-attempt live-module sink; never stdout/admission authority."""

from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import time
from collections.abc import Callable
from dataclasses import dataclass, fields

from . import static_python_fixed_profile as profile
from .static_python_fixed_live_modules import (
    FIXED_LIVE_COLLECTOR_SOURCE_BYTES,
    FIXED_LIVE_PRIVATE_SINK_PROFILE,
    FIXED_LIVE_RUNTIME_SINK_PROFILE,
    FIXED_LIVE_RUNTIME_SOURCE_BYTES,
    FIXED_LIVE_RUNTIME_SOURCE_SHA256,
    FIXED_LIVE_SINK_LAUNCHER_PATH,
    FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES,
    FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256,
    MAX_FIXED_LIVE_MODULES_BYTES,
    FixedPythonBoundLiveModules,
    FixedPythonLiveModulesError,
    _compose,
    compare_fixed_python_bound_live_modules,
)
from .static_python_fixed_runtime_observation import map_fixed_python_runtime_observation


class NativeFixedLiveSinkError(ValueError):
    """Fixed refusal codes without caller wire or path content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FixedPythonLiveSinkRequest:
    """Installed caller comparison inputs, not live process/custody authority."""

    installation: profile.FixedPythonInstallation
    image: bytes
    runtime_main_source: bytes
    expected_installation_sha256: str
    source_profile: str = FIXED_LIVE_PRIVATE_SINK_PROFILE

    def validate(self, *, target_sha256: str) -> None:
        try:
            if (type(self) is not FixedPythonLiveSinkRequest
                    or type(self.source_profile) is not str
                    or self.source_profile not in {FIXED_LIVE_PRIVATE_SINK_PROFILE, FIXED_LIVE_RUNTIME_SINK_PROFILE}):
                raise ValueError
            installed = profile._reparse(self.installation, self.expected_installation_sha256)
            sources = json.loads(installed.closure_bytes)["sources"]
            if {"path": FIXED_LIVE_SINK_LAUNCHER_PATH, "size": FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES,
                "sha256": FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256} not in sources:
                raise ValueError
            profile.verify_fixed_python_image(
                installed, self.image, expected_installation_sha256=self.expected_installation_sha256,
            )
            if hashlib.sha256(self.image).hexdigest() != target_sha256:
                raise ValueError
            source = self.runtime_main_source
            if (type(source) is not bytes or not FIXED_LIVE_COLLECTOR_SOURCE_BYTES < len(source) <= 64 * 1024):
                raise ValueError
            records = installed.to_dict()["frozen_modules"]
            main = next(record["source"] for record in records if record["name"] == "_lunar_static_main")
            if main != {"path": "runtime/frozen_main.py", "size": len(source),
                        "sha256": hashlib.sha256(source).hexdigest()}:
                raise ValueError
            runtime = self.source_profile == FIXED_LIVE_RUNTIME_SINK_PROFILE
            offset = FIXED_LIVE_COLLECTOR_SOURCE_BYTES
            supplement = None
            if runtime:
                supplement = source[-FIXED_LIVE_RUNTIME_SOURCE_BYTES:]
                separator = f'\n_LUNAR_LIVE_RUNTIME_SHA256 = {FIXED_LIVE_RUNTIME_SOURCE_SHA256!r}\n\n'.encode("ascii")
                offset += len(separator) + FIXED_LIVE_RUNTIME_SOURCE_BYTES
            solver = installed.profile_version.removeprefix("fixed-").removesuffix("-v1")
            if source != _compose(
                solver, tuple(sorted(installed.frozen_names)), installed.builtin_names,
                installed.aliases, tuple(sorted(record["name"] for record in records if record["package"])),
                source[-offset:][:FIXED_LIVE_COLLECTOR_SOURCE_BYTES], supplement,
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, StopIteration):
            raise NativeFixedLiveSinkError("native_fixed_live_sink_request_invalid") from None

    def compare(self, raw: bytes, *, image_device: int, image_inode: int,
                target_pid: int, manifest_sha256: str) -> FixedPythonBoundLiveModules:
        try:
            if type(self) is not FixedPythonLiveSinkRequest or type(self.source_profile) is not str:
                raise ValueError
            if self.source_profile == FIXED_LIVE_RUNTIME_SINK_PROFILE:
                return map_fixed_python_runtime_observation(
                    self.installation, raw, image=self.image, runtime_main_source=self.runtime_main_source,
                    expected_installation_sha256=self.expected_installation_sha256,
                    expected_image_device=image_device, expected_image_inode=image_inode,
                    expected_target_pid=target_pid, expected_manifest_sha256=manifest_sha256,
                ).live_modules_observation
            if self.source_profile != FIXED_LIVE_PRIVATE_SINK_PROFILE:
                raise ValueError
            return compare_fixed_python_bound_live_modules(
                self.installation, raw, image=self.image, runtime_main_source=self.runtime_main_source,
                expected_installation_sha256=self.expected_installation_sha256,
                expected_image_device=image_device, expected_image_inode=image_inode,
                expected_target_pid=target_pid, expected_manifest_sha256=manifest_sha256,
            )
        except (FixedPythonLiveModulesError, ValueError):
            raise NativeFixedLiveSinkError("native_fixed_live_sink_comparison_refused") from None


@dataclass(frozen=True, slots=True)
class _FixedPythonLiveSinkPin:
    """Original immutable request fields, with no process or admission authority.

    Validation hashes the image once per retained context. A newly copied context
    revalidates the material. Later polling compares identities of exact immutable
    fields, so owner/worker wakeups do not rehash a large image. Replacing even
    equivalent material in an existing context is drift.
    """

    request: FixedPythonLiveSinkRequest
    request_fields: tuple[object, ...]
    installation_fields: tuple[object, ...]
    target_sha256: str
    projection_json: bytes

    def assert_current(self, request: object, *, target_sha256: str) -> None:
        if (type(self) is not _FixedPythonLiveSinkPin
                or type(request) is not FixedPythonLiveSinkRequest or request is not self.request
                or target_sha256 != self.target_sha256
                or type(request.installation) is not profile.FixedPythonInstallation
                or any(getattr(request, field.name) is not value
                       for field, value in zip(fields(FixedPythonLiveSinkRequest), self.request_fields, strict=True))
                or any(getattr(request.installation, field.name) is not value
                       for field, value in zip(fields(profile.FixedPythonInstallation),
                                               self.installation_fields, strict=True))):
            raise NativeFixedLiveSinkError("native_fixed_live_sink_request_changed")

    def to_dict(self) -> dict:
        return json.loads(self.projection_json)


def _pin_fixed_python_live_sink_request(
    request: FixedPythonLiveSinkRequest, *, target_sha256: str,
) -> _FixedPythonLiveSinkPin:
    if type(request) is not FixedPythonLiveSinkRequest:
        raise NativeFixedLiveSinkError("native_fixed_live_sink_request_invalid")
    installation = request.installation
    if (type(installation) is not profile.FixedPythonInstallation
            or any(type(value) is not bytes for value in (
                request.image, request.runtime_main_source, installation.canonical_bytes,
                installation.closure_bytes,
            ))
            or any(type(value) is not str for value in (
                request.expected_installation_sha256, request.source_profile, target_sha256,
                installation.installation_sha256, installation.profile_version,
                installation.installation_version, installation.source_inventory_sha256,
                installation.configuration_sha256, installation.artifact_sha256,
                installation.frozen_inventory_sha256, installation.native_inventory_sha256,
            ))
            or any(type(vector) is not tuple or any(type(item) is not str for item in vector)
                   for vector in (installation.frozen_names, installation.builtin_names))
            or type(installation.aliases) is not tuple
            or any(type(pair) is not tuple or len(pair) != 2
                   or any(type(item) is not str for item in pair) for pair in installation.aliases)):
        raise NativeFixedLiveSinkError("native_fixed_live_sink_request_invalid")
    FixedPythonLiveSinkRequest.validate(request, target_sha256=target_sha256)
    projection = {
        "protocol": "lunar-fixed-python-live-sink-input-v1",
        "source_profile": request.source_profile,
        "installation_sha256": request.expected_installation_sha256,
        "runtime_closure_sha256": hashlib.sha256(request.installation.closure_bytes).hexdigest(),
        "image_sha256": target_sha256,
        "runtime_main_source_sha256": hashlib.sha256(request.runtime_main_source).hexdigest(),
        "production_admission": False,
    }
    return _FixedPythonLiveSinkPin(
        request, tuple(getattr(request, field.name) for field in fields(FixedPythonLiveSinkRequest)),
        tuple(getattr(request.installation, field.name) for field in fields(profile.FixedPythonInstallation)),
        target_sha256, json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )


class NativeFixedLiveSinkCapture:
    """Original host reader, drained synchronously after target_started.

    The bootstrap emits target_started on exec-error-pipe EOF, before it waits
    for the target. A collector blocked on this pipe therefore cannot prevent
    that frame. No reader thread, new process or post-deadline owner is needed.
    """

    def __init__(self, read_fd: int, *, deadline: float,
                 monotonic: Callable[[], float] = time.monotonic,
                 cancelled: Callable[[], bool] | None = None) -> None:
        if (type(read_fd) is not int or read_fd <= 2 or type(deadline) not in {int, float}
                or not math.isfinite(deadline) or not callable(monotonic)
                or (cancelled is not None and not callable(cancelled))):
            raise NativeFixedLiveSinkError("native_fixed_live_sink_context_invalid")
        self._fd = read_fd
        self._deadline = float(deadline)
        self._monotonic = monotonic
        self._cancelled = cancelled
        self._selector: selectors.BaseSelector | None = None
        self._closed = False
        self._started = False
        self._result: bytes | None = None
        self._error: str | None = None

    def start(self) -> NativeFixedLiveSinkCapture:
        if self._started or self._closed:
            raise NativeFixedLiveSinkError("native_fixed_live_sink_already_started")
        try:
            self._selector = selectors.DefaultSelector()
            os.set_blocking(self._fd, False)
            self._selector.register(self._fd, selectors.EVENT_READ)
            self._started = True
            return self
        except (OSError, ValueError):
            self.cancel()
            raise NativeFixedLiveSinkError("native_fixed_live_sink_context_invalid") from None

    def _close_owned_reader(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._selector is not None:
                self._selector.close()
        except (OSError, ValueError):
            self._error = "native_fixed_live_sink_close_unknown"
        finally:
            try:
                os.close(self._fd)
            except OSError:
                self._error = "native_fixed_live_sink_close_unknown"

    def cancel(self) -> None:
        self._error = self._error or "native_fixed_live_sink_cancelled"
        self._close_owned_reader()

    def _now(self) -> float:
        try:
            value = self._monotonic()
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError
            return float(value)
        except Exception:  # noqa: BLE001 - foreign clock callback has a fixed failure boundary
            raise NativeFixedLiveSinkError("native_fixed_live_sink_clock_unknown") from None

    def _cancelled_now(self) -> bool:
        if self._cancelled is None:
            return False
        try:
            value = self._cancelled()
        except Exception:  # noqa: BLE001 - foreign cancellation callback must not leak its error
            raise NativeFixedLiveSinkError("native_trusted_attempt_cancellation_unknown") from None
        if type(value) is not bool:
            raise NativeFixedLiveSinkError("native_trusted_attempt_cancellation_invalid")
        return value

    def finish(self) -> bytes:
        if not self._started:
            raise NativeFixedLiveSinkError("native_fixed_live_sink_not_started")
        if self._error is not None:
            raise NativeFixedLiveSinkError(self._error)
        if self._result is not None:
            return self._result
        if self._closed:
            raise NativeFixedLiveSinkError(self._error or "native_fixed_live_sink_incomplete")
        raw = bytearray()
        try:
            assert self._selector is not None
            while True:
                if self._cancelled_now():
                    raise NativeFixedLiveSinkError("native_trusted_attempt_cancelled")
                remaining = self._deadline - self._now()
                if remaining <= 0:
                    raise NativeFixedLiveSinkError("native_fixed_live_sink_wall_timeout")
                if not self._selector.select(min(0.02, remaining)):
                    continue
                try:
                    chunk = os.read(self._fd, min(65536, MAX_FIXED_LIVE_MODULES_BYTES + 1 - len(raw)))
                except BlockingIOError:
                    continue
                if not chunk:
                    if not raw:
                        raise NativeFixedLiveSinkError("native_fixed_live_sink_empty")
                    if self._now() >= self._deadline:
                        raise NativeFixedLiveSinkError("native_fixed_live_sink_wall_timeout")
                    self._result = bytes(raw)
                    break
                raw.extend(chunk)
                if len(raw) > MAX_FIXED_LIVE_MODULES_BYTES:
                    raise NativeFixedLiveSinkError("native_fixed_live_sink_limit_exceeded")
        except NativeFixedLiveSinkError as exc:
            self._error = exc.code
        except (OSError, ValueError):
            self._error = "native_fixed_live_sink_read_unknown"
        finally:
            self._close_owned_reader()
        if self._error is not None:
            raise NativeFixedLiveSinkError(self._error) from None
        assert self._result is not None
        return self._result
