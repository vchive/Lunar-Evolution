"""Bounded original procfs status checks for a private PID namespace init.

The caller must acquire these bytes through the original worker's procfs view
and bracket the read with its existing live pidfd, start-tick and namespace-FD
checks. The procfs mount must expose the same PID numbering as that original
service/client view. Parsing bytes alone proves no lifetime or cleanup fact.
"""

from __future__ import annotations

from collections.abc import Callable

MAX_WORKER_STATUS_BYTES = 65536
# Linux permits namespace levels 0 through 32, including the initial level.
MAX_PID_NAMESPACE_DEPTH = 33
_MAX_PID = 2**31 - 1
_FIELDS = {b"Pid", b"Tgid", b"NSpid", b"NStgid"}


def _refuse() -> None:
    raise ValueError("podman_worker_init")


def _decimal(raw: bytes, checkpoint: Callable[[], None]) -> int:
    checkpoint()
    if (not 0 < len(raw) <= 10 or raw[:1] == b"0"
            or any(value < 48 or value > 57 for value in raw)):
        _refuse()
    value = int(raw)
    if value > _MAX_PID:
        _refuse()
    return value


def verify_worker_namespace_init(
    status_raw: bytes, worker_pid: int, *, checkpoint: Callable[[], None] | None = None,
) -> None:
    """Require the original process leader to be PID 1 in its nested PID view.

    Relevant fields use the kernel's exact labels and tab-delimited decimal
    representation. Other status fields remain uninterpreted. This helper
    opens nothing, changes no state and returns no authority or report object.
    """
    if checkpoint is not None and not callable(checkpoint):
        _refuse()
    check = checkpoint if checkpoint is not None else lambda: None
    check()
    if (type(status_raw) is not bytes or not 0 < len(status_raw) <= MAX_WORKER_STATUS_BYTES
            or not status_raw.endswith(b"\n") or b"\x00" in status_raw
            or type(worker_pid) is not int or not 0 < worker_pid <= _MAX_PID):
        _refuse()
    fields: dict[bytes, tuple[int, ...]] = {}
    for line in status_raw.split(b"\n")[:-1]:
        check()
        key, separator, payload = line.partition(b":")
        if key.strip(b" \t") not in _FIELDS:
            continue
        if key not in _FIELDS or not separator or key in fields or not payload.startswith(b"\t"):
            _refuse()
        values = payload[1:]
        if key in {b"Pid", b"Tgid"}:
            fields[key] = (_decimal(values, check),)
        else:
            depth = values.count(b"\t") + 1
            if not 2 <= depth <= MAX_PID_NAMESPACE_DEPTH:
                _refuse()
            fields[key] = tuple(_decimal(value, check) for value in values.split(b"\t"))
    check()
    if set(fields) != _FIELDS or fields[b"Pid"] != (worker_pid,) or fields[b"Tgid"] != (worker_pid,):
        _refuse()
    namespace_pids = fields[b"NSpid"]
    if (fields[b"NStgid"] != namespace_pids
            or namespace_pids[0] != worker_pid or namespace_pids[-1] != 1):
        _refuse()
    check()
