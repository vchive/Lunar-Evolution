"""Read completed local producer snapshots into the existing Python adapter.

All execution evidence and pins belong to the caller. Source inspection reuses
the OpenEvolve/Shinka handoff readers, with no process, evaluator or export write.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Sequence
from typing import NoReturn

from . import openevolve_handoff as _openevolve
from . import shinka_handoff as _shinka
from .producer_handoff import ProducerMaterial, ProducerResultEnvelope
from .python_producer_adapter import (
    PythonProducerAdapterEnvelope,
    _canonical,
    _result_wire,
    build_python_producer_adapter_envelope,
    verify_python_producer_adapter_envelope,
    verify_python_producer_result_binding,
)
from .python_producer_binding import PythonProducerBinding
from .python_producer_lifecycle import PythonProducerRuntimeObservation, PythonProducerTerminal
from .static_python_installation import StaticPythonInstallationDescriptor

_SHA = re.compile(r"^[0-9a-f]{64}$")


class PythonProducerExportError(ValueError):
    """Fixed composition refusal without producer source, paths or prose."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_export_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerExportError(code)


def _pin(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail("pin_invalid")
    return value


def _wires(
    binding: PythonProducerBinding, terminal: PythonProducerTerminal,
    observation: PythonProducerRuntimeObservation, result: ProducerResultEnvelope,
    descriptor: StaticPythonInstallationDescriptor,
) -> tuple[bytes, bytes, bytes, bytes, bytes]:
    if (type(binding) is not PythonProducerBinding or type(terminal) is not PythonProducerTerminal
            or type(observation) is not PythonProducerRuntimeObservation
            or type(result) is not ProducerResultEnvelope
            or type(descriptor) is not StaticPythonInstallationDescriptor):
        _fail("evidence_invalid")
    try:
        return (binding.to_json(), terminal.to_json(), observation.to_json(),
                _canonical(_result_wire(result)), descriptor.to_json())
    except (ValueError, TypeError, AttributeError, RecursionError, OverflowError) as exc:
        raise PythonProducerExportError("evidence_invalid") from exc


def _openevolve_result(
    source_root: str | os.PathLike[str], result_path: str | os.PathLike[str],
    original: PythonProducerAdapterEnvelope,
) -> ProducerResultEnvelope:
    (_root, path, source, present, score_present,
     evaluation_sha256) = _openevolve._read_openevolve_snapshot(source_root, result_path)
    if len(original.result.materials) != 1:
        _fail("result_mismatch")
    return ProducerResultEnvelope(
        schema_version="1", producer_id=original.producer_id,
        producer_fingerprint=original.result.producer_fingerprint,
        producer_run_id=original.result.producer_run_id, status="completed",
        contract_sha256=original.result.contract_sha256, budget=original.result.budget,
        materials=(ProducerMaterial(
            kind="candidate_source", path=path, size=len(source),
            sha256=hashlib.sha256(source).hexdigest(),
            lineage=original.result.materials[0].lineage,
            external_evidence={"present": present, "score_present": score_present,
                               "payload_sha256": evaluation_sha256},
        ),),
    )


def _shinka_result(
    source_root: str | os.PathLike[str], original: PythonProducerAdapterEnvelope,
    top_k: int | None, program_ids: Sequence[str] | None,
) -> ProducerResultEnvelope:
    if top_k is not None and (type(top_k) is not int or not 1 <= top_k <= _shinka.MAX_SHINKA_TOP_K):
        _fail("selection_invalid")
    if program_ids is not None and (type(program_ids) not in {list, tuple}
                                   or not 1 <= len(program_ids) <= _shinka.MAX_SHINKA_TOP_K
                                   or any(type(item) is not str for item in program_ids)):
        _fail("selection_invalid")
    root = _shinka._root(source_root, _shinka.SHINKA_ROOT_UNSAFE)
    prepared = _shinka._read_shinka_snapshot(root, top_k, program_ids)
    materials = []
    for row, lineage, source, origin in prepared:
        evidence = {"correct": row.correct, "generation": row.generation, "program_id": row.program_id}
        if row.combined_score is not None:
            evidence["combined_score"] = row.combined_score
        materials.append(ProducerMaterial(
            kind="candidate_source", path=origin, size=len(source),
            sha256=hashlib.sha256(source).hexdigest(), lineage=lineage, external_evidence=evidence,
        ))
    return ProducerResultEnvelope(
        schema_version="1", producer_id=original.producer_id,
        producer_fingerprint=original.result.producer_fingerprint,
        producer_run_id=original.result.producer_run_id, status="completed",
        contract_sha256=original.result.contract_sha256, budget=original.result.budget,
        materials=tuple(materials),
    )


def read_python_producer_adapter_export(
    source_root: str | os.PathLike[str], *, producer_id: str,
    binding: PythonProducerBinding, terminal: PythonProducerTerminal,
    observation: PythonProducerRuntimeObservation, result: ProducerResultEnvelope,
    binding_sha256: str, terminal_sha256: str, observation_sha256: str, result_sha256: str,
    installation_descriptor: StaticPythonInstallationDescriptor,
    installation_descriptor_sha256: str, installation_version: str,
    initialization_profile_sha256: str,
    result_path: str | os.PathLike[str] = "result.json",
    top_k: int | None = None, program_ids: Sequence[str] | None = None,
) -> PythonProducerAdapterEnvelope:
    """Compose a read-only source snapshot with independently retained original evidence.

    ``result`` is the caller's original generic envelope, with paths relative to
    ``source_root``. Its existing canonical digest is mandatory. An unknown
    terminal or missing installation/evidence pin refuses before source-root I/O.
    """
    if type(producer_id) is not str or producer_id not in {"openevolve", "shinka"}:
        _fail("producer_mismatch")
    pins = tuple(_pin(item) for item in (
        binding_sha256, terminal_sha256, observation_sha256, result_sha256,
        installation_descriptor_sha256, initialization_profile_sha256,
    ))
    original_wires = _wires(binding, terminal, observation, result, installation_descriptor)
    if binding.producer_id != producer_id:
        _fail("producer_mismatch")
    if (binding.binding_sha256 != pins[0] or terminal.terminal_sha256 != pins[1]
            or observation.observation_sha256 != pins[2]
            or hashlib.sha256(original_wires[3]).hexdigest() != pins[3]):
        _fail("pin_mismatch")
    policy = {
        "installation_descriptor": installation_descriptor,
        "installation_descriptor_sha256": installation_descriptor_sha256,
        "installation_version": installation_version,
        "initialization_profile_sha256": initialization_profile_sha256,
    }
    try:
        original = build_python_producer_adapter_envelope(binding, terminal, observation, result, **policy)
        original = verify_python_producer_adapter_envelope(binding, original, **policy)
    except (ValueError, TypeError, AttributeError, RecursionError, OverflowError) as exc:
        raise PythonProducerExportError("evidence_invalid") from exc

    if producer_id == "openevolve":
        if top_k is not None or program_ids is not None:
            _fail("selection_invalid")
        imported = _openevolve_result(source_root, result_path, original)
    else:
        imported = _shinka_result(source_root, original, top_k, program_ids)
    if (_canonical(_result_wire(imported)) != original_wires[3]
            or imported.envelope_sha256 != result_sha256):
        _fail("result_mismatch")
    try:
        if _wires(binding, terminal, observation, result, installation_descriptor) != original_wires:
            _fail("evidence_drift")
        verified = verify_python_producer_result_binding(binding, imported)
        exported = build_python_producer_adapter_envelope(binding, original.terminal, original.observation,
                                                        verified, **policy)
        exported = verify_python_producer_adapter_envelope(binding, exported, **policy)
        if _wires(binding, terminal, observation, result, installation_descriptor) != original_wires:
            _fail("evidence_drift")
        return exported
    except PythonProducerExportError:
        raise
    except (ValueError, TypeError, AttributeError, RecursionError, OverflowError) as exc:
        raise PythonProducerExportError("evidence_drift") from exc


__all__ = ["PythonProducerExportError", "read_python_producer_adapter_export"]
