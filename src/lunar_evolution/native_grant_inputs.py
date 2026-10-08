"""Extract original grant proposals from already-validated native input snapshots.

This pure helper grants no authority. The formal caller must retain its existing full
input/launch validators; no current filesystem observation becomes an expected identity.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import producer_launch_inputs as producer_inputs
from . import rsi_native_inputs as rsi_inputs
from .producer_grant_anchors import (
    ProducerGrantExpectedBinding,
    ProducerGrantIdentity,
    ProducerGrantMaterial,
    ProducerGrantRequest,
)
from .rsi_learning import MAX_RSI_RECORD_BYTES, canonical_json, strict_json


class NativeGrantInputError(ValueError):
    def __init__(self, code: str = "native_grant_inputs_invalid") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NativeOriginalGrantInputs:
    requests: tuple[ProducerGrantRequest, ...]
    expected_bindings: tuple[ProducerGrantExpectedBinding, ...]
    materials: tuple[ProducerGrantMaterial, ...]


def original_native_grant_inputs(
    inputs: producer_inputs.ProducerLaunchInputDescriptor | rsi_inputs.NativeRSIInputDescriptor | None,
) -> NativeOriginalGrantInputs:
    """Propose exact original pins; never stat paths or create/bind/replay an attempt."""
    if inputs is None:
        return NativeOriginalGrantInputs((), (), ())
    if type(inputs) is producer_inputs.ProducerLaunchInputDescriptor:
        limit = producer_inputs.MAX_PRODUCER_LAUNCH_INPUT_BYTES
        names, contents = ("config.json",), (inputs.config_json,)
        fields = producer_inputs._MANIFEST_FIELDS
        protocol = producer_inputs._INPUT_PROTOCOL
    elif type(inputs) is rsi_inputs.NativeRSIInputDescriptor:
        limit = MAX_RSI_RECORD_BYTES
        names, contents = ("request.json", "memory.json"), (inputs.request_json, inputs.memory_json)
        fields = rsi_inputs._MANIFEST_FIELDS
        protocol = rsi_inputs._INPUT_PROTOCOL
    else:
        raise NativeGrantInputError()
    try:
        if type(inputs.workspace) is not type(Path()) or type(inputs.inputs_path) is not type(Path()):
            raise NativeGrantInputError()
        value = strict_json(inputs.manifest_json, limit)
        def canonical(item: object) -> bytes:
            return canonical_json(item, maximum=limit)
        if (type(value) is not dict or set(value) != fields or value["schema_version"] != "1"
                or value["protocol"] != protocol or canonical(value) != inputs.manifest_json
                or value["manifest_sha256"] != inputs.manifest_sha256
                or hashlib.sha256(canonical({k: v for k, v in value.items() if k != "manifest_sha256"})).hexdigest()
                != inputs.manifest_sha256):
            raise NativeGrantInputError()
        files = value["files"]
        if type(files) is not list or len(files) != len(names):
            raise NativeGrantInputError()
        requests, materials = [], []
        for expected, name, content in zip(files, names, contents):
            if (type(expected) is not dict
                    or set(expected) != {"name", "device", "inode", "size", "mtime_ns", "ctime_ns", "sha256"}
                    or expected["name"] != name or type(content) is not bytes or len(content) > limit
                    or type(expected["size"]) is not int or expected["size"] != len(content)
                    or expected["sha256"] != hashlib.sha256(content).hexdigest()
                    or any(type(expected[key]) is not int for key in ("mtime_ns", "ctime_ns"))):
                raise NativeGrantInputError()
            identity = ProducerGrantIdentity(expected["device"], expected["inode"], "file")
            identity.validate()
            path = str(inputs.inputs_path / name)
            requests.append(ProducerGrantRequest(path, "protected-file", identity))
            materials.append(ProducerGrantMaterial(path, identity, content, expected["mtime_ns"], expected["ctime_ns"]))
        bindings = []
        for key, path in (
            ("workspace_identity", inputs.workspace),
            ("batch_identity", inputs.inputs_path.parent),
            ("inputs_identity", inputs.inputs_path),
        ):
            expected = value[key]
            if type(expected) is not dict or set(expected) != {"device", "inode"}:
                raise NativeGrantInputError()
            identity = ProducerGrantIdentity(expected["device"], expected["inode"], "directory")
            identity.validate()
            bindings.append(ProducerGrantExpectedBinding(str(path), identity))
        for proposal in (*requests, *bindings, *materials):
            proposal.validate()
        return NativeOriginalGrantInputs(tuple(requests), tuple(bindings), tuple(materials))
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        if isinstance(exc, NativeGrantInputError):
            raise
        raise NativeGrantInputError() from exc


__all__ = ["NativeGrantInputError", "NativeOriginalGrantInputs", "original_native_grant_inputs"]
