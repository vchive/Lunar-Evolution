"""Durable checkpoint binding for a Python producer sidecar.

This module only serializes the evidence retained by a controller.  It never
captures a fresh ``stat`` from the sidecar, and a checkpoint wire cannot be
used to reconstruct a sidecar pin without the original binding and sidecar
object supplied by the caller.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from .python_producer_binding_store import PythonProducerBindingSidecar

PYTHON_PRODUCER_CHECKPOINT_PROTOCOL = "lunar-python-producer-checkpoint-v1"
PYTHON_PRODUCER_CHECKPOINT_SCHEMA_VERSION = "1"
_FIELDS = frozenset({"schema_version", "protocol", "binding_sha256", "run_id", "journal_id", "sidecar_pin"})
_PIN_FIELDS = frozenset({
    "raw_sha256", "raw_size", "file_device", "file_inode", "file_mode", "file_nlink",
    "file_mtime_ns", "file_ctime_ns",
})
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class PythonProducerCheckpointError(ValueError):
    """Fixed-code rejection for malformed or mismatched checkpoint evidence."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_checkpoint_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerCheckpointError(code)


def _sha(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _id(value: object, code: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerCheckpointError("json_invalid") from exc


def _pin_dict(sidecar: PythonProducerBindingSidecar) -> dict[str, object]:
    return {
        "raw_sha256": sidecar.raw_sha256,
        "raw_size": sidecar.raw_size,
        "file_device": sidecar.file_device,
        "file_inode": sidecar.file_inode,
        "file_mode": sidecar.file_mode,
        "file_nlink": sidecar.file_nlink,
        "file_mtime_ns": sidecar.file_mtime_ns,
        "file_ctime_ns": sidecar.file_ctime_ns,
    }


def _validate_pin(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _PIN_FIELDS:
        _fail("pin_invalid")
    _sha(value["raw_sha256"], "raw_digest_invalid")
    if type(value["raw_size"]) is not int or isinstance(value["raw_size"], bool) or not 1 <= value["raw_size"] <= 2 * 1024 * 1024:
        _fail("raw_size_invalid")
    for key in ("file_device", "file_inode", "file_mtime_ns", "file_ctime_ns"):
        item = value[key]
        if type(item) is not int or isinstance(item, bool) or item <= 0:
            _fail(f"{key}_invalid")
    if value["file_mode"] != 0o600 or type(value["file_mode"]) is not int or isinstance(value["file_mode"], bool):
        _fail("file_mode_invalid")
    if value["file_nlink"] != 1 or type(value["file_nlink"]) is not int or isinstance(value["file_nlink"], bool):
        _fail("file_nlink_invalid")
    return dict(value)


@dataclass(frozen=True, slots=True)
class PythonProducerCheckpointBinding:
    """Checkpoint wire retaining the original sidecar identity and bytes pin."""

    binding_sha256: str
    run_id: str
    journal_id: str
    sidecar_pin: Mapping[str, object]
    schema_version: str = PYTHON_PRODUCER_CHECKPOINT_SCHEMA_VERSION
    protocol: str = PYTHON_PRODUCER_CHECKPOINT_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != PYTHON_PRODUCER_CHECKPOINT_SCHEMA_VERSION or self.protocol != PYTHON_PRODUCER_CHECKPOINT_PROTOCOL:
            _fail("schema_invalid")
        _sha(self.binding_sha256)
        _id(self.run_id, "run_id_invalid")
        _id(self.journal_id, "journal_id_invalid")
        _validate_pin(dict(self.sidecar_pin) if type(self.sidecar_pin) is not dict else self.sidecar_pin)

    @classmethod
    def from_sidecar(cls, sidecar: PythonProducerBindingSidecar) -> PythonProducerCheckpointBinding:
        if type(sidecar) is not PythonProducerBindingSidecar:
            _fail("sidecar_invalid")
        binding = sidecar.binding
        try:
            digest = binding.binding_sha256
            run_id = binding.run_id
            journal_id = binding.intent.journal_id
        except (AttributeError, TypeError) as exc:
            raise PythonProducerCheckpointError("sidecar_invalid") from exc
        _sha(digest)
        return cls(digest, run_id, journal_id, _pin_dict(sidecar))

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "binding_sha256": self.binding_sha256,
            "run_id": self.run_id,
            "journal_id": self.journal_id,
            "sidecar_pin": dict(self.sidecar_pin),
        }

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PythonProducerCheckpointBinding:
        if type(value) is not dict or set(value) != _FIELDS:
            _fail("schema_invalid")
        if value["schema_version"] != PYTHON_PRODUCER_CHECKPOINT_SCHEMA_VERSION:
            _fail("schema_invalid")
        if value["protocol"] != PYTHON_PRODUCER_CHECKPOINT_PROTOCOL:
            _fail("protocol_invalid")
        return cls(value["binding_sha256"], value["run_id"], value["journal_id"], _validate_pin(value["sidecar_pin"]))

    @classmethod
    def from_json(cls, value: bytes | str) -> PythonProducerCheckpointBinding:
        if type(value) is bytes:
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PythonProducerCheckpointError("json_invalid") from exc
        if type(value) is not str:
            _fail("json_invalid")
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, RecursionError) as exc:
            raise PythonProducerCheckpointError("json_invalid") from exc
        result = cls.from_dict(parsed)
        if result.to_json().decode("utf-8") != value:
            _fail("noncanonical_json")
        return result

    def validate_sidecar(self, sidecar: PythonProducerBindingSidecar) -> None:
        """Require the original object to match; never refresh the checkpoint pin."""
        if type(sidecar) is not PythonProducerBindingSidecar:
            _fail("sidecar_invalid")
        try:
            digest = sidecar.binding.binding_sha256
            run_id = sidecar.binding.run_id
            journal_id = sidecar.binding.intent.journal_id
        except (AttributeError, TypeError) as exc:
            raise PythonProducerCheckpointError("sidecar_invalid") from exc
        if digest != self.binding_sha256 or run_id != self.run_id or journal_id != self.journal_id:
            _fail("binding_mismatch")
        if _pin_dict(sidecar) != dict(self.sidecar_pin):
            _fail("pin_mismatch")


__all__ = [
    "PYTHON_PRODUCER_CHECKPOINT_PROTOCOL", "PYTHON_PRODUCER_CHECKPOINT_SCHEMA_VERSION",
    "PythonProducerCheckpointBinding", "PythonProducerCheckpointError",
]
