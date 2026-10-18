"""Private original-BRS checkpoint primitives, without an online publication facade.

The first before/prepared pair, adjacent success staged/terminal observations and
explicit first-ordinal rejection C1/P/C2 are supported. Recovery, successor and
online composition remain separate. This module never dispatches,
evaluates, stages or publishes artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections import deque
from contextlib import _GeneratorContextManager as _ORIGINAL_CONTEXT_MANAGER
from contextlib import nullcontext
from dataclasses import fields, replace
from hashlib import sha256 as _ORIGINAL_SHA256
from json import dumps as _ORIGINAL_JSON_DUMPS
from json import loads as _ORIGINAL_JSON_LOADS
from math import isfinite as _ORIGINAL_ISFINITE
from os import fstat as _ORIGINAL_FSTAT
from os import stat as _ORIGINAL_STAT
from pathlib import Path
from sqlite3 import Row as _ORIGINAL_SQLITE_ROW
from sqlite3 import connect as _ORIGINAL_SQLITE_CONNECT
from stat import S_ISDIR as _ORIGINAL_ISDIR
from stat import S_ISREG as _ORIGINAL_ISREG
from threading import Condition, get_ident
from time import monotonic as _ORIGINAL_MONOTONIC
from typing import Any

from . import _benchmark_files as _files
from . import producer_bundle_recovery as recovery
from . import rsi_brs_rejection_owner as rejection
from . import rsi_brs_rejection_provenance as provenance
from . import rsi_brs_rejection_provenance_policy as _provenance_policy
from . import rsi_brs_rejection_ready_owner as ready_owner
from . import rsi_brs_rejection_ready_policy as ready_policy
from . import rsi_brs_rejection_ready_service as ready_service
from . import rsi_publication_lineage as lineage
from .algorithm import ALGORITHM_FAMILY_REPERTOIRES as _ORIGINAL_FAMILY_REPERTOIRES
from .candidate_evaluation_spec import canonical_json
from .producer_bundle_admission import parse_producer_bundle_admission_plan
from .producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_BATCHES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    capture_lineage_snapshot_pin,
    persist_lineage_bytes_snapshot,
    persist_lineage_descriptor,
    persist_lineage_snapshot,
    verify_persisted_lineage_snapshot,
)
from .producer_bundle_preflight import compute_archive_prefix_digest
from .producer_bundle_publication import parse_producer_bundle_publication_journal
from .python_producer_admission_handoff import read_python_producer_admission_handoff_pinned
from .rsi_brs_rejection_ready_sync import assert_ready_condition as _ORIGINAL_READY_CONDITION_ASSERT
from .rsi_budget import RSIRunBudget
from .rsi_gateway import SolverRequest
from .rsi_identity import component_fingerprint
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan

_FIELD = "producer_publication_lineage"
_PROTOCOL = "lunar-rsi-brs-lineage-checkpoint-v1"
_RUN_POLICY_FIELD = "producer_brs_checkpoint_policy"
_ORIGINAL_RUNTIME_CODES = tuple((function, getattr(function, "__code__", None)) for function in (
    _ORIGINAL_JSON_LOADS, _ORIGINAL_JSON_DUMPS, _ORIGINAL_ISDIR, _ORIGINAL_ISREG,
    _ORIGINAL_CONTEXT_MANAGER.__init__, _ORIGINAL_CONTEXT_MANAGER.__enter__, _ORIGINAL_CONTEXT_MANAGER.__exit__,
))
# Keep the enclosing guard independent of the native policy's mutable checker.
# Source fingerprints still bind defaults/captures, but a live code replacement
# can preserve the source locator and therefore requires these original objects.
_ORIGINAL_PROVENANCE_CODES = tuple(
    (module, name, vars(module)[name], vars(module)[name].__code__,
     tuple(vars(module)[name].__dict__.items()), vars(module)[name].__defaults__,
     vars(module)[name].__kwdefaults__, tuple((vars(module)[name].__kwdefaults__ or {}).items()),
     tuple((attribute, getattr(vars(module)[name], attribute))
           for attribute in ("__name__", "__qualname__", "__module__")))
    for module, names in (
        (provenance, (
            "_fail", "_owner", "_capture", "_custody", "_unchanged", "_allowance", "_control",
            "_ledger_identity", "_fixed", "_postwrite_observe", "_observe", "_material_tables", "_fresh",
            "_wire", "_capacity", "_preflight", "_read_p", "_readback", "_policy_gate",
            "rejection_provenance_binding", "retain_rejection_provenance",
            "acknowledge_rejection_provenance", "rejection_provenance_file_pin")),
        (_provenance_policy, (
            "_fail", "_capture_function", "_constant", "_check_function", "native_rejection_provenance_policy")),
        (ready_policy, ("rejection_ready_capture_policy",)),
    ) for name in names
)
_ORIGINAL_READY_POLICY_CLOSURE = (
    ready_policy.rejection_ready_capture_policy.__closure__,
    tuple(cell.cell_contents for cell in ready_policy.rejection_ready_capture_policy.__closure__),
)


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_publication_lineage_" + reason)


def _native_shape(value: object, *, depth: int = 0) -> None:
    """Reject nested DTO shadows before any original or live serializer call."""
    from .algorithm import (
        AlgorithmProblemContract,
        ConstraintSpec,
        EvolutionSpec,
        InputSpec,
        MetricSpec,
        ObjectiveSpec,
        OutputSpec,
        SourceCheckSpec,
    )
    from .evolution import CandidateIntegrityAuthority, EvolutionConfig
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    if depth > 48:
        _fail("native_strategy_shape_invalid")
    kind = type(value)
    if kind in {AlgorithmProblemContract, ConstraintSpec, EvolutionSpec, InputSpec,
                MetricSpec, ObjectiveSpec, OutputSpec, SourceCheckSpec,
                CandidateIntegrityAuthority, EvolutionConfig}:
        # Read the trusted class declaration: fields(instance) itself can be shadowed.
        declared = fields(kind)
        attributes = object.__getattribute__(value, "__dict__")
        if (type(attributes) is not dict or any(type(key) is not str for key in attributes)
                or set(attributes) != {item.name for item in declared}):
            _fail("native_strategy_shape_invalid")
        for item in declared:
            _native_shape(object.__getattribute__(value, item.name), depth=depth + 1)
    elif kind in {tuple, list, dict}:
        if kind is dict:
            if any(type(key) is not str for key in value):
                _fail("native_strategy_shape_invalid")
            items = value.values()
        else:
            items = value
        for item in items:
            _native_shape(item, depth=depth + 1)
    else:
        validate_rsi_python_admission_shapes(value)


def _native_snapshot(config: object, authority: object, contract: object) -> bytes:
    from .algorithm import AlgorithmProblemContract
    from .evolution import CandidateIntegrityAuthority, EvolutionConfig

    if (type(config) is not EvolutionConfig or type(authority) is not CandidateIntegrityAuthority
            or type(contract) is not AlgorithmProblemContract):
        _fail("native_strategy_invalid")
    _native_shape((config, authority, contract))
    return lineage._raw({"config": EvolutionConfig.to_dict(config),
                         "authority": CandidateIntegrityAuthority.to_dict(authority),
                         "contract_sha256": AlgorithmProblemContract.digest(contract)})


def _family_repertoires() -> dict[str, list[str]]:
    from . import evolution

    value = evolution.ALGORITHM_FAMILY_REPERTOIRES
    # The retained module constant is a trusted mapping proxy over primitive data.
    # Do not inspect a caller-substituted proxy which could wrap callback mapping.
    if (value is not _ORIGINAL_FAMILY_REPERTOIRES or any(type(key) is not str or type(item) is not tuple
            or any(type(family) is not str for family in item) for key, item in value.items())):
        _fail("population_repertoires_invalid")
    return {key: list(item) for key, item in value.items()}


def _policy_required(controller: Any, *, mode: object, plan: object) -> bool:
    """Select non-authorizing metadata without observing source/configuration hooks."""
    from .python_producer_binding_store import PythonProducerBindingSidecar

    return (type(mode) is str and mode == "brs" and type(plan) is dict
            and plan.get("mode") == "brs" and type(plan.get("max_workers")) is int
            and plan["max_workers"] == 1
            and type(controller.producer_sidecar) is PythonProducerBindingSidecar)


def _run_policy(controller: Any, *, mode: object = None, plan: object = None) -> dict[str, Any] | None:
    """Pin only new sidecar-bound, single-worker BRS runs; never enable execution."""
    return _policy() if _policy_required(controller, mode=mode, plan=plan) else None


def _validate_persisted_policy(
    controller: Any, *, run_id: str, state: Any = None, expected: dict[str, Any] | None = None,
) -> None:
    """Compare original JSON pins only; source/configuration hooks belong outside locks.

    Every retained record and checkpoint must carry the original policy. A later
    state cannot supply a missing original pin, and this reader never migrates it.
    """
    with controller.ledger.read_only_observations():
        history = controller.ledger.history(run_id)
        checkpoints = controller.ledger.controller_checkpoint_history(run_id)
    if not history:
        _fail("persisted_policy_original_missing")
    original = history[0].payload
    required = _policy_required(controller, mode=original.get("mode"), plan=original.get("plan"))
    policy = original.get(_RUN_POLICY_FIELD)
    snapshots = [record.payload for record in history] + [payload for _head, payload in checkpoints]
    if state is not None:
        snapshots.append(state)
    if not required:
        if expected is not None or any(_RUN_POLICY_FIELD in snapshot for snapshot in snapshots):
            _fail("persisted_policy_scope_invalid")
        return
    if (type(policy) is not dict or policy.get("protocol") != _PROTOCOL
            or policy.get("mode") != "brs" or type(policy.get("max_workers")) is not int
            or policy["max_workers"] != 1 or policy.get("online_publication") is not False
            or policy.get("production_admission") is not False):
        _fail("persisted_policy_original_invalid")
    if expected is not None and policy != expected:
        _fail("persisted_policy_drift")
    for snapshot in snapshots:
        if (snapshot.get(_RUN_POLICY_FIELD) != policy
                or not _policy_required(controller, mode=snapshot.get("mode"), plan=snapshot.get("plan"))):
            _fail("persisted_policy_drift")
    for record in history:
        fingerprints = record.payload.get("fingerprints", {})
        fingerprint = fingerprints.get("run_fingerprint", {}) if type(fingerprints) is dict else {}
        settings = fingerprint.get("solver_settings", {}) if type(fingerprint) is dict else {}
        if type(settings) is not dict or settings.get(_RUN_POLICY_FIELD) != policy:
            _fail("persisted_policy_fingerprint_invalid")


def _policy() -> dict[str, Any]:
    """Original-run and constructor BRS identity pin, never a dispatch permission."""
    if any(vars(module).get(name) is not function or function.__globals__ is not vars(module)
           or function.__code__ is not code
           or type(function.__dict__) is not dict or len(function.__dict__) != len(attributes)
           or any(type(key) is not str for key in function.__dict__)
           or any(key not in function.__dict__ or function.__dict__[key] is not value
                  for key, value in attributes)
           or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
           or (kwdefaults is not None and (
               type(kwdefaults) is not dict or len(kwdefaults) != len(kwitems)
               or any(type(key) is not str for key in kwdefaults)
               or any(key not in kwdefaults or kwdefaults[key] is not value for key, value in kwitems)))
           or any(type(getattr(function, attribute)) is not str or getattr(function, attribute) != original
                  for attribute, original in labels)
           for module, name, function, code, attributes, defaults, kwdefaults, kwitems, labels
           in _ORIGINAL_PROVENANCE_CODES):
        _fail("rejection_policy_drift")
    ready_closure, ready_captures = _ORIGINAL_READY_POLICY_CLOSURE
    try:
        if (ready_policy.rejection_ready_capture_policy.__closure__ is not ready_closure
                or any(cell.cell_contents is not original
                       for cell, original in zip(ready_closure, ready_captures, strict=True))):
            _fail("rejection_policy_drift")
    except ValueError:
        _fail("rejection_policy_drift")
    import contextlib
    import dataclasses
    import math
    import re
    import sqlite3
    import sys
    import threading
    # Refuse substituted runtime readers before hashing/serializing policy itself.
    if any(actual is not original for actual, original in (
        (sqlite3.connect, _ORIGINAL_SQLITE_CONNECT), (sqlite3.Row, _ORIGINAL_SQLITE_ROW),
        (json.loads, _ORIGINAL_JSON_LOADS), (json.dumps, _ORIGINAL_JSON_DUMPS),
        (hashlib.sha256, _ORIGINAL_SHA256), (os.fstat, _ORIGINAL_FSTAT), (os.stat, _ORIGINAL_STAT),
        (stat.S_ISDIR, _ORIGINAL_ISDIR), (stat.S_ISREG, _ORIGINAL_ISREG),
        (contextlib._GeneratorContextManager, _ORIGINAL_CONTEXT_MANAGER),
    )) or any(getattr(function, "__code__", None) is not code for function, code in _ORIGINAL_RUNTIME_CODES):
        _fail("rejection_policy_drift")
    from concurrent.futures import Future, ThreadPoolExecutor
    from types import FunctionType

    from . import (
        _candidate_workspace_io,
        automatic_solve_lifecycle,
        candidate_evaluation_spec,
        evolution,
        native_bootstrap,
        native_trusted_attempt,
        native_trusted_capture,
        native_trusted_cleanup,
        native_trusted_output,
        native_trusted_receipt,
        native_trusted_scheduler,
        native_trusted_streams,
        producer_bootstrap,
        producer_bundle_admission,
        producer_bundle_control,
        producer_bundle_deadline,
        producer_bundle_handoff,
        producer_bundle_lineage,
        producer_bundle_lineage_v2,
        producer_bundle_population,
        producer_bundle_preflight,
        producer_bundle_publication,
        producer_bundle_receipts,
        producer_bundle_rejection,
        producer_bundle_staging,
        producer_bundle_transaction,
        producer_handoff,
        producer_launcher,
        producer_process,
        producer_request_transport,
        python_producer_admission_handoff,
        rsi_brs_mailbox_evidence,
        rsi_brs_native_process_evidence,
        rsi_brs_reconcile,
        rsi_brs_rejection_c1,
        rsi_brs_rejection_capacity,
        rsi_brs_rejection_owner,
        rsi_brs_rejection_provenance,
        rsi_brs_rejection_provenance_policy,
        rsi_brs_terminal_evidence,
        rsi_budget,
        rsi_controller,
        rsi_fingerprint,
        rsi_native_rejection,
        rsi_native_scheduler,
        rsi_producer_staging_capsule,
        rsi_python_admission,
        rsi_python_brs_handoff,
        rsi_python_brs_native_dispatch,
        rsi_python_brs_owner_bridge,
        rsi_python_brs_publication_inputs,
        rsi_python_brs_publication_mailbox,
        rsi_python_brs_publication_recovery,
        rsi_python_brs_result_delivery,
        rsi_python_brs_terminal_lifecycle,
        rsi_store,
    )
    from . import rsi_python_scheduler_inputs as scheduler_inputs
    from .algorithm import (
        AlgorithmProblemContract,
        ConstraintSpec,
        EvolutionSpec,
        InputSpec,
        MetricSpec,
        ObjectiveSpec,
        OutputSpec,
        SourceCheckSpec,
    )
    from .candidate_bundle import CandidateSourceBundle, parse_candidate_source_bundle
    from .evolution import (
        Candidate,
        CandidateArchive,
        CandidateIntegrityAuthority,
        EvolutionConfig,
        PopulationStrategy,
    )
    from .producer_bundle_transaction import _records_from_archive
    from .rsi_learning import PracticeEpisode
    from .rsi_python_scheduler_inputs import _context

    reader = rsi_python_brs_publication_recovery
    dispatch = rsi_python_brs_native_dispatch
    delivery = rsi_python_brs_result_delivery
    mailbox_evidence = rsi_brs_mailbox_evidence
    process_evidence = rsi_brs_native_process_evidence
    terminal = rsi_python_brs_terminal_lifecycle
    composer = rsi_brs_terminal_evidence
    rejection_owner = rsi_brs_rejection_owner
    rejection_wire = rsi_brs_rejection_c1
    rejection_capacity = rsi_brs_rejection_capacity
    provenance_policy = rsi_brs_rejection_provenance_policy
    provenance_methods = (
        "rejection_provenance_binding", "retain_rejection_provenance",
        "acknowledge_rejection_provenance", "rejection_provenance_file_pin",
    )
    provenance_helpers = (
        "_fail", "_owner", "_capture", "_custody", "_unchanged", "_allowance", "_control",
        "_ledger_identity", "_fixed", "_postwrite_observe", "_observe", "_material_tables", "_fresh",
        "_wire", "_capacity", "_preflight", "_read_p", "_readback", "_policy_gate", *provenance_methods,
    )
    rejection_methods = (
        "_history", "_rejection_scope", "_rejection_allowance", "_rejection_control_live",
        "_rejection_cap_unchanged", "_rejection_fixed", "_rejection_observe", "_rejection_materials",
        "_rejection_readback", "_rejection_readback_observe", "_rejection_final_readback",
        "_rejection_capacity", "_rejected_entry", "retain_rejected_terminal", "checkpoint_rejected",
    )
    for value in (rejection_wire._BASE_FIELDS, rejection_wire._REJECTED_FIELDS,
                  rejection_wire._PROVENANCE_FIELDS):
        if type(value) is not frozenset or any(type(item) is not str for item in value):
            _fail("rejection_policy_drift")
    if (any(type(value) is not str for value in (
            rejection_wire.REJECTION_SCHEMA, rejection_wire.REJECTION_PROVENANCE_SCHEMA,
            rejection_wire._BRS_PROTOCOL, rejection_capacity._BRS_PROTOCOL,
            rejection_capacity._REJECTION_SCHEMA, rejection_capacity._LINEAGE_FIELD, rejection_owner._FIELD))
            or type(rejection_capacity._OBSERVATION_FIELDS) is not tuple
            or any(type(value) is not str for value in rejection_capacity._OBSERVATION_FIELDS)
            or type(rejection_capacity._IDENTIFIER) is not re.Pattern
            or type(rejection_capacity._IDENTIFIER.pattern) is not str
            or any(type(value) is not int for value in (
                rejection_capacity._MAX_INT, rejection_capacity.MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
                rejection_capacity.MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES))):
        _fail("rejection_policy_drift")
    for module, names in (
        (process_evidence, ("_FIELDS", "_REF_FIELDS", "_PIN_FIELDS", "_REASONS")),
        (mailbox_evidence, ("_BINDING_FIELDS", "_OBSERVATION_FIELDS")),
        (terminal, ("_BINDING_FIELDS", "_OBSERVATION_FIELDS")),
        (composer, ("_PIN_FIELDS", "_REPORT_FIELDS", "_TERMINAL_STATUSES")),
    ):
        for name in names:
            value = getattr(module, name)
            if type(value) is not frozenset or any(type(item) is not str for item in value):
                _fail("mailbox_evidence_policy_drift")
    for module, names in (
        (process_evidence, ("_NAMES",)), (mailbox_evidence, ("STAGES", "_MESSAGE_DIGESTS")),
        (terminal, ("STAGES",)),
    ):
        for name in names:
            value = getattr(module, name)
            if type(value) is not tuple or any(type(item) is not str for item in value):
                _fail("mailbox_evidence_policy_drift")
    for module, names in (
        (process_evidence, ("PROTOCOL", "ROLE")),
        (mailbox_evidence, ("BINDING_PROTOCOL", "OBSERVATION_PROTOCOL")),
        (terminal, ("BINDING_PROTOCOL", "OBSERVATION_PROTOCOL")),
        (composer, ("PROTOCOL",)),
    ):
        if any(type(getattr(module, name)) is not str for name in names):
            _fail("mailbox_evidence_policy_drift")
    if (any(type(value) is not int for value in (
            process_evidence._MAX, process_evidence._MAX_FILE, mailbox_evidence.MAX_BRS_MAILBOX_EVIDENCE_BYTES,
            _candidate_workspace_io._FLAGS, terminal.MAX_BRS_TERMINAL_EVIDENCE_BYTES,
            composer.MAX_BRS_TERMINAL_REPORT_BYTES))
            or any(type(value) is not re.Pattern or type(value.pattern) is not str for value in (
                process_evidence._SHA, process_evidence._ID, mailbox_evidence._SHA,
                terminal._SHA, composer._SHA))):
        _fail("mailbox_evidence_policy_drift")
    if (type(delivery._PROTOCOL) is not str or type(delivery._STATUSES) is not frozenset
            or any(type(value) is not str for value in delivery._STATUSES)
            or type(delivery._FIELDS) is not set or any(type(value) is not str for value in delivery._FIELDS)
            or type(delivery.MAX_BRS_OWNER_RESULT_BYTES) is not int
            or type(delivery._ID) is not re.Pattern or type(delivery._SHA) is not re.Pattern
            or type(delivery._ID.pattern) is not str or type(delivery._SHA.pattern) is not str):
        _fail("owner_result_policy_drift")
    native_sets = ((producer_bundle_rejection, ("_EVIDENCE_FIELDS", "_MANIFEST_FIELDS")),
                   (producer_bundle_receipts, ("_EXECUTION_FIELDS", "_EVALUATION_FIELDS", "_EVALUATION_OPTIONAL_FIELDS",
                                              "_RETAINED_EVIDENCE_FIELDS", "_RETAINED_ENTRY_FIELDS")))
    native_patterns = (producer_bundle_rejection._DIGEST, producer_bundle_receipts._SHA256, producer_bundle_receipts._ID)
    native_protocols = (producer_bundle_rejection._PROTOCOL, producer_bundle_receipts._EXECUTION_PROTOCOL,
                        producer_bundle_receipts._EVALUATION_PROTOCOL, producer_bundle_receipts._RETAINED_EVIDENCE_PROTOCOL,
                        producer_bundle_lineage_v2.LINEAGE_V2_PROTOCOL, producer_bundle_lineage_v2.LINEAGE_V2_SCHEMA_VERSION)
    native_limits = (producer_bundle_rejection._MAX_BYTES, producer_bundle_receipts._MAX_RECEIPT_BYTES,
                     producer_bundle_receipts._MAX_RETAINED_EVIDENCE_ENTRIES,
                     producer_bundle_lineage_v2.MAX_LINEAGE_BATCHES, producer_bundle_lineage_v2.MAX_LINEAGE_DESCRIPTOR_BYTES)
    if (any(type(getattr(module, name)) is not set or any(type(item) is not str for item in getattr(module, name))
            for module, names in native_sets for name in names)
            or any(type(value) is not re.Pattern or type(value.pattern) is not str for value in native_patterns)
            or any(type(value) is not str for value in native_protocols)
            or any(type(value) is not int for value in native_limits)):
        _fail("rejection_policy_drift")
    for binding in (rsi_store.RSILedger.read_only_observations,
                    rsi_controller.RSILearningController._python_admission_brs_observations):
        implementation = getattr(binding, "__wrapped__", None)
        captures = getattr(binding, "__closure__", None)
        if (type(binding) is not FunctionType or type(implementation) is not FunctionType
                or type(captures) is not tuple or len(captures) != 1 or captures[0].cell_contents is not implementation):
            _fail("rejection_policy_drift")
    transaction = producer_bundle_transaction
    control_binding = producer_bundle_control.bind_native_producer_bundle_control
    control_implementation = getattr(control_binding, "__wrapped__", None)
    closure = getattr(control_binding, "__closure__", None)
    if (type(control_binding) is not FunctionType or type(control_implementation) is not FunctionType
            or type(closure) is not tuple or len(closure) != 1
            or closure[0].cell_contents is not control_implementation):
        _fail("native_dispatch_control_binding_drift")
    aliases = (
        (ready_owner, sys.modules["lunar_evolution.rsi_brs_rejection_ready_owner"]),
        (ready_policy, sys.modules["lunar_evolution.rsi_brs_rejection_ready_policy"]),
        (rejection, rejection_owner),
        (provenance, rsi_brs_rejection_provenance),
        *((getattr(_BRSLineageCheckpointOwner, name), getattr(provenance, name))
          for name in provenance_methods),
        (provenance.json, json), (provenance.math, math), (provenance.time, time),
        (provenance._files, _files), (provenance.lineage, lineage),
        (provenance.math.isfinite, _ORIGINAL_ISFINITE), (provenance.time.monotonic, _ORIGINAL_MONOTONIC),
        (provenance.recover_native_trusted_producer, native_trusted_scheduler.recover_native_trusted_producer),
        (provenance.LineageSnapshotPin, producer_bundle_lineage.LineageSnapshotPin),
        (provenance.verify_persisted_lineage_snapshot, producer_bundle_lineage.verify_persisted_lineage_snapshot),
        (provenance.read_lineage_v2_descriptor_pinned, producer_bundle_lineage_v2.read_lineage_v2_descriptor_pinned),
        (provenance.parse_producer_bundle_publication_journal,
         producer_bundle_publication.parse_producer_bundle_publication_journal),
        (provenance._verify_terminal_batch_rejection_evidence,
         producer_bundle_rejection._verify_terminal_batch_rejection_evidence),
        (provenance.rejected_c1_entry, rejection_wire.rejected_c1_entry),
        (provenance.validate_rejected_provenance_transition, rejection_wire.validate_rejected_provenance_transition),
        (provenance.retained_brs_c1_evidence_bytes, rejection_capacity.retained_brs_c1_evidence_bytes),
        (provenance.retained_brs_c2_evidence_bytes, rejection_capacity.retained_brs_c2_evidence_bytes),
        *((getattr(provenance, name), getattr(rsi_native_rejection, name)) for name in (
            "NativeRSIRejectionEvidence", "NativeRSIRejectionFilePin", "RejectionLineageC1Binding",
            "_canonical", "_dto_shape", "persist_native_rsi_rejection_provenance",
            "read_native_rsi_rejection_provenance")),
        (provenance._read_ledger_identity, rsi_native_scheduler._read_ledger_identity),
        (provenance.validate_python_rsi_scheduler_inputs, scheduler_inputs.validate_python_rsi_scheduler_inputs),
        *((getattr(_BRSLineageCheckpointOwner, name), getattr(rejection_owner, name))
          for name in rejection_methods),
        (rejection_owner._files, _files), (rejection_owner.recovery, recovery),
        (rejection_owner.lineage, lineage), (rejection_owner.replace, dataclasses.replace),
        (rejection_owner.math, math), (rejection_owner.math.isfinite, _ORIGINAL_ISFINITE),
        (rejection_owner.time.monotonic, _ORIGINAL_MONOTONIC),
        (rejection_owner.time, time), (rejection_owner.json, json),
        (rejection_wire.hashlib, hashlib), (rejection_capacity.hashlib, hashlib),
        (rsi_store.sqlite3, sqlite3), (rsi_store.json, json), (rsi_store.hashlib, hashlib),
        (rsi_store.os, os), (rsi_store.stat, stat), (rsi_store.threading, threading),
        (rsi_store.threading.get_ident, get_ident), (rsi_controller.get_ident, get_ident),
        (rsi_store.canonical_json, candidate_evaluation_spec.canonical_json),
        (rsi_controller.canonical_json, candidate_evaluation_spec.canonical_json),
        (lineage.canonical_json, candidate_evaluation_spec.canonical_json),
        (rejection_owner.LineageSnapshotPin, producer_bundle_lineage.LineageSnapshotPin),
        (rejection_owner.capture_lineage_snapshot_pin, producer_bundle_lineage.capture_lineage_snapshot_pin),
        (rejection_owner.verify_persisted_lineage_snapshot, producer_bundle_lineage.verify_persisted_lineage_snapshot),
        (rejection_owner.ProducerLineageRejectedTerminalV2, producer_bundle_lineage_v2.ProducerLineageRejectedTerminalV2),
        (rejection_owner.persist_lineage_v2_descriptor, producer_bundle_lineage_v2.persist_lineage_v2_descriptor),
        (rejection_owner.read_lineage_v2_descriptor_pinned, producer_bundle_lineage_v2.read_lineage_v2_descriptor_pinned),
        (rejection_owner.parse_producer_bundle_publication_journal,
         producer_bundle_publication.parse_producer_bundle_publication_journal),
        (rejection_wire.LineageSnapshotPin, producer_bundle_lineage.LineageSnapshotPin),
        (rejection_wire.ProducerLineageBeforeIntent, producer_bundle_lineage.ProducerLineageBeforeIntent),
        (rejection_wire.ProducerLineageRejectedTerminalV2, producer_bundle_lineage_v2.ProducerLineageRejectedTerminalV2),
        (rejection_wire.parse_producer_bundle_publication_journal,
         producer_bundle_publication.parse_producer_bundle_publication_journal),
        (rejection_wire.validate_rsi_python_admission_shapes, rsi_python_admission.validate_rsi_python_admission_shapes),
        (rejection_wire.NativeRSIRejectionFilePin, rsi_native_rejection.NativeRSIRejectionFilePin),
        (rejection_capacity.LineageSnapshotPin, producer_bundle_lineage.LineageSnapshotPin),
        (rejection_capacity.NativeRSIRejectionFilePin, rsi_native_rejection.NativeRSIRejectionFilePin),
        (rejection_capacity._validate_retained_evidence, producer_bundle_receipts._validate_retained_evidence),
        (rejection_capacity._shape, rsi_producer_staging_capsule._shape),
        (rejection_capacity.retained_ready_capsule_bytes, rsi_producer_staging_capsule.retained_ready_capsule_bytes),
        *((getattr(producer_bundle_rejection, name), getattr(producer_bundle_staging, name)) for name in (
            "_batch", "_canonical", "_confined", "_directory", "_file_descriptor", "_present", "_pretty", "_read",
            "_regular", "_validate_python_handoff_pin", "_verify_python_handoff", "_workspace", "verify_native_publication_intent")),
        *((getattr(producer_bundle_rejection, name), getattr(producer_bundle_receipts, name)) for name in (
            "ProducerBundleEvaluationReceipt", "ProducerBundleExecutionReceipt", "_collect_retained_evidence",
            "build_native_producer_bundle_evaluation_receipt", "build_native_producer_bundle_execution_receipt")),
        *((getattr(producer_bundle_lineage_v2, name), getattr(producer_bundle_lineage, name)) for name in (
            "LineageSnapshotPin", "_absolute_path", "_create_lineage_file", "_id", "_int", "_observe_file", "_sha", "lineage_directory")),
        (persist_lineage_bytes_snapshot, producer_bundle_lineage.persist_lineage_bytes_snapshot),
        (persist_lineage_snapshot, producer_bundle_lineage.persist_lineage_snapshot),
        (persist_lineage_descriptor, producer_bundle_lineage.persist_lineage_descriptor),
        (compute_archive_prefix_digest, producer_bundle_preflight.compute_archive_prefix_digest),
        (read_python_producer_admission_handoff_pinned,
         python_producer_admission_handoff.read_python_producer_admission_handoff_pinned),
        (reader._context, scheduler_inputs._context),
        (reader._request, rsi_python_brs_publication_mailbox._request),
        (reader._request_from_native_preparation, rsi_python_brs_publication_inputs._request_from_native_preparation),
        (reader.recover_native_trusted_producer, native_trusted_scheduler.recover_native_trusted_producer),
        (reader.read_python_producer_admission_handoff_pinned,
         python_producer_admission_handoff.read_python_producer_admission_handoff_pinned),
        (reader._prepublication_control_pin, native_trusted_scheduler._prepublication_control_pin),
        (rsi_python_brs_owner_bridge.build_brs_owner_result_payload, delivery.build_brs_owner_result_payload),
        (rsi_python_brs_owner_bridge._BRSLineageCheckpointOwner, _BRSLineageCheckpointOwner),
        (rsi_python_brs_owner_bridge.BRSOwnerPublicationMailbox, rsi_python_brs_publication_mailbox.BRSOwnerPublicationMailbox),
        (rsi_python_brs_owner_bridge.BRSOwnerPublicationRequest, rsi_python_brs_publication_mailbox.BRSOwnerPublicationRequest),
        (rsi_python_brs_owner_bridge.BRSOwnerPublicationResponse, rsi_python_brs_publication_mailbox.BRSOwnerPublicationResponse),
        (rsi_python_brs_owner_bridge.BRSSelectedChildHandoff, rsi_python_brs_handoff.BRSSelectedChildHandoff),
        (rsi_python_brs_handoff.canonical_json, candidate_evaluation_spec.canonical_json),
        (delivery.canonical_json, candidate_evaluation_spec.canonical_json),
        (delivery.replace, dataclasses.replace),
        (delivery.ProducerBundlePublicationJournal, producer_bundle_publication.ProducerBundlePublicationJournal),
        (delivery.NativeProducerBundleTransactionResult, transaction.NativeProducerBundleTransactionResult),
        (delivery.BRSSelectedChildHandoff, rsi_python_brs_handoff.BRSSelectedChildHandoff),
        (delivery.BRSOwnerPublicationRequest, rsi_python_brs_publication_mailbox.BRSOwnerPublicationRequest),
        (delivery.BRSOwnerPublicationResponse, rsi_python_brs_publication_mailbox.BRSOwnerPublicationResponse),
        (delivery._request_payload, rsi_python_brs_publication_mailbox._request_payload),
        (rsi_python_brs_publication_mailbox.parse_python_producer_admission_handoff_file_pin,
         python_producer_admission_handoff.parse_python_producer_admission_handoff_file_pin),
        (producer_bundle_publication.strict_json, candidate_evaluation_spec.strict_json),
        (producer_bundle_publication._producer_identifier, producer_bundle_handoff._identifier),
        (producer_bundle_publication.parse_python_producer_admission_handoff_file_pin,
         python_producer_admission_handoff.parse_python_producer_admission_handoff_file_pin),
        (reader.SolveExecutionControl, automatic_solve_lifecycle.SolveExecutionControl),
        (dispatch.SolveExecutionControl, automatic_solve_lifecycle.SolveExecutionControl),
        (dispatch._BRSLineageCheckpointOwner, _BRSLineageCheckpointOwner),
        (dispatch.capture_lineage_snapshot_pin, producer_bundle_lineage.capture_lineage_snapshot_pin),
        (dispatch.verify_persisted_lineage_snapshot, producer_bundle_lineage.verify_persisted_lineage_snapshot),
        (dispatch.parse_producer_execution_receipt, producer_process.parse_producer_execution_receipt),
        (transaction.bind_native_producer_bundle_control, producer_bundle_control.bind_native_producer_bundle_control),
        (transaction.native_producer_bundle_budget_sha256, producer_bundle_control.native_producer_bundle_budget_sha256),
        (transaction.persist_controlled_producer_bundle_intent, producer_bundle_deadline.persist_controlled_producer_bundle_intent),
        (transaction.parse_producer_execution_receipt, producer_process.parse_producer_execution_receipt),
        (native_trusted_scheduler.recover_native_trusted_execution_receipt,
         native_trusted_receipt.recover_native_trusted_execution_receipt),
        (native_trusted_scheduler.prepare_native_trusted_output, native_trusted_output.prepare_native_trusted_output),
        (native_trusted_output.recover_native_trusted_execution_receipt,
         native_trusted_receipt.recover_native_trusted_execution_receipt),
        (native_trusted_output.recover_native_trusted_output_capture,
         native_trusted_capture.recover_native_trusted_output_capture),
        (native_trusted_output.recover_native_trusted_attempt, native_trusted_attempt.recover_native_trusted_attempt),
        (native_trusted_receipt.recover_native_trusted_attempt, native_trusted_attempt.recover_native_trusted_attempt),
        (native_trusted_receipt.recover_native_trusted_stream_capture,
         native_trusted_streams.recover_native_trusted_stream_capture),
        (native_trusted_receipt.recover_native_trusted_cleanup, native_trusted_cleanup.recover_native_trusted_cleanup),
        (native_trusted_receipt.recover_native_trusted_output_capture,
         native_trusted_capture.recover_native_trusted_output_capture),
        (native_trusted_output.prepare_producer_bundle_manifest, producer_bundle_handoff.prepare_producer_bundle_manifest),
        (native_trusted_output.prepare_producer_bundle_drafts, producer_bundle_population.prepare_producer_bundle_drafts),
        (native_trusted_output.build_producer_bundle_admission_plan,
         producer_bundle_admission.build_producer_bundle_admission_plan),
        (native_trusted_output._read_envelope, producer_process._read_envelope),
        (native_trusted_output.parse_producer_envelope, producer_handoff.parse_producer_envelope),
        (native_trusted_capture.read_host_request_journal, producer_request_transport.read_host_request_journal),
        (mailbox_evidence.canonical_json, candidate_evaluation_spec.canonical_json),
        (mailbox_evidence.parse_native_process_binding, process_evidence.parse_native_process_binding),
        (mailbox_evidence.BRSReconcileObligation, rsi_brs_reconcile.BRSReconcileObligation),
        (mailbox_evidence.BRSSelectedChildHandoff, rsi_python_brs_handoff.BRSSelectedChildHandoff),
        (mailbox_evidence.BRSOwnerPublicationRequest, rsi_python_brs_publication_mailbox.BRSOwnerPublicationRequest),
        (mailbox_evidence.BRSOwnerPublicationResponse, rsi_python_brs_publication_mailbox.BRSOwnerPublicationResponse),
        (process_evidence.canonical_json, candidate_evaluation_spec.canonical_json),
        (process_evidence.DirectoryChain, _candidate_workspace_io.DirectoryChain),
        (process_evidence.NativeBootstrapArtifact, native_bootstrap.NativeBootstrapArtifact),
        (process_evidence.NativeRSIExecutionPlan, NativeRSIExecutionPlan),
        (process_evidence.ProducerLaunchIntent, producer_launcher.ProducerLaunchIntent),
        (process_evidence.ProducerLaunchAttestation, producer_launcher.ProducerLaunchAttestation),
        (process_evidence.recover_native_trusted_attempt, native_trusted_attempt.recover_native_trusted_attempt),
        (process_evidence.recover_native_trusted_execution_receipt, native_trusted_receipt.recover_native_trusted_execution_receipt),
        (process_evidence.verify_native_trusted_cleanup, native_trusted_cleanup.verify_native_trusted_cleanup),
        (process_evidence.build_trusted_bootstrap_launch, producer_bootstrap.build_trusted_bootstrap_launch),
        (process_evidence.verify_trusted_bootstrap_process_registration,
         producer_bootstrap.verify_trusted_bootstrap_process_registration),
        (process_evidence._process_owner_identity, producer_process._process_owner_identity),
        (terminal.canonical_json, candidate_evaluation_spec.canonical_json),
        (terminal.parse_brs_mailbox_binding, mailbox_evidence.parse_brs_mailbox_binding),
        (terminal.validate_brs_mailbox_history, mailbox_evidence.validate_brs_mailbox_history),
        (terminal.validate_brs_mailbox_root_history, mailbox_evidence.validate_brs_mailbox_root_history),
        (terminal.BRSSelectedChildHandoff, rsi_python_brs_handoff.BRSSelectedChildHandoff),
        (terminal.BRSOwnerPublicationMailbox, rsi_python_brs_publication_mailbox.BRSOwnerPublicationMailbox),
        (terminal.BRSOwnerPublicationRequest, rsi_python_brs_publication_mailbox.BRSOwnerPublicationRequest),
        (terminal.BRSOwnerPublicationResponse, rsi_python_brs_publication_mailbox.BRSOwnerPublicationResponse),
        (terminal.deliver_brs_owner_result, delivery.deliver_brs_owner_result),
        (composer.canonical_json, candidate_evaluation_spec.canonical_json),
        (composer.inspect_brs_mailbox_evidence, mailbox_evidence.inspect_brs_mailbox_evidence),
        (composer.observe_native_process_binding, process_evidence.observe_native_process_binding),
        (composer.BRSReconcileEvidence, rsi_brs_reconcile.BRSReconcileEvidence),
        (composer._validate_brs_episode_history, rsi_brs_reconcile._validate_brs_episode_history),
        (composer.parse_brs_reconcile_obligations, rsi_brs_reconcile.parse_brs_reconcile_obligations),
        (composer.inspect_brs_worker_terminal_evidence, terminal.inspect_brs_worker_terminal_evidence),
        (composer.PracticeEpisode, PracticeEpisode),
        (terminal.Future, Future), (terminal.ThreadPoolExecutor, ThreadPoolExecutor),
        (terminal.threading, threading), (terminal.time, time),
        (terminal.threading.get_ident, get_ident),
    )
    if any(actual is not canonical for actual, canonical in aliases):
        _fail("native_reader_binding_drift")
    # Code fingerprints do not capture a function's globals. Pin the finite
    # recovery entry chain to its canonical application module dictionary too.
    # This also refuses replacing both sides of an import alias with one clone.
    entries = (
        *((getattr(provenance, name), provenance) for name in provenance_helpers),
        *((getattr(provenance_policy, name), provenance_policy) for name in (
            "_fail", "_constant", "_check_function", "native_rejection_provenance_policy")),
        *((getattr(rejection_owner, name), rejection_owner) for name in ("_fail", *rejection_methods)),
        *((getattr(rejection_wire, name), rejection_wire) for name in (
            "_fail", "rejected_c1_entry", "rejected_c1_index", "validate_rejected_c1_transition",
            "rejected_provenance_entry", "rejected_provenance_index", "validate_rejected_provenance_transition")),
        *((getattr(rejection_capacity, name), rejection_capacity) for name in (
            "_fail", "_identifier", "_pin_record", "_add_material", "_retained_brs_c1_materials",
            "retained_brs_c1_evidence_bytes", "retained_brs_c2_evidence_bytes")),
        *((getattr(producer_bundle_lineage_v2, name), producer_bundle_lineage_v2) for name in (
            "_fail", "_plain", "_canonical", "_normalized_snapshot_pin", "_pin_payload", "_wire",
            "_association", "_seal", "parse_lineage_v2_descriptor", "persist_lineage_v2_descriptor",
            "read_lineage_v2_descriptor_pinned")),
        *((getattr(producer_bundle_lineage_v2.ProducerLineageRejectedTerminalV2, name), producer_bundle_lineage_v2)
          for name in ("__post_init__", "_validated_payload", "to_dict", "to_json", "digest")),
        (producer_bundle_lineage_v2.ProducerLineageRejectedTerminalV2.from_dict.__func__, producer_bundle_lineage_v2),
        *((getattr(producer_bundle_rejection, name), producer_bundle_rejection) for name in (
            "_fail", "_sha", "_prepared", "_preflight", "_json", "_verify_receipts",
            "_verify_terminal_batch_rejection_evidence",
            "_verify_rejection_files", "_exact_evidence_shape")),
        (producer_bundle_rejection.VerifiedProducerBundleRejection.__post_init__, producer_bundle_rejection),
        *((getattr(producer_bundle_receipts, name), producer_bundle_receipts) for name in (
            "_fail", "_digest", "_identifier", "_canonical", "_object", "_sha", "_digest_payload", "_mapping",
            "_validate_retained_evidence", "_retained_evidence_digest", "_retained_evidence_payload",
            "_retained_entry", "_collect_retained_evidence", "verify_native_retained_evidence", "_normal_report",
            "build_native_producer_bundle_execution_receipt", "build_native_producer_bundle_evaluation_receipt")),
        *((getattr(kind, name), producer_bundle_receipts) for kind in (
            producer_bundle_receipts.ProducerBundleExecutionReceipt, producer_bundle_receipts.ProducerBundleEvaluationReceipt)
          for name in ("__post_init__", "to_dict", "digest")),
        *((kind.from_dict.__func__, producer_bundle_receipts) for kind in (
            producer_bundle_receipts.ProducerBundleExecutionReceipt, producer_bundle_receipts.ProducerBundleEvaluationReceipt)),
        (producer_bundle_staging.verify_native_publication_intent, producer_bundle_staging),
        *((getattr(_ORIGINAL_CONTEXT_MANAGER, name), contextlib) for name in ("__init__", "__enter__", "__exit__")),
        (rsi_store._id, rsi_store),
        (rsi_store.RSILedger.read_only_observations, contextlib),
        (rsi_store.RSILedger.read_only_observations.__wrapped__, rsi_store),
        *((getattr(rsi_store.RSILedger, name), rsi_store) for name in (
            "_connect", "_checkpoint_python_references", "_checkpoint_digest", "_checkpoint_reference_rows_tx",
            "_python_admission_row", "controller_lock_held", "_assert_controller_lock")),
        (rsi_controller.RSILearningController._python_admission_brs_observations, contextlib),
        (rsi_controller.RSILearningController._python_admission_brs_observations.__wrapped__, rsi_controller),
        (rsi_controller.RSILearningController._python_admission_flow_payload, rsi_controller),
        (rsi_controller.RSILearningController._python_admission_assert_brs_wave, rsi_controller),
        (rsi_controller._record_digest, rsi_controller),
        (rsi_controller.RSILearningController._run_fingerprint, rsi_controller),
        *((getattr(rsi_fingerprint, name), rsi_fingerprint) for name in (
            "ensure_fingerprint_compatible", "compare_fingerprint_contracts", "_normalize_json", "_json_value", "_settings")),
        *((getattr(rsi_fingerprint.RSIFingerprintContract, name), rsi_fingerprint)
          for name in ("__post_init__", "digest", "to_dict")),
        (rsi_fingerprint.RSIFingerprintContract.from_dict.__func__, rsi_fingerprint),
        (rsi_budget.RSIRunBudget.load.__func__, rsi_budget),
        *((getattr(rsi_budget.RSIRunBudget, name), rsi_budget)
          for name in ("__init__", "_validate", "assert_matches", "check", "_check_unlocked", "_check_depth", "to_dict")),
        (rsi_producer_staging_capsule.retained_ready_capsule_bytes, rsi_producer_staging_capsule),
        (rsi_producer_staging_capsule._shape, rsi_producer_staging_capsule),
        (rsi_python_admission.validate_rsi_python_admission_shapes, rsi_python_admission),
        (_retain_mailbox_observation, sys.modules[__name__]),
        (_mailbox_fixed_tail, sys.modules[__name__]),
        *((getattr(terminal, name), terminal) for name in (
            "_fail", "_plain", "_clean", "_digest", "_sha", "parse_brs_terminal_binding",
            "brs_terminal_evidence_namespace", "_messages", "parse_brs_terminal_observation",
            "build_brs_terminal_observation", "validate_brs_terminal_history",
            "inspect_brs_worker_terminal_evidence", "open_brs_terminal_lifecycle")),
        *((getattr(terminal._PrimitiveExchange, name), terminal)
          for name in ("__init__", "submit", "fail")),
        *((getattr(terminal._BRSWorkerTerminalEndpoint, name), terminal)
          for name in ("__init__", "receive_and_settle")),
        (terminal._BRSWorkerTerminalEndpoint.status.fget, terminal),
        *((getattr(terminal.BRSOwnerTerminalLifecycle, name), terminal)
          for name in ("_fixed", "_append", "_drain", "serve")),
        (terminal.BRSOwnerTerminalLifecycle.worker_endpoint.fget, terminal),
        *((getattr(composer, name), composer) for name in (
            "_fail", "_plain", "_clean", "_digest", "_sha", "_text", "_pins",
            "parse_brs_terminal_observation", "_ledger_terminal", "_publication", "_finish",
            "_compose_brs_terminal_evidence", "inspect_brs_terminal_observation")),
        (_candidate_workspace_io.fail, _candidate_workspace_io),
        (_candidate_workspace_io.identity, _candidate_workspace_io),
        *((getattr(_candidate_workspace_io.DirectoryChain, name), _candidate_workspace_io)
          for name in ("__init__", "check", "close")),
        (_candidate_workspace_io.DirectoryChain.fd.fget, _candidate_workspace_io),
        *((getattr(mailbox_evidence, name), mailbox_evidence) for name in (
            "_fail", "_sha", "_plain", "_clean", "_digest", "parse_brs_mailbox_binding",
            "build_brs_mailbox_binding", "brs_mailbox_evidence_namespace", "parse_brs_mailbox_observation",
            "build_brs_mailbox_observation", "validate_brs_mailbox_history", "inspect_brs_mailbox_evidence",
            "validate_brs_mailbox_root_history")),
        *((getattr(process_evidence, name), process_evidence) for name in (
            "_fail", "_plain", "_sha", "_number", "_digest", "_owner", "parse_native_process_binding",
            "_workspace", "_identity", "_pairs", "_entry", "_records", "_plan",
            "capture_native_process_binding", "_group", "_process", "observe_native_process_binding")),
        (native_trusted_cleanup.verify_native_trusted_cleanup, native_trusted_cleanup),
        (producer_bootstrap.build_trusted_bootstrap_launch, producer_bootstrap),
        (producer_bootstrap.verify_trusted_bootstrap_process_registration, producer_bootstrap),
        (producer_process._process_owner_identity, producer_process),
        *((getattr(producer_bundle_lineage, name), producer_bundle_lineage) for name in (
            "persist_lineage_bytes_snapshot", "persist_lineage_snapshot", "persist_lineage_descriptor",
            "_create_lineage_file", "_observe_file", "verify_lineage_snapshot_pin")),
        (compute_archive_prefix_digest, producer_bundle_preflight),
        *((getattr(evolution.PopulationStrategy, name), evolution) for name in (
            "_validate_candidate_integrity_state", "_active", "_reconstruct_population_projection",
            "_producer_admission_events", "_apply_producer_admissions", "_trim", "_capacity", "_candidates",
            "_rank", "_family_elites", "_candidate_family")),
        (evolution._novelty, evolution), (evolution._tokens, evolution),
        *((getattr(_BRSLineageCheckpointOwner, name), sys.modules[__name__]) for name in (
            "retain_staged", "verify_precommit", "retain_terminal", "_success_observe", "_success_fixed",
            "_success_capacity", "_success_scope", "_success_control_live", "_success_allowance",
            "_success_cap_unchanged",
            "_success_entry", "_verify_staged_projection", "_candidate_materials")),
        *((getattr(_BRSLineageCheckpointOwner, name), sys.modules[__name__]) for name in (
            "retain_reconcile_obligation", "_reconcile_registration_observe", "_reconcile_registration_readback",
            "_reconcile_registration_fixed", "retain_mailbox_observation", "_mailbox_native_arguments",
            "_mailbox_process_unchanged", "_mailbox_readback")),
        *((getattr(rsi_brs_reconcile, name), rsi_brs_reconcile) for name in (
            "register_brs_selected_obligation", "put_brs_reconcile_obligation", "validate_brs_reconcile_obligations")),
        *((getattr(rsi_store.RSILedger, name), rsi_store) for name in (
            "write_brs_reconcile_obligation", "_append_controller_checkpoint_tx",
            "controller_checkpoint_history", "_controller_checkpoint_history_tx", "_native_result_status",
            "_native_claim_row", "append_brs_mailbox_observation", "append_brs_terminal_observation",
            "read_brs_terminal_evidence_snapshot", "_brs_terminal_evidence_snapshot_tx",
            "_consume_brs_reconcile_obligation")),
        (PracticeEpisode.from_dict.__func__, sys.modules[PracticeEpisode.__module__]),
        (PracticeEpisode.to_record_dict, sys.modules[PracticeEpisode.__module__]),
        (recovery.resume_producer_bundle_publication, recovery),
        (producer_bundle_lineage.read_lineage_descriptor_pinned, producer_bundle_lineage),
        *((getattr(Future, name), sys.modules[Future.__module__])
          for name in ("done", "running", "exception", "result")),
        (ThreadPoolExecutor.shutdown, sys.modules[ThreadPoolExecutor.__module__]),
        (threading.Thread.is_alive, threading), (threading.current_thread, threading),
        *((getattr(threading.Condition, name), threading)
          for name in ("wait", "notify_all", "__enter__", "__exit__")),
        *((getattr(rsi_python_brs_owner_bridge, name), rsi_python_brs_owner_bridge) for name in (
            "run_brs_owner_publication_mailbox", "_require_original_mailbox", "_require_disabled_policy",
            "_response_payload")),
        (rsi_python_brs_owner_bridge._original_control, dispatch),
        (rsi_python_brs_owner_bridge._run_original_brs_native_publication, dispatch),
        (rsi_python_brs_owner_bridge.build_brs_owner_result_payload, delivery),
        *((getattr(delivery, name), delivery) for name in (
            "_fail", "_id", "_sha", "_shape", "_canonical_payload", "_journal",
            "build_brs_owner_result_payload", "deliver_brs_owner_result")),
        *((getattr(delivery.BRSOwnerResultDelivery, name), delivery)
          for name in ("__post_init__", "to_dict")),
        *((getattr(delivery.BRSOwnerResultSettlement, name), delivery)
          for name in ("__init__", "settle")),
        (delivery.BRSOwnerResultSettlement.delivery.fget, delivery),
        (delivery.BRSOwnerResultSettlement.status.fget, delivery),
        *((getattr(candidate_evaluation_spec, name), candidate_evaluation_spec)
          for name in ("canonical_json", "strict_json", "_fail", "_maximum", "_json_bytes")),
        *((getattr(producer_bundle_publication, name), producer_bundle_publication) for name in (
            "_fail", "_digest", "_identifier", "_optional_identifier", "_canonical", "_object",
            "_bounded_int", "parse_producer_bundle_publication_journal")),
        *((getattr(producer_bundle_publication.ProducerBundlePublicationJournal, name), producer_bundle_publication)
          for name in ("__post_init__", "_payload_dict", "to_dict", "digest")),
        (producer_bundle_publication.ProducerBundlePublicationJournal.from_dict.__func__, producer_bundle_publication),
        *((getattr(producer_bundle_publication.ProducerBundlePublicationCandidate, name), producer_bundle_publication)
          for name in ("__post_init__", "to_dict")),
        (producer_bundle_publication.ProducerBundlePublicationCandidate.from_dict.__func__, producer_bundle_publication),
        *((getattr(rsi_python_brs_handoff.BRSSelectedChildHandoff, name), rsi_python_brs_handoff)
          for name in ("__post_init__", "to_dict")),
        (rsi_python_brs_handoff.BRSSelectedChildHandoff.canonical_bytes.fget, rsi_python_brs_handoff),
        (rsi_python_brs_handoff.BRSSelectedChildHandoff.sha256.fget, rsi_python_brs_handoff),
        *((getattr(rsi_python_brs_handoff, name), rsi_python_brs_handoff)
          for name in ("_fail", "_identity", "_digest", "_int")),
        *((getattr(rsi_python_brs_publication_mailbox, name), rsi_python_brs_publication_mailbox) for name in (
            "_fail", "_identity", "_sha", "_shape", "_payload", "_request_payload", "_digest",
            "_primitive_fields", "build_brs_owner_publication_response")),
        (rsi_python_brs_publication_mailbox.BRSOwnerPublicationRequest.__post_init__, rsi_python_brs_publication_mailbox),
        (rsi_python_brs_publication_mailbox.BRSOwnerPublicationResponse.__post_init__, rsi_python_brs_publication_mailbox),
        (rsi_python_brs_publication_mailbox.BRSOwnerPublicationMailbox.service, rsi_python_brs_publication_mailbox),
        (rsi_python_brs_publication_mailbox.BRSOwnerPublicationMailbox.request, rsi_python_brs_publication_mailbox),
        (rsi_python_brs_publication_mailbox.BRSOwnerPublicationMailbox._observation_snapshot, rsi_python_brs_publication_mailbox),
        *((getattr(python_producer_admission_handoff, name), python_producer_admission_handoff) for name in (
            "parse_python_producer_admission_handoff_file_pin", "_validate_file_pin_payload",
            "_canonical", "_strict_json", "_pairs", "_sha", "_identifier", "_fail")),
        *((getattr(python_producer_admission_handoff.PythonProducerAdmissionHandoffFilePin, name),
           python_producer_admission_handoff) for name in ("__post_init__", "_payload", "to_dict")),
        *((getattr(producer_bundle_staging, name), producer_bundle_staging) for name in (
            "_load_marker", "_check_held_publication_lock", "_read", "_sha", "_canonical", "_marker_bytes", "_pretty", "_fail")),
        *((getattr(producer_bundle_staging.ProducerBundlePublicationManifest, name), producer_bundle_staging)
          for name in ("to_dict", "digest")),
        *((getattr(reader._BRSRetainedNativePreparationReader, name), reader)
          for name in ("__init__", "_scope", "_check", "_project", "recover")),
        *((getattr(reader, name), reader) for name in (
            "_fail", "_copy", "_comparison_preparation", "_arguments", "_dto_policy", "_control_pin")),
        (rsi_python_brs_publication_inputs._request_from_native_preparation, rsi_python_brs_publication_inputs),
        (scheduler_inputs._context, scheduler_inputs),
        (rsi_python_brs_publication_mailbox._request, rsi_python_brs_publication_mailbox),
        (native_trusted_scheduler.recover_native_trusted_producer, native_trusted_scheduler),
        (native_trusted_scheduler._prepublication_control_pin, native_trusted_scheduler),
        (native_trusted_receipt.recover_native_trusted_execution_receipt, native_trusted_receipt),
        (native_trusted_receipt.build_native_trusted_execution_receipt, native_trusted_receipt),
        (native_trusted_attempt.recover_native_trusted_attempt, native_trusted_attempt),
        (native_trusted_streams.recover_native_trusted_stream_capture, native_trusted_streams),
        (native_trusted_cleanup.recover_native_trusted_cleanup, native_trusted_cleanup),
        (native_trusted_capture.recover_native_trusted_output_capture, native_trusted_capture),
        (native_trusted_output.prepare_native_trusted_output, native_trusted_output),
        (producer_process._read_envelope, producer_process),
        (producer_handoff.parse_producer_envelope, producer_handoff),
        (producer_bundle_handoff.prepare_producer_bundle_manifest, producer_bundle_handoff),
        (producer_bundle_population.prepare_producer_bundle_drafts, producer_bundle_population),
        (producer_bundle_admission.build_producer_bundle_admission_plan, producer_bundle_admission),
        (python_producer_admission_handoff.read_python_producer_admission_handoff_pinned,
         python_producer_admission_handoff),
        (producer_request_transport.read_host_request_journal, producer_request_transport),
        *((getattr(automatic_solve_lifecycle.SolveExecutionControl, name), automatic_solve_lifecycle)
          for name in ("check", "is_cancelled", "_now")),
        (automatic_solve_lifecycle._finite_time, automatic_solve_lifecycle),
        (automatic_solve_lifecycle._stage_name, automatic_solve_lifecycle),
        *((getattr(dispatch, name), dispatch) for name in (
            "_fail", "_original_control", "_fixed_original_brs_owner", "_original_brs_numeric_tail",
            "_call_original_brs_owner", "_run_original_brs_native_publication")),
        *((getattr(transaction, name), transaction) for name in (
            "_validate_native_lineage_scope", "_native_lineage_call", "derive_population_state_after",
            "_derive_population_state_after", "_run_bound_native_producer_bundle_publication_transaction",
            "_run_native_producer_bundle_publication_transaction", "_verify_native_execution_receipt_link",
            "_verify_python_handoff_link", "_verify_python_admission_attempt_anchor", "_admission_attempt_anchor")),
        # The public stage/commit entry points are deliberately disabled by the private
        # BRS policy (online_publication=false).  They may be replaced by inert test
        # guards without changing the retained recovery reader.  Keep the underlying
        # commit helpers pinned because those helpers are still part of the read-only
        # native evidence projection and can affect recovery semantics.
        *((getattr(producer_bundle_staging, name), producer_bundle_staging) for name in (
            "_commit_producer_bundle_publication", "_commit_original_brs_producer_bundle_publication")),
        (control_binding, contextlib),
        (control_implementation, producer_bundle_control),
        (producer_bundle_control.native_producer_bundle_budget_sha256, producer_bundle_control),
        (rsi_controller.RSILearningController._pin_python_admission_for_original_brs_owner, rsi_controller),
        (producer_process.parse_producer_execution_receipt, producer_process),
        (producer_bundle_deadline.persist_controlled_producer_bundle_intent, producer_bundle_deadline),
    )
    if any(type(function) is not FunctionType or function.__globals__ is not vars(module)
           for function, module in entries):
        _fail("native_reader_globals_drift")
    journal_defaults = producer_request_transport.read_host_request_journal.__kwdefaults__
    if (type(journal_defaults) is not dict or any(type(key) is not str for key in journal_defaults)
            or set(journal_defaults) != {"deadline", "monotonic", "expected_file_identity"}
            or journal_defaults["deadline"] is not None or journal_defaults["expected_file_identity"] is not None
            or journal_defaults["monotonic"] is not time.monotonic):
        _fail("native_reader_binding_drift")

    return {
        "protocol": _PROTOCOL, "mode": "brs", "max_workers": 1,
        "rejection_schema": rejection_wire.REJECTION_SCHEMA,
        "rejection_provenance_schema": rejection_wire.REJECTION_PROVENANCE_SCHEMA,
        "production_admission": False, "online_publication": False,
        "max_batches": MAX_LINEAGE_BATCHES,
        "max_checkpoint_bytes": lineage._MAX_CHECKPOINT_BYTES,
        "max_aggregate_snapshot_bytes": MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
        "dependencies": {
            # Evaluate the complete finite live graph on every observation, then
            # retain its digest once. Persisting the expanded graph in each run
            # fingerprint would duplicate it beyond the unchanged record cap.
            "rejection_provenance": hashlib.sha256(canonical_json({
                "owner_helpers": {name: component_fingerprint(getattr(provenance, name))
                                  for name in provenance_helpers},
                "policy_helpers": {name: component_fingerprint(function) for function, module in entries
                                   if module is provenance_policy for name in (function.__name__,)},
                "native": provenance_policy.native_rejection_provenance_policy(),
                "fields": [provenance._FIELD, provenance.REJECTION_PROVENANCE_SCHEMA,
                           provenance.NATIVE_RSI_REJECTION_PROVENANCE_NAME],
                "sources": {name: hashlib.sha256(_files.read_regular_file(
                    Path(__file__).parent / name, 1024 * 1024)).hexdigest() for name in (
                        "rsi_brs_rejection_provenance.py", "rsi_brs_rejection_provenance_policy.py",
                        "rsi_native_scheduler.py")},
            })).hexdigest(),
            "rejection_ready_capture": ready_policy.rejection_ready_capture_policy(),
            "rejection_c1": {
                "owner_methods": {name: component_fingerprint(getattr(rejection_owner, name))
                                  for name in ("_fail", *rejection_methods)},
                "wire_helpers": {name: component_fingerprint(function) for function, module in entries
                                 if module is rejection_wire for name in (function.__name__,)},
                "capacity_helpers": {name: component_fingerprint(function) for function, module in entries
                                     if module is rejection_capacity for name in (function.__name__,)},
                "descriptor_helpers": [component_fingerprint(function) for function, module in entries
                                       if module is producer_bundle_lineage_v2],
                "native_helpers": {name: [component_fingerprint(function) for function, module in entries
                                         if module is canonical] for name, canonical in (
                                             ("rejection", producer_bundle_rejection),
                                             ("receipts", producer_bundle_receipts))},
                "native_intent": component_fingerprint(producer_bundle_staging.verify_native_publication_intent),
                "final_readers": {name: [component_fingerprint(function, config={} if module is contextlib else None)
                                         for function, module in entries if module is canonical]
                                  for name, canonical in (("ledger", rsi_store), ("controller", rsi_controller),
                                                          ("contextmanager", contextlib))},
                "ready_helpers": [component_fingerprint(function) for function, module in entries
                                  if module is rsi_producer_staging_capsule],
                "source_control": {name: [component_fingerprint(function) for function, module in entries if module is canonical]
                                   for name, canonical in (("budget", rsi_budget), ("fingerprint", rsi_fingerprint))},
                "shape": component_fingerprint(rsi_python_admission.validate_rsi_python_admission_shapes),
                "fields": [sorted(rejection_wire._BASE_FIELDS), sorted(rejection_wire._REJECTED_FIELDS),
                           sorted(rejection_wire._PROVENANCE_FIELDS)],
                "owner_field": rejection_owner._FIELD,
                "native_fields": {module.__name__.rsplit(".", 1)[-1]: {name: sorted(getattr(module, name)) for name in names}
                                  for module, names in native_sets},
                "native_patterns": [[value.pattern, value.flags] for value in native_patterns],
                "native_protocols": list(native_protocols),
                "native_limits": list(native_limits),
                "capacity_protocols": [rejection_capacity._BRS_PROTOCOL, rejection_capacity._REJECTION_SCHEMA,
                                       rejection_capacity.READY_CAPSULE_PROTOCOL, rejection_capacity._LINEAGE_FIELD,
                                       rejection_wire._BRS_PROTOCOL, rejection_wire.REJECTION_PROVENANCE_SCHEMA],
                "capacity_limits": [rejection_capacity._MAX_INT,
                                    rejection_capacity.MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
                                    rejection_capacity.MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES,
                                    rsi_native_rejection.MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES],
                "capacity_fields": list(rejection_capacity._OBSERVATION_FIELDS),
                "capacity_pattern": rejection_capacity._IDENTIFIER.pattern,
                "capacity_pattern_flags": rejection_capacity._IDENTIFIER.flags,
                "module_sources": {name: hashlib.sha256(_files.read_regular_file(
                    Path(__file__).parent / name, 1024 * 1024)).hexdigest() for name in (
                        "rsi_brs_rejection_owner.py", "rsi_brs_rejection_c1.py", "rsi_brs_rejection_capacity.py",
                        "producer_bundle_lineage_v2.py", "producer_bundle_rejection.py",
                        "producer_bundle_receipts.py", "rsi_native_rejection.py", "rsi_budget.py", "rsi_fingerprint.py")},
            },
            "policy": component_fingerprint(_policy),
            "failure": component_fingerprint(_fail),
            "selection": component_fingerprint(_policy_required),
            "run_policy": component_fingerprint(_run_policy),
            "persisted_policy": component_fingerprint(_validate_persisted_policy),
            "native_shape": component_fingerprint(_native_shape),
            "native_snapshot": component_fingerprint(_native_snapshot),
            "family_repertoires": {"reader": component_fingerprint(_family_repertoires),
                                   "value": _family_repertoires()},
            "module_sources": {name: hashlib.sha256(_files.read_regular_file(Path(__file__).parent / name, 1024 * 1024)).hexdigest()
                               for name in ("rsi_brs_publication_lineage.py", "rsi_publication_lineage.py",
                                            "rsi_controller.py", "rsi_store.py", "rsi_brs_reconcile.py",
                                            "rsi_brs_mailbox_evidence.py", "rsi_brs_native_process_evidence.py",
                                            "rsi_brs_terminal_evidence.py", "rsi_python_brs_terminal_lifecycle.py",
                                            "_candidate_workspace_io.py",
                                            "rsi_python_brs_owner_bridge.py", "producer_bundle_lineage.py",
                                            "producer_bundle_admission.py", "producer_bundle_publication.py",
                                            "rsi_python_admission.py", "rsi_python_brs_handoff.py",
                                            "rsi_producer_staging_capsule.py", "producer_bundle_recovery.py",
                                            "producer_bundle_staging.py", "evolution.py", "algorithm.py",
                                            "candidate_bundle.py", "producer_bundle_transaction.py",
                                            "rsi_python_scheduler_inputs.py",
                                            "rsi_python_brs_publication_recovery.py",
                                            "rsi_python_brs_publication_inputs.py",
                                            "rsi_python_brs_publication_mailbox.py", "rsi_native_plan.py",
                                            "rsi_python_brs_result_delivery.py", "candidate_evaluation_spec.py",
                                            "rsi_python_brs_native_dispatch.py", "producer_bundle_control.py",
                                            "producer_bundle_deadline.py",
                                            "rsi_gateway.py", "rsi_python_brs_admission.py",
                                            "automatic_solve_lifecycle.py", "native_trusted_scheduler.py",
                                            "native_trusted_output.py", "native_trusted_receipt.py",
                                            "native_trusted_capture.py", "native_trusted_attempt.py",
                                            "native_trusted_streams.py", "native_trusted_cleanup.py",
                                            "_benchmark_files.py", "bundle_evolution.py",
                                            "native_bootstrap.py", "producer_bootstrap.py",
                                            "producer_launcher.py", "producer_process.py",
                                            "producer_bundle_handoff.py", "producer_bundle_population.py",
                                            "producer_bundle_preflight.py",
                                            "producer_handoff.py", "producer_request_transport.py",
                                            "python_producer_admission_handoff.py")},
            "retained_native_reader": {
                "methods": {name: component_fingerprint(getattr(
                    rsi_python_brs_publication_recovery._BRSRetainedNativePreparationReader, name))
                    for name in ("__init__", "_scope", "_check", "_project", "recover")},
                "helpers": {name: component_fingerprint(getattr(rsi_python_brs_publication_recovery, name))
                    for name in ("_fail", "_copy", "_comparison_preparation", "_arguments", "_dto_policy", "_control_pin")},
                "dto_types": reader._dto_policy(),
                "projector": component_fingerprint(rsi_python_brs_publication_inputs._request_from_native_preparation),
                "projector_binding": component_fingerprint(
                    rsi_python_brs_publication_recovery._request_from_native_preparation),
                "context_binding": component_fingerprint(rsi_python_brs_publication_recovery._context),
                "request_binding": component_fingerprint(rsi_python_brs_publication_recovery._request),
                "control_pin": component_fingerprint(rsi_python_brs_publication_recovery._prepublication_control_pin),
                "control_check": component_fingerprint(rsi_python_brs_publication_recovery.SolveExecutionControl.check),
                "control_cancelled": component_fingerprint(rsi_python_brs_publication_recovery.SolveExecutionControl.is_cancelled),
                "control_clock": component_fingerprint(rsi_python_brs_publication_recovery.SolveExecutionControl._now),
                "control_finite_time": component_fingerprint(automatic_solve_lifecycle._finite_time),
                "control_stage_name": component_fingerprint(automatic_solve_lifecycle._stage_name),
                "channel": component_fingerprint(rsi_python_brs_publication_recovery.BRSAdmissionChannel, config={}),
                "recovery_binding": component_fingerprint(
                    rsi_python_brs_publication_recovery.recover_native_trusted_producer),
                "handoff_binding": component_fingerprint(
                    rsi_python_brs_publication_recovery.read_python_producer_admission_handoff_pinned),
                "native_recovery": component_fingerprint(native_trusted_scheduler.recover_native_trusted_producer),
                "native_receipt_binding": component_fingerprint(
                    native_trusted_scheduler.recover_native_trusted_execution_receipt),
                "native_output_binding": component_fingerprint(native_trusted_scheduler.prepare_native_trusted_output),
                "output": component_fingerprint(native_trusted_output.prepare_native_trusted_output),
                "output_receipt_binding": component_fingerprint(
                    native_trusted_output.recover_native_trusted_execution_receipt),
                "output_capture_binding": component_fingerprint(
                    native_trusted_output.recover_native_trusted_output_capture),
                "output_terminal_binding": component_fingerprint(native_trusted_output.recover_native_trusted_attempt),
                "receipt": component_fingerprint(native_trusted_receipt.recover_native_trusted_execution_receipt),
                "receipt_projection": component_fingerprint(native_trusted_receipt.build_native_trusted_execution_receipt),
                "receipt_terminal": component_fingerprint(native_trusted_receipt.recover_native_trusted_attempt),
                "receipt_streams": component_fingerprint(native_trusted_receipt.recover_native_trusted_stream_capture),
                "receipt_cleanup": component_fingerprint(native_trusted_receipt.recover_native_trusted_cleanup),
                "receipt_capture": component_fingerprint(native_trusted_receipt.recover_native_trusted_output_capture),
                "output_manifest": component_fingerprint(native_trusted_output.prepare_producer_bundle_manifest),
                "output_drafts": component_fingerprint(native_trusted_output.prepare_producer_bundle_drafts),
                "output_admission": component_fingerprint(native_trusted_output.build_producer_bundle_admission_plan),
                "output_read_envelope": component_fingerprint(native_trusted_output._read_envelope),
                "output_parse_envelope": component_fingerprint(native_trusted_output.parse_producer_envelope),
                "broker_journal": component_fingerprint(native_trusted_capture.read_host_request_journal,
                    config={"deadline": None, "expected_file_identity": None, "monotonic": "time.monotonic"}),
                "capture": component_fingerprint(native_trusted_capture.recover_native_trusted_output_capture),
                "handoff": component_fingerprint(
                    python_producer_admission_handoff.read_python_producer_admission_handoff_pinned),
            },
            "private_native_dispatch": {
                "helpers": {name: component_fingerprint(getattr(dispatch, name)) for name in (
                    "_fail", "_original_control", "_fixed_original_brs_owner", "_original_brs_numeric_tail",
                    "_call_original_brs_owner", "_run_original_brs_native_publication")},
                "transaction": {name: component_fingerprint(getattr(transaction, name)) for name in (
                    "_validate_native_lineage_scope", "_native_lineage_call", "derive_population_state_after",
                    "_derive_population_state_after", "_run_bound_native_producer_bundle_publication_transaction",
                    "_run_native_producer_bundle_publication_transaction", "_verify_native_execution_receipt_link",
                    "_verify_python_handoff_link", "_verify_python_admission_attempt_anchor", "_admission_attempt_anchor")},
                "staging": {name: component_fingerprint(getattr(producer_bundle_staging, name)) for name in (
                    "_commit_producer_bundle_publication", "_commit_original_brs_producer_bundle_publication")},
                "control_binding": component_fingerprint(control_binding, config={}),
                "control_implementation": component_fingerprint(control_implementation),
                "budget": component_fingerprint(producer_bundle_control.native_producer_bundle_budget_sha256),
                "deadline": component_fingerprint(producer_bundle_deadline.persist_controlled_producer_bundle_intent),
                "prepared_pin": component_fingerprint(
                    rsi_controller.RSILearningController._pin_python_admission_for_original_brs_owner),
                "receipt_parser": component_fingerprint(producer_process.parse_producer_execution_receipt),
            },
            "owner": component_fingerprint(_BRSLineageCheckpointOwner, config={}),
            "mailbox_recovery_evidence": {
                "owner_append": component_fingerprint(_retain_mailbox_observation),
                "owner_fixed_tail": component_fingerprint(_mailbox_fixed_tail),
                "methods": {
                    name: [component_fingerprint(function) for function, canonical_module in entries
                           if canonical_module is module]
                    for name, module in (("mailbox_schema", mailbox_evidence), ("native_process", process_evidence))
                },
                "protocols": [mailbox_evidence.BINDING_PROTOCOL, mailbox_evidence.OBSERVATION_PROTOCOL,
                              process_evidence.PROTOCOL, process_evidence.ROLE],
                "stages": list(mailbox_evidence.STAGES),
                "limits": [mailbox_evidence.MAX_BRS_MAILBOX_EVIDENCE_BYTES, process_evidence._MAX,
                           process_evidence._MAX_FILE],
                "process_shapes": {name: sorted(getattr(process_evidence, name)) for name in (
                    "_FIELDS", "_REF_FIELDS", "_PIN_FIELDS", "_REASONS")},
                "process_entries": list(process_evidence._NAMES),
                "observation_shapes": {name: sorted(getattr(mailbox_evidence, name)) for name in (
                    "_BINDING_FIELDS", "_OBSERVATION_FIELDS", "_MESSAGE_DIGESTS")},
                "process_patterns": [process_evidence._SHA.pattern, process_evidence._ID.pattern],
                "mailbox_pattern": mailbox_evidence._SHA.pattern,
                "observer_snapshot": component_fingerprint(
                    rsi_python_brs_publication_mailbox.BRSOwnerPublicationMailbox._observation_snapshot),
                "store": component_fingerprint(rsi_store.RSILedger.append_brs_mailbox_observation),
                "native_dependencies": {name: component_fingerprint(function) for name, function in (
                    ("cleanup", native_trusted_cleanup.verify_native_trusted_cleanup),
                    ("launch", producer_bootstrap.build_trusted_bootstrap_launch),
                    ("registration", producer_bootstrap.verify_trusted_bootstrap_process_registration),
                    ("owner_identity", producer_process._process_owner_identity),
                )},
                "directory_methods": {name: component_fingerprint(getattr(_candidate_workspace_io.DirectoryChain, name))
                                      for name in ("__init__", "check", "close")},
                "directory_fd": component_fingerprint(_candidate_workspace_io.DirectoryChain.fd.fget),
                "directory_flags": _candidate_workspace_io._FLAGS,
                "directory_helpers": {name: component_fingerprint(getattr(_candidate_workspace_io, name))
                                      for name in ("fail", "identity")},
            },
            "owner_result_delivery": {
                "helpers": {name: component_fingerprint(getattr(delivery, name)) for name in (
                    "_fail", "_id", "_sha", "_shape", "_canonical_payload", "_journal",
                    "build_brs_owner_result_payload", "deliver_brs_owner_result")},
                "dto": component_fingerprint(delivery.BRSOwnerResultDelivery, config={}),
                "settlement": component_fingerprint(delivery.BRSOwnerResultSettlement, config={}),
                "journal": component_fingerprint(producer_bundle_publication.ProducerBundlePublicationJournal, config={}),
                "candidate": component_fingerprint(producer_bundle_publication.ProducerBundlePublicationCandidate, config={}),
                "bridge_builder": component_fingerprint(rsi_python_brs_owner_bridge.build_brs_owner_result_payload),
                "canonical": {name: component_fingerprint(getattr(candidate_evaluation_spec, name))
                              for name in ("canonical_json", "strict_json", "_fail", "_maximum", "_json_bytes")},
                "journal_helpers": {name: component_fingerprint(getattr(producer_bundle_publication, name)) for name in (
                    "_fail", "_digest", "_identifier", "_optional_identifier", "_canonical", "_object",
                    "_bounded_int", "parse_producer_bundle_publication_journal")},
                "request_helpers": {name: component_fingerprint(getattr(rsi_python_brs_publication_mailbox, name))
                                    for name in ("_identity", "_sha", "_shape", "_payload", "_request_payload", "_digest",
                                                 "build_brs_owner_publication_response")},
                "handoff_helpers": {name: component_fingerprint(getattr(rsi_python_brs_handoff, name))
                                    for name in ("_fail", "_identity", "_digest", "_int")},
                "projection_methods": {
                    name: [component_fingerprint(function) for function, canonical_module in entries
                           if canonical_module is module]
                    for name, module in (
                        ("result_delivery", delivery), ("publication_journal", producer_bundle_publication),
                        ("selected_handoff", rsi_python_brs_handoff),
                        ("publication_mailbox", rsi_python_brs_publication_mailbox),
                        ("canonical_json", candidate_evaluation_spec),
                        ("admission_file_pin", python_producer_admission_handoff),
                    )
                },
                "protocol": delivery._PROTOCOL,
                "statuses": sorted(delivery._STATUSES),
                "fields": sorted(delivery._FIELDS),
                "max_bytes": delivery.MAX_BRS_OWNER_RESULT_BYTES,
                "identity_pattern": delivery._ID.pattern,
                "identity_flags": delivery._ID.flags,
                "digest_pattern": delivery._SHA.pattern,
                "digest_flags": delivery._SHA.flags,
            },
            "terminal_recovery": {
                "methods": [component_fingerprint(function) for function, module in entries if module is terminal],
                "protocols": [terminal.BINDING_PROTOCOL, terminal.OBSERVATION_PROTOCOL],
                "stages": list(terminal.STAGES),
                "max_bytes": terminal.MAX_BRS_TERMINAL_EVIDENCE_BYTES,
                "fields": [sorted(terminal._BINDING_FIELDS), sorted(terminal._OBSERVATION_FIELDS)],
                "pattern": terminal._SHA.pattern,
                "pattern_flags": terminal._SHA.flags,
                "store": {name: component_fingerprint(getattr(rsi_store.RSILedger, name)) for name in (
                    "append_brs_terminal_observation", "read_brs_terminal_evidence_snapshot",
                    "_brs_terminal_evidence_snapshot_tx", "_consume_brs_reconcile_obligation")},
                "controller": component_fingerprint(rsi_controller.RSILearningController.reconcile_brs_terminal),
                "composer_methods": [component_fingerprint(function) for function, module in entries if module is composer],
                "composer_protocol": composer.PROTOCOL,
                "composer_max_bytes": composer.MAX_BRS_TERMINAL_REPORT_BYTES,
                "composer_fields": [sorted(composer._PIN_FIELDS), sorted(composer._REPORT_FIELDS),
                                    sorted(composer._TERMINAL_STATUSES)],
                "composer_pattern": composer._SHA.pattern,
                "composer_pattern_flags": composer._SHA.flags,
                "stdlib_methods": {name: component_fingerprint(function) for name, function in (
                    *(("future_" + name, getattr(Future, name)) for name in ("done", "running", "exception", "result")),
                    ("shutdown", ThreadPoolExecutor.shutdown), ("thread_alive", threading.Thread.is_alive),
                    ("current_thread", threading.current_thread),
                    *(("condition_" + name, getattr(threading.Condition, name))
                      for name in ("wait", "notify_all", "__enter__", "__exit__")),
                )},
                "publication_readers": {name: component_fingerprint(function) for name, function in (
                    ("recovery", recovery.resume_producer_bundle_publication),
                    ("descriptor", producer_bundle_lineage.read_lineage_descriptor_pinned),
                    ("episode_read", PracticeEpisode.from_dict.__func__),
                    ("episode_write", PracticeEpisode.to_record_dict),
                )},
            },
            "reconcile_registration": {
                "helpers": {name: component_fingerprint(getattr(rsi_brs_reconcile, name)) for name in (
                    "register_brs_selected_obligation", "put_brs_reconcile_obligation",
                    "validate_brs_reconcile_obligations")},
                "store": {name: component_fingerprint(getattr(rsi_store.RSILedger, name)) for name in (
                    "write_brs_reconcile_obligation", "_append_controller_checkpoint_tx",
                    "controller_checkpoint_history", "_controller_checkpoint_history_tx", "_native_result_status",
                    "_native_claim_row")},
                "bridge": {name: component_fingerprint(getattr(rsi_python_brs_owner_bridge, name)) for name in (
                    "run_brs_owner_publication_mailbox", "_require_original_mailbox", "_require_disabled_policy",
                    "_original_control", "_run_original_brs_native_publication", "_response_payload")},
            },
            "methods": {name: component_fingerprint(getattr(_BRSLineageCheckpointOwner, name)) for name in (
                "__init__", "_identity", "_check_owner", "_running", "_before_entry", "_write",
                "checkpoint_before", "acknowledge_prepared", "_accept_prepared_reference",
                "_native_strategy", "_strategy_identity", "_history", "_success_entry",
                "_initial_window", "_candidate_materials", "_verify_staged_projection",
                "checkpoint_staged", "checkpoint_terminal",
                "validate_before", "retain_before", "_before_unlocked", "_before_channel", "_live_before", "_before_wire",
                "_before_control_state", "_before_control_live",
                "retain_staged", "verify_precommit", "retain_terminal",
                "_success_observe", "_success_fixed", "_success_capacity", "_success_scope",
                "_success_control_live", "_success_allowance",
                "_success_cap_unchanged",
                "retain_reconcile_obligation", "_reconcile_registration_observe", "_reconcile_registration_readback",
                "_reconcile_registration_fixed",
                "retain_mailbox_observation", "_mailbox_native_arguments", "_mailbox_process_unchanged",
                "_mailbox_readback",
            )},
            "readers": {name: component_fingerprint(getattr(lineage._LineageEvidenceReader, name)) for name in (
                "_is_v2", "_validate_entry_shape", "_validate_source_pin_maps", "_verify_descriptor", "_snapshot_bytes",
                "_verify_terminal_entry", "_verify_transition_projection",
            )},
            "checkpoint_delta": component_fingerprint(lineage._publication_lineage_checkpoint_delta),
            "checkpoint_readback": component_fingerprint(lineage._validate_publication_lineage_checkpoint_readback),
            "root_pin": component_fingerprint(lineage._root_pin),
            "source_pin_check": component_fingerprint(lineage.RSIPublicationLineage._verify_before_source_pins),
            "after_source_pin_check": component_fingerprint(lineage.RSIPublicationLineage._verify_after_source_pins),
            "marker_absence": component_fingerprint(lineage._require_marker_absent),
            "native_context_reader": component_fingerprint(_context),
            "native_context_helpers": {name: component_fingerprint(getattr(scheduler_inputs, name)) for name in (
                "_checkpoint", "_sidecar", "_native", "_projection", "_shape", "_broker", "_request_memory", "_path",
            )},
            "population_projection": {name: component_fingerprint(getattr(PopulationStrategy, name)) for name in (
                "_reconstruct_population_projection", "_producer_admission_events", "_apply_producer_admissions",
                "_trim", "_capacity", "_candidates", "_rank", "_family_elites", "_candidate_family",
            )},
            "population_serializers": {
                "config": component_fingerprint(EvolutionConfig.to_dict),
                "authority": component_fingerprint(CandidateIntegrityAuthority.to_dict),
                "novelty": component_fingerprint(evolution._novelty),
                "tokens": component_fingerprint(evolution._tokens),
                "archive_reader": component_fingerprint(_records_from_archive),
                "seed_predicate": component_fingerprint(CandidateArchive._is_seed_candidate),
                "candidate_read": component_fingerprint(Candidate.from_dict, config={}),
                "candidate_write": component_fingerprint(Candidate.to_dict),
                "bundle_read": component_fingerprint(parse_candidate_source_bundle),
                "bundle_digest": component_fingerprint(CandidateSourceBundle.digest),
                "contract_digest": component_fingerprint(AlgorithmProblemContract.digest),
                "contract_canonical": component_fingerprint(AlgorithmProblemContract.canonical_json),
                "contract_serializers": {kind.__name__: component_fingerprint(kind.to_dict) for kind in (
                    AlgorithmProblemContract, ConstraintSpec, EvolutionSpec, InputSpec,
                    MetricSpec, ObjectiveSpec, OutputSpec, SourceCheckSpec,
                )},
            },
            "recovery": {name: component_fingerprint(getattr(recovery, name)) for name in (
                "_batch", "_read_json", "_read_journal", "_check_preflight", "_manifest",
                "_verify_python_handoff", "_verify_manifest_files", "_verify_terminal_batch_evidence", "_marker", "_path",
            )},
            "shape_check": component_fingerprint(lineage._publication_shapes),
            "admission_parser": component_fingerprint(parse_producer_bundle_admission_plan),
            "journal_parser": component_fingerprint(parse_producer_bundle_publication_journal),
            "capture_pin": component_fingerprint(capture_lineage_snapshot_pin),
            "verify_pin": component_fingerprint(verify_persisted_lineage_snapshot),
            "before_persistence": {name: component_fingerprint(getattr(producer_bundle_lineage, name)) for name in (
                "persist_lineage_bytes_snapshot", "persist_lineage_snapshot", "persist_lineage_descriptor",
                "_create_lineage_file", "_observe_file", "verify_lineage_snapshot_pin",
            )},
            "before_population": {name: component_fingerprint(getattr(PopulationStrategy, name)) for name in (
                "_validate_candidate_integrity_state", "_active",
            )},
            "before_prefix": component_fingerprint(compute_archive_prefix_digest),
            "before_handoff": component_fingerprint(read_python_producer_admission_handoff_pinned),
            "success_native": {
                "marker_helpers": {name: component_fingerprint(getattr(producer_bundle_staging, name)) for name in (
                    "_load_marker", "_check_held_publication_lock", "_read", "_sha", "_canonical", "_marker_bytes", "_pretty", "_fail")},
                "manifest_write": component_fingerprint(producer_bundle_staging.ProducerBundlePublicationManifest.to_dict),
                "manifest_digest": component_fingerprint(producer_bundle_staging.ProducerBundlePublicationManifest.digest),
            },
            "shared_retained_bytes": component_fingerprint(lineage.RSIPublicationLineage._retained_bytes),
        },
    }


def _mailbox_native_arguments(self) -> dict[str, Any]:
    """Use the original native context; never infer a BRS worker process."""
    from .rsi_python_brs_publication_recovery import _arguments

    arguments = {"workspace": self._workspace, "native_plan": self._plan}
    if self._native is not None:
        retained = _arguments(self)
        arguments.update({name: retained[name] for name in ("workspace", "intent", "attestation", "artifact")})
    return arguments

def _mailbox_process_unchanged(self, binding: dict[str, Any]) -> None:
    from .rsi_brs_native_process_evidence import observe_native_process_binding

    observed = observe_native_process_binding(
        binding["capture"]["native_process"], **self._mailbox_native_arguments(),
    )
    if observed["status"] == "drifted":
        _fail("mailbox_native_binding_drift")

def _mailbox_readback(self, namespace: str, expected: list, binding: dict[str, Any]) -> None:
    from .rsi_brs_mailbox_evidence import validate_brs_mailbox_history

    with self._ledger.read_only_observations():
        actual = self._ledger.controller_checkpoint_history(namespace)
        root = self._ledger.controller_checkpoint_history(self._run_id)
    if actual != expected or not root or root[-1] != (self._head, json.loads(self._payload)):
        _fail("mailbox_observation_readback_invalid")
    validate_brs_mailbox_history(actual, binding=binding)


def _mailbox_fixed_tail(self) -> None:
    """Last original numeric/lease/channel check, without observing source hooks."""
    from .rsi_python_brs_native_dispatch import _original_brs_numeric_tail

    _original_brs_numeric_tail(self)
    _BRSLineageCheckpointOwner._success_allowance(self)
    RSIRunBudget.load(self._wave.budget_state).check()
    if self._before_control is not None and time.monotonic() >= self._before_control.deadline:
        _fail("mailbox_observation_deadline_exhausted")


def _retain_mailbox_observation(
    self, stage: str, *, mailbox_state: str, worker_receipt_observed: bool,
    request: object = None, response: object = None,
) -> str:
    """Append an adjacent original-owner observation, without advancing root.

    The acknowledged side cursor stays old on every uncertain append or
    readback. Such failures poison the ephemeral owner and retain its fence.
    """
    from .rsi_brs_mailbox_evidence import (
        brs_mailbox_evidence_namespace,
        build_brs_mailbox_binding,
        build_brs_mailbox_observation,
        parse_brs_mailbox_binding,
    )
    from .rsi_brs_native_process_evidence import capture_native_process_binding
    from .rsi_brs_reconcile import FIELD, BRSReconcileObligation

    if type(self) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    try:
        self._success_observe()
        if stage == "owner_capture":
            if self._mailbox_capture_started is not False or self._mailbox_binding_bytes is not None:
                _fail("mailbox_capture_unavailable")
            self._mailbox_capture_started = True
            obligation = BRSReconcileObligation.from_dict(self._state[FIELD][self._request.episode_id])
            binding = build_brs_mailbox_binding(
                obligation=obligation, handoff=self._handoff,
                run_record_sha256=self._run_head, episode_record_sha256=self._episode_head,
                native_process=capture_native_process_binding(**self._mailbox_native_arguments()),
            )
        else:
            if self._mailbox_capture_started is not True or type(self._mailbox_binding_bytes) is not bytes:
                _fail("mailbox_capture_required")
            binding = parse_brs_mailbox_binding(json.loads(self._mailbox_binding_bytes))
        history = [tuple(item) for item in json.loads(self._mailbox_history_bytes)]
        namespace = brs_mailbox_evidence_namespace(binding)
        record = build_brs_mailbox_observation(
            binding, stage=stage, root_checkpoint_sha256=self._head,
            mailbox_state=mailbox_state, worker_receipt_observed=worker_receipt_observed,
            request=request, response=response,
        )
        self._mailbox_process_unchanged(binding)
        self._success_observe()
        root_head = self._head
        with self._ledger.controller_lock(namespace):
            self._mailbox_readback(namespace, history, binding)
            _mailbox_fixed_tail(self)
            head = self._ledger.append_brs_mailbox_observation(
                binding, record, expected_sha256=None if not history else history[-1][0],
            )
            expected = [*history, (head, record)]
            self._mailbox_readback(namespace, expected, binding)
        self._mailbox_process_unchanged(binding)
        self._success_observe()
        if self._head != root_head:
            _fail("mailbox_observation_root_drift")
        self._mailbox_readback(namespace, expected, binding)
        _mailbox_fixed_tail(self)
        self._mailbox_binding_bytes = lineage._raw(binding)
        self._mailbox_history_bytes = lineage._raw(expected)
        return head
    except BaseException:
        self._poisoned = True
        raise


class _BRSLineageCheckpointOwner(lineage._LineageEvidenceReader):
    """Exact original BRS owner for bounded first-batch success checkpoints.

    Caller-owned wire is checked against genuine descriptor/snapshot/source files
    and the original request/claim/plan. No arbitrary lineage delta, DRS context,
    completed result, rejection event or latest-head refresh is accepted.
    Instances are ephemeral and cannot be reconstructed from retained evidence.
    """

    __slots__ = (
        "_association",
        "_before_bytes",
        "_before_cancelled",
        "_before_channel_condition",
        "_before_control",
        "_before_control_pin",
        "_budget_bytes",
        "_channel",
        "_claim",
        "_controller",
        "_episode_head",
        "_gateway",
        "_handoff",
        "_handoff_bytes",
        "_head",
        "_ledger",
        "_mailbox_binding_bytes",
        "_mailbox_capture_started",
        "_mailbox_history_bytes",
        "_memory",
        "_native",
        "_native_config",
        "_native_inputs",
        "_payload",
        "_phase",
        "_plan",
        "_poisoned",
        "_policy_bytes",
        "_prepared",
        "_provided_memory",
        "_provided_plan",
        "_provided_request",
        "_reconcile_registration_started",
        "_rejection_c1_capture",
        "_rejection_deadline",
        "_rejection_file_pin",
        "_rejection_ledger_identity",
        "_rejection_provenance_c2_capture",
        "_rejection_provenance_deadline",
        "_rejection_provenance_evidence",
        "_rejection_provenance_file_pin",
        "_rejection_provenance_sha256",
        "_rejection_ready_ack",
        "_rejection_ready_ack_fields",
        "_rejection_ready_capture",
        "_rejection_ready_capture_started",
        "_rejection_ready_commit_started",
        "_rejection_ready_final_capture",
        "_rejection_ready_locks_capture",
        "_rejection_ready_stage",
        "_rejection_ready_state",
        "_rejection_ready_sync_capture",
        "_request",
        "_retaining_before",
        "_retaining_rejection",
        "_retaining_rejection_provenance",
        "_retaining_success",
        "_run_head",
        "_run_id",
        "_selected_context",
        "_selected_context_bytes",
        "_sidecar",
        "_state",
        "_strategy",
        "_strategy_archive",
        "_strategy_authority",
        "_strategy_bytes",
        "_strategy_config",
        "_strategy_context",
        "_strategy_contract",
        "_success_deadline",
        "_thread",
        "_validated_before",
        "_wave",
        "_workspace",
    )

    def __init__(self, controller: Any, wave: Any, *, request: SolverRequest,
                 memory: MemorySnapshot, native_plan: NativeRSIExecutionPlan) -> None:
        from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
        from .rsi_python_admission import validate_rsi_python_admission_shapes
        from .rsi_python_brs_handoff import BRSChildHandoffContext, BRSSelectedChildHandoff
        from .rsi_python_scheduler_inputs import _request_memory
        from .rsi_store import RSILedger

        if (type(self) is not _BRSLineageCheckpointOwner or type(controller) is not RSILearningController
                or type(wave) is not _PythonAdmissionBRSWave or type(controller.ledger) is not RSILedger):
            _fail("owner_invalid")
        controller._python_admission_assert_brs_wave(wave, owner=True)
        handoff, context = wave.selected_handoff, wave.selected_context
        if type(handoff) is not BRSSelectedChildHandoff or type(context) is not BRSChildHandoffContext:
            _fail("selection_required")
        controller._python_admission_selected_brs_identity(wave, handoff)
        parsed_request, parsed_memory = _request_memory(request, memory)
        validate_rsi_python_admission_shapes(native_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
        if type(native_plan) is not NativeRSIExecutionPlan:
            _fail("plan_invalid")
        plan = NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(native_plan))
        if (plan.request != parsed_request or plan.memory_snapshot_sha256 != parsed_memory.digest()
                or parsed_request.digest() != handoff.request_sha256 or plan.run_id != wave.run_id
                or parsed_memory.digest() != handoff.root_snapshot_sha256 or handoff.ordinal != 0):
            _fail("inputs_invalid")
        previous = getattr(controller._python_admission_brs_local, "lineage_checkpoint_owner", None)
        if type(previous) is _BRSLineageCheckpointOwner and previous._wave is wave:
            _fail("owner_already_created")
        self._controller, self._wave, self._state = controller, wave, wave.state
        self._ledger, self._gateway = controller.ledger, controller.gateway
        self._workspace, self._sidecar, self._thread = wave.workspace, wave.sidecar, get_ident()
        self._channel, self._handoff, self._selected_context = wave.channel, handoff, context
        self._before_channel_condition = self._channel._condition
        self._budget_bytes = controller._python_admission_flow_payload(wave.budget_state)
        self._handoff_bytes = BRSSelectedChildHandoff.canonical_bytes.fget(handoff)
        self._selected_context_bytes = canonical_json(BRSChildHandoffContext.to_dict(context))
        self._provided_request, self._provided_memory, self._provided_plan = request, memory, native_plan
        self._request, self._memory, self._plan = parsed_request, parsed_memory, plan
        self._run_id, self._head, self._payload = plan.run_id, wave.checkpoint_sha256, wave.payload
        self._policy_bytes = lineage._raw(_policy())
        with self._ledger.read_only_observations():
            original = self._ledger.history(self._run_id)[0]
            run = self._ledger.get_run(self._run_id)
            claim = self._ledger.inspect_native_episode_claim(parsed_request, plan_sha256=plan.plan_sha256)
            episode = self._ledger.get_episode(parsed_request.episode_id)
            result = self._ledger.episode_result(parsed_request.episode_id)
        if (run is None or run.state != "running" or episode is None or episode.state != "running"
                or claim is None or claim.status != "started" or result is not None
                or episode.request_sha256 != parsed_request.digest()):
            _fail("running_claim_required")
        self._run_head, self._claim, self._episode_head = run.record_sha256, claim, episode.record_sha256
        self._association = {
            "protocol": _PROTOCOL, "run_id": self._run_id, "workspace": lineage._root_pin(self._workspace),
            "run_request_sha256": original.request_sha256,
            "root_proof_sha256": lineage._sha(lineage._raw(original.payload.get("producer_checkpoint_binding"))),
            "policy_sha256": lineage._sha(self._policy_bytes), "max_batches": MAX_LINEAGE_BATCHES,
        }
        config = getattr(self._gateway, "producer_config", None)
        self._native_config = config
        self._native_inputs = self._native = self._strategy = None
        self._strategy_context = self._strategy_config = self._strategy_authority = None
        self._strategy_archive = self._strategy_contract = None
        self._strategy_bytes = None
        if config is not None:
            from .evolution import (
                CandidateIntegrityAuthority,
                EvolutionConfig,
                EvolutionContext,
                PopulationStrategy,
            )
            from .rsi_native_scheduler import NativeRSISchedulerContext
            from .rsi_producer_gateway import PythonProducerRSIExecutionConfig
            from .rsi_python_scheduler_inputs import PythonRSISchedulerInputContext

            if (type(config) is not PythonProducerRSIExecutionConfig or config.ledger is not self._ledger
                    or type(config.inputs) is not PythonRSISchedulerInputContext
                    or type(config.inputs.native_context) is not NativeRSISchedulerContext
                    or type(config.inputs.native_context.strategy) is not PopulationStrategy):
                _fail("native_strategy_invalid")
            self._native_inputs, self._native = config.inputs, config.inputs.native_context
            self._strategy = self._native.strategy
            self._strategy_context, self._strategy_config = self._strategy.context, self._strategy.config
            self._strategy_authority = self._strategy.integrity_authority
            if (type(self._strategy_context) is not EvolutionContext
                    or type(self._strategy_config) is not EvolutionConfig
                    or type(self._strategy_authority) is not CandidateIntegrityAuthority):
                _fail("native_strategy_invalid")
            self._strategy_archive, self._strategy_contract = self._strategy.archive, self._strategy_context.contract
            self._strategy_bytes = _native_snapshot(
                self._strategy_config, self._strategy_authority, self._strategy_contract,
            )
        self._phase, self._poisoned, self._prepared, self._before_bytes = "new", False, None, None
        self._reconcile_registration_started = False
        self._mailbox_binding_bytes = None
        self._mailbox_capture_started = False
        self._mailbox_history_bytes = b"[]"
        self._validated_before, self._retaining_before, self._retaining_success = None, False, None
        self._success_deadline = None
        self._retaining_rejection, self._rejection_deadline, self._rejection_file_pin = False, None, None
        self._rejection_c1_capture = self._rejection_provenance_c2_capture = None
        self._retaining_rejection_provenance = False
        self._rejection_provenance_deadline = self._rejection_provenance_file_pin = None
        self._rejection_provenance_evidence = self._rejection_provenance_sha256 = None
        self._rejection_ready_capture_started, self._rejection_ready_capture = False, None
        self._rejection_ready_state, self._rejection_ready_stage = "unused", None
        self._rejection_ready_ack, self._rejection_ready_ack_fields = None, None
        self._rejection_ready_commit_started, self._rejection_ready_final_capture = False, None
        self._rejection_ready_locks_capture = None
        self._rejection_ready_sync_capture = None
        from .rsi_native_scheduler import _read_ledger_identity
        self._rejection_ledger_identity = (None if self._native is None else
                                           lineage._raw(_read_ledger_identity(self._ledger)))
        self._before_control = None if self._native is None else self._native.execution_control
        self._before_cancelled = None if self._native is None else self._native.cancelled
        self._before_control_pin = self._before_control_state()
        self._check_owner(registered=False)
        if self._state.get(_FIELD) is not None:
            _fail("fresh_lineage_required")
        controller._python_admission_brs_local.lineage_checkpoint_owner = self

    def _reconcile_registration_fixed(self) -> None:
        """Recheck fixed old-capture facts without source or control callbacks."""
        self._identity()
        if (self._reconcile_registration_started is not True or self._phase != "new"
                or self._retaining_before is not False or self._retaining_success is not None
                or self._success_deadline is not None or self._state.get(_FIELD) is not None
                or self._head != self._handoff.head_sha256
                or hashlib.sha256(self._payload).hexdigest() != self._handoff.state_sha256):
            _fail("reconcile_registration_unavailable")
        self._before_channel()
        RSIRunBudget.load(self._wave.budget_state).check()
        if self._before_control_state() != self._before_control_pin:
            _fail("before_control_drift")
        if self._before_control is not None:
            with self._before_control._lock:
                if self._before_control._cancelled is not False:
                    _fail("before_control_cancelled")
            if time.monotonic() >= self._before_control.deadline:
                _fail("reconcile_registration_deadline_exhausted")
        with self._ledger.read_only_observations():
            self._running()

    def _reconcile_registration_observe(self, expected: dict[str, Any]) -> None:
        """Observe the staged exact delta while every local owner capture stays old.

        The durable obligation may already be appended. Ordinary owner checks
        require durable/local head equality and cannot authorize this window.
        This validation returns no capability and never adopts a latest head.
        """
        from .rsi_controller import _record_digest
        from .rsi_fingerprint import RSIFingerprintContract, ensure_fingerprint_compatible

        self._before_unlocked()
        self._reconcile_registration_fixed()
        self._before_control_live()
        captured = json.loads(self._payload)
        with self._ledger.read_only_observations():
            original = self._ledger.history(self._run_id)[0]
            actual, _ = self._controller._run_fingerprint(
                **captured["pins"], memory_snapshot_sha256=self._memory.digest(),
                mode=captured["mode"], plan=captured["plan"],
            )
            ensure_fingerprint_compatible(
                RSIFingerprintContract.from_dict(original.payload["fingerprints"]["run_fingerprint"]), actual,
            )
            run = self._ledger.get_run(self._run_id)
            self._controller._validate_original_run_checkpoint_producer_binding(run, expected)
            self._controller._validate_python_admission_references(self._run_id, expected)
            self._controller._validate_producer_staging(run, expected)
            self._history(expected)
        budget = RSIRunBudget.load(captured["budget_state"])
        budget.assert_matches(original.payload["budget"])
        budget.check()
        policy = {
            "plan": captured["plan"], "pins": captured["pins"],
            "planned": budget.to_dict()["planned"],
            "producer_checkpoint_binding": captured.get("producer_checkpoint_binding"),
            "solver_settings": actual.to_dict()["solver_settings"],
        }
        control = {"budget_state": budget.to_dict(), "status": captured["status"]}
        context = self._selected_context
        if (actual.digest() != context.source_sha256 or _record_digest(policy) != context.policy_sha256
                or _record_digest(control) != context.execution_control_sha256):
            _fail("reconcile_registration_authority_drift")
        self._identity()
        if self._native is not None:
            self._native_strategy()
        self._reconcile_registration_fixed()

    def _reconcile_registration_readback(self, head: str, expected: dict[str, Any]) -> None:
        """Require the returned head to be exactly the original head's successor."""
        with self._ledger.read_only_observations():
            history = self._ledger.controller_checkpoint_history(self._run_id)
            if (type(head) is not str or head == self._head or len(history) < 2
                    or history[-2] != (self._head, json.loads(self._payload))
                    or history[-1] != (head, expected)):
                _fail("reconcile_registration_readback_invalid")

    def retain_reconcile_obligation(self) -> str:
        """Append one publication recovery fence under the genuine original owner.

        This one-shot method changes only the existing obligation field and
        acknowledges its exact adjacent CAS. The original handoff/context are
        immutable; neither a result nor process cleanup is inferred here.
        """
        if type(self) is not _BRSLineageCheckpointOwner:
            _fail("owner_invalid")
        from .rsi_brs_reconcile import (
            FIELD,
            BRSReconcileObligation,
            put_brs_reconcile_obligation,
            register_brs_selected_obligation,
        )

        try:
            self._before_unlocked()
            self._identity()
            if self._reconcile_registration_started is not False:
                _fail("reconcile_registration_unavailable")
            self._reconcile_registration_started = True
            self._reconcile_registration_fixed()
            self._check_owner()
            self._before_control_live()
            self._reconcile_registration_fixed()
            obligation = BRSReconcileObligation(
                self._run_id, self._request.episode_id, "selected", self._handoff.sha256,
                self._request.digest(), self._plan.plan_sha256, self._head, self._episode_head,
                native_claim_sha256=self._claim.claim_sha256, mailbox_state="open",
            )
            expected = json.loads(self._payload)
            if self._request.episode_id in expected.get(FIELD, {}):
                _fail("reconcile_registration_unavailable")
            put_brs_reconcile_obligation(expected, obligation)
            payload = self._controller._python_admission_flow_payload(expected)
            registration = register_brs_selected_obligation(
                self._ledger, self._handoff, native_plan_sha256=self._plan.plan_sha256,
                controller_checkpoint_sha256=self._head, episode_record_sha256=self._episode_head,
                expected_run_record_sha256=self._run_head,
                expected_native_claim_sha256=self._claim.claim_sha256,
            )
            if registration.obligation.to_dict() != obligation.to_dict():
                _fail("reconcile_registration_readback_invalid")
            head = registration.checkpoint_sha256
            self._reconcile_registration_readback(head, expected)
            # No shared state is refreshed to let ordinary owner checks pass.
            self._reconcile_registration_observe(expected)
            self._reconcile_registration_readback(head, expected)
            with self._controller._python_admission_brs_observations(), self._before_channel_condition:
                self._reconcile_registration_fixed()
                self._reconcile_registration_readback(head, expected)
                self._state[FIELD] = expected[FIELD]
                self._wave.checkpoint_sha256, self._wave.payload = head, payload
                self._head, self._payload = head, payload
            return head
        except BaseException:
            self._poisoned = True
            raise

    _mailbox_native_arguments = _mailbox_native_arguments
    _mailbox_process_unchanged = _mailbox_process_unchanged
    _mailbox_readback = _mailbox_readback

    retain_mailbox_observation = _retain_mailbox_observation

    def _identity(self, *, captured: bool = True, registered: bool = True) -> None:
        from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
        from .rsi_python_admission import validate_rsi_python_admission_shapes
        from .rsi_python_brs_handoff import BRSChildHandoffContext, BRSSelectedChildHandoff
        from .rsi_python_scheduler_inputs import _request_memory

        controller, wave = self._controller, self._wave
        if (type(self) is not _BRSLineageCheckpointOwner or self._poisoned
                or type(self._reconcile_registration_started) is not bool
                or type(controller) is not RSILearningController or type(wave) is not _PythonAdmissionBRSWave
                or type(wave.run_id) is not str or wave.run_id != self._run_id
                or type(wave.owner_thread) is not int or wave.owner_thread != self._thread
                or type(wave.checkpoint_sha256) is not str or type(wave.payload) is not bytes
                or get_ident() != self._thread or controller.ledger is not self._ledger
                or controller.gateway is not self._gateway or wave.state is not self._state
                or controller.producer_workspace is not self._workspace or controller.producer_sidecar is not self._sidecar
                or wave.channel is not self._channel or wave.selected_handoff is not self._handoff
                or wave.selected_context is not self._selected_context or wave.selected_worker_started is not True
                or wave.selected_return is not None or wave.selected_settlement_started is not False
                or (registered and getattr(controller._python_admission_brs_local, "lineage_checkpoint_owner", None) is not self)):
            _fail("owner_drift")
        controller._python_admission_assert_brs_wave(wave, owner=True)
        controller._python_admission_selected_brs_identity(wave, self._handoff)
        if (BRSSelectedChildHandoff.canonical_bytes.fget(self._handoff) != self._handoff_bytes
                or canonical_json(BRSChildHandoffContext.to_dict(self._selected_context)) != self._selected_context_bytes
                or lineage._root_pin(self._workspace) != self._association["workspace"]
                or self._state.get("plan", {}).get("max_workers") != 1
                or self._state.get("root_snapshot") != self._memory.to_dict()
                or self._state.get("intents", {}).get(self._request.episode_id, {}).get("request") != self._request.to_dict()
                or self._request.episode_id in self._state.get("executions", {})
                or self._controller._python_admission_flow_payload(wave.budget_state) != self._budget_bytes
                or self._controller._python_admission_flow_payload(self._state["budget_state"]) != self._budget_bytes
                or (captured and (wave.checkpoint_sha256 != self._head or wave.payload != self._payload))):
            _fail("checkpoint_drift")
        if lineage._raw(_policy()) != self._policy_bytes:
            _fail("policy_drift")
        self._strategy_identity()
        _validate_persisted_policy(
            controller, run_id=self._run_id, state=self._state, expected=json.loads(self._policy_bytes),
        )
        request, memory = _request_memory(self._provided_request, self._provided_memory)
        validate_rsi_python_admission_shapes(self._provided_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
        plan = NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(self._provided_plan))
        if request != self._request or memory.to_bytes() != self._memory.to_bytes() or plan != self._plan:
            _fail("inputs_drift")
        binding = self._sidecar.binding
        if ((plan.run_id, plan.journal_id, plan.launch_id, plan.parent_task_id, plan.task_id, plan.intent_sha256,
             plan.attestation_sha256, plan.deadline_unix) !=
                (binding.run_id, binding.intent.journal_id, binding.intent.launch_id, binding.parent_task_id,
                 binding.task_id, binding.intent_sha256, binding.attestation_sha256, binding.deadline_unix)):
            _fail("plan_binding_drift")
        RSIRunBudget.load(self._wave.budget_state).check()
        RSIRunBudget.load(self._state["budget_state"]).check()

    def _running(self) -> None:
        run = self._ledger.get_run(self._run_id)
        episode = self._ledger.get_episode(self._request.episode_id)
        claim = self._ledger.inspect_native_episode_claim(self._request, plan_sha256=self._plan.plan_sha256)
        if (run is None or run.state != "running" or run.record_sha256 != self._run_head
                or episode is None or episode.state != "running" or episode.record_sha256 != self._episode_head
                or episode.request_sha256 != self._request.digest() or claim != self._claim or claim.status != "started"
                or self._ledger.episode_result(self._request.episode_id) is not None):
            _fail("running_claim_drift")
        original = self._ledger.history(self._run_id)[0]
        if (original.request_sha256 != self._association["run_request_sha256"]
                or lineage._sha(lineage._raw(original.payload.get("producer_checkpoint_binding")))
                != self._association["root_proof_sha256"]):
            _fail("root_proof_drift")

    def _check_owner(self, *, captured: bool = True, registered: bool = True) -> dict[str, Any]:
        scope, allowance = self._retaining_success, self._success_deadline
        self._identity(captured=captured, registered=registered)
        # Source/configuration callbacks can wait for another observer. They must
        # finish outside the short observation mutex and any workspace write lock.
        self._controller._python_admission_assert_selected_brs(self._wave, self._handoff)
        if scope is not None:
            self._success_scope(scope)
            self._success_cap_unchanged(allowance)
        self._identity(captured=captured, registered=registered)
        if self._native is not None:
            self._native_strategy()
        if scope is not None:
            self._success_scope(scope)
            self._success_cap_unchanged(allowance)
        with self._ledger.read_only_observations():
            self._running()
            self._controller._python_admission_active_brs_owner(self._wave)
            self._history()
        return self._state

    def _strategy_identity(self) -> None:
        if getattr(self._gateway, "producer_config", None) is not self._native_config:
            _fail("native_strategy_drift")
        if self._native_config is None:
            return
        from .algorithm import AlgorithmProblemContract
        from .evolution import (
            CandidateArchive,
            CandidateIntegrityAuthority,
            EvolutionConfig,
            EvolutionContext,
            PopulationStrategy,
        )
        from .rsi_native_scheduler import NativeRSISchedulerContext
        from .rsi_producer_gateway import PythonProducerRSIExecutionConfig
        from .rsi_python_scheduler_inputs import PythonRSISchedulerInputContext

        if (type(self._native_config) is not PythonProducerRSIExecutionConfig
                or self._native_config.ledger is not self._ledger
                or self._native_config.inputs is not self._native_inputs
                or type(self._native_inputs) is not PythonRSISchedulerInputContext
                or self._native_inputs.native_context is not self._native
                or type(self._native) is not NativeRSISchedulerContext
                or self._native.strategy is not self._strategy
                or type(self._strategy) is not PopulationStrategy
                or self._strategy.context is not self._strategy_context
                or type(self._strategy_context) is not EvolutionContext
                or self._strategy_context.contract is not self._strategy_contract
                or type(self._strategy_contract) is not AlgorithmProblemContract
                or self._strategy.config is not self._strategy_config
                or self._strategy_context.config is not self._strategy_config
                or type(self._strategy_config) is not EvolutionConfig
                or self._strategy.integrity_authority is not self._strategy_authority
                or type(self._strategy_authority) is not CandidateIntegrityAuthority
                or self._strategy.archive is not self._strategy_archive
                or type(self._strategy_archive) is not CandidateArchive
                or type(self._strategy_archive.workspace) is not type(self._workspace)
                or self._strategy_archive.workspace != self._workspace
                or any(callable(item) for item in vars(self._strategy).values())
                or any(name in vars(self._strategy_archive) for name in ("_is_seed_candidate",))
                or type(self._strategy_context.workspace) is not type(self._workspace)
                or self._strategy_context.workspace.expanduser().absolute() != self._workspace
                or type(self._native.workspace) not in {str, type(self._workspace)}
                or Path(self._native.workspace).expanduser().absolute() != self._workspace
                or _native_snapshot(self._strategy_config, self._strategy_authority,
                                    self._strategy_contract) != self._strategy_bytes):
            _fail("native_strategy_drift")

    def _native_strategy(self) -> None:
        self._strategy_identity()
        if self._native is None:
            _fail("native_strategy_required")
        from .rsi_python_scheduler_inputs import _context

        _native, sidecar = _context(self._native_inputs)
        binding = self._sidecar.binding
        authority = self._strategy_authority
        if (sidecar != self._sidecar or self._native.failure_ledger is not self._ledger
                or self._strategy_context.contract.digest() != binding.contract_sha256
                or (authority.contract_sha256, authority.evaluator_kind, authority.evaluator_fingerprint,
                    authority.runner_fingerprint, authority.dependency_sha256, authority.environment_sha256) !=
                (binding.contract_sha256, binding.evaluator_kind, binding.evaluator_fingerprint,
                 binding.intent.runner_fingerprint, binding.dependency_sha256, binding.environment_sha256)):
            _fail("native_strategy_binding_invalid")

    _history = rejection._history

    def _initial_window(self, archive: bytes, state_bytes: bytes) -> None:
        from .producer_bundle_transaction import _records_from_archive

        state, records = json.loads(state_bytes), _records_from_archive(archive)
        outcome_fields = {"outcome_schema_version", "outcome_start_iteration", "outcome_watermark",
            "outcome_watermark_sha256", "outcome_archive_baseline_sha256", "pending_offspring",
            "failed_offspring_iteration", "failed_offspring_sha256"}
        if (type(state.get("iteration")) is not int or state["iteration"] != 0
                or state.get("status") != "running" or "seed_admission" in state
                or outcome_fields.intersection(state) or state.get("producer_admissions") is not None
                or any(item.iteration != 0 or "seed_handoff" in item.metadata or "producer_bundle" in item.metadata
                       for item in records)):
            _fail("success_initial_window_required")
        # Read-only counterpart of the native initial-window gate. Avoid the
        # archive's mutation/recovery facade while a staged marker may exist.
        for filename in ("seed-commit.json", "offspring-outcomes.jsonl"):
            path = self._workspace / "evolution" / filename
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            if filename == "seed-commit.json" or _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES).strip():
                _fail("success_initial_window_required")

    def _before_unlocked(self) -> None:
        from .producer_bundle_staging import _HELD_PUBLICATION_LOCKS

        # Unlike the DRS facade, the BRS owner performs source/config callbacks.
        # Refuse a locked caller before any such observation, including reentry.
        if type(self) is not _BRSLineageCheckpointOwner or _HELD_PUBLICATION_LOCKS.get():
            _fail("before_unlocked_owner_required")

    def _before_channel(self) -> None:
        from .rsi_python_brs_admission import BRSAdmissionChannel

        channel, condition = self._channel, self._before_channel_condition
        if type(channel) is not BRSAdmissionChannel or type(condition) is not Condition:
            _fail("before_channel_drift")
        ready_sync = self._rejection_ready_sync_capture
        if ready_sync is not None:
            _ORIGINAL_READY_CONDITION_ASSERT(condition, ready_sync)
        nonce = json.loads(self._handoff_bytes)["lease_nonce"]
        digest = hashlib.sha256(self._handoff_bytes).hexdigest()
        with condition if ready_sync is None else ready_sync[1]:
            if ready_sync is not None:
                _ORIGINAL_READY_CONDITION_ASSERT(condition, ready_sync)
            if (self._wave.channel is not channel or channel._condition is not condition
                    or channel._closed is not False or type(channel._owner_thread) is not int
                    or channel._owner_thread != self._thread or type(channel._run_id) is not str
                    or channel._run_id != self._run_id or type(self._wave.episode_ids) is not tuple
                    or any(type(item) is not str for item in self._wave.episode_ids)
                    or type(channel._episode_ids) is not frozenset
                    or any(type(item) is not str for item in channel._episode_ids)
                    or channel._episode_ids != frozenset(self._wave.episode_ids)
                    or channel._handoff_mode is not True or channel._servicing is not False
                    or type(channel._selected_episode_id) is not str
                    or channel._selected_episode_id != self._request.episode_id
                    or type(channel._selected_handoff_sha256) is not str or channel._selected_handoff_sha256 != digest
                    or type(channel._consumed_handoff_nonces) is not set
                    or any(type(item) is not str for item in channel._consumed_handoff_nonces)
                    or channel._consumed_handoff_nonces != {nonce}
                    or type(channel._completed_selected_episodes) is not set or channel._completed_selected_episodes
                    or type(channel._requests) is not dict or channel._requests
                    or type(channel._queue) is not deque or channel._queue):
                _fail("before_channel_drift")

    def _before_control_state(self):
        from .automatic_solve_lifecycle import SolveExecutionControl
        from .rsi_python_brs_publication_recovery import _control_pin

        control = self._before_control
        if (self._native is not None and (self._native.execution_control is not control
                or self._native.cancelled is not self._before_cancelled)):
            _fail("before_control_drift")
        if control is not None:
            if type(control) is not SolveExecutionControl:
                _fail("before_control_drift")
            # Refuse foreign numeric types before the shared finite-time helper
            # can compare their metaclass against its allowed scalar types.
            values = object.__getattribute__(control, "__dict__")
            if (type(values) is not dict or any(type(key) is not str for key in values)
                    or any(type(values.get(name)) is not int and type(values.get(name)) is not float
                           for name in ("started_at", "deadline", "timeout_seconds"))):
                _fail("before_control_drift")
        return _control_pin(control)

    def _before_control_live(self) -> float | None:
        from .automatic_solve_lifecycle import SolveExecutionControl

        if self._before_control_state() != self._before_control_pin:
            _fail("before_control_drift")
        if self._before_cancelled is not None:
            cancelled = self._before_cancelled()
            if type(cancelled) is not bool or cancelled:
                _fail("before_control_cancelled")
        if self._before_control_state() != self._before_control_pin:
            _fail("before_control_drift")
        remaining = None
        if self._before_control is not None:
            remaining = SolveExecutionControl.check(self._before_control, "rsi_brs_before_evidence")
        if self._before_control_state() != self._before_control_pin:
            _fail("before_control_drift")
        return remaining

    def _live_before(self, archive: bytes, state_bytes: bytes) -> None:
        path = self._workspace / "evolution/archive.jsonl"
        try:
            path.lstat()
        except FileNotFoundError:
            if archive:
                _fail("before_source_drift")
        else:
            if _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES) != archive:
                _fail("before_source_drift")
        if (_files.read_regular_file(self._workspace / "evolution/state.json", lineage.MAX_LINEAGE_SNAPSHOT_BYTES)
                != state_bytes or lineage._root_pin(self._workspace) != self._association["workspace"]):
            _fail("before_source_drift")
        lineage._require_marker_absent(self._workspace)

    def validate_before(self, journal: Any, base_archive: bytes, base_state_bytes: bytes,
                        strategy: Any, *, admission_plan: Any = None) -> tuple[tuple[str, ...], ...]:
        """Observe only the original first native prefix; retain no files or CAS."""
        from .evolution import CandidateIntegrityAuthority, EvolutionConfig, PopulationStrategy
        from .producer_bundle_admission import ProducerBundleAdmissionPlan
        from .producer_bundle_publication import ProducerBundlePublicationJournal

        try:
            self._before_unlocked()
            lineage._publication_shapes(journal, admission_plan)
            if (type(journal) is not ProducerBundlePublicationJournal or type(strategy) is not PopulationStrategy
                    or type(base_archive) is not bytes or type(base_state_bytes) is not bytes):
                _fail("before_inputs_invalid")
            self._check_owner()
            self._before_channel()
            self._native_strategy()
            self._before_control_live()
            self._identity()
            self._before_channel()
            if self._phase not in {"new", "before", "prepared-evidence"} or strategy is not self._strategy:
                _fail("before_unavailable")
            if (len(base_archive) > lineage.MAX_LINEAGE_SNAPSHOT_BYTES
                    or len(base_state_bytes) > lineage.MAX_LINEAGE_SNAPSHOT_BYTES):
                _fail("capacity_exceeded")
            parsed = parse_producer_bundle_publication_journal(journal.to_dict())
            if admission_plan is None:
                if self._validated_before is None:
                    _fail("before_admission_required")
                admission_plan = parse_producer_bundle_admission_plan(json.loads(self._validated_before)["admission_plan"])
            if type(admission_plan) is not ProducerBundleAdmissionPlan:
                _fail("before_inputs_invalid")
            admission = parse_producer_bundle_admission_plan(admission_plan.to_dict())
            binding = self._sidecar.binding
            authority = (binding.contract_sha256, self._plan.evaluator_kind, binding.evaluator_fingerprint,
                binding.intent.runner_fingerprint, binding.dependency_sha256, binding.environment_sha256)
            if (parsed != journal or parsed.state != "prepared"
                    or (parsed.run_id, parsed.journal_id, parsed.parent_task_id, parsed.task_id) !=
                    (self._run_id, self._plan.journal_id, self._plan.parent_task_id, self._plan.task_id)
                    or parsed.admission_sha256 != admission.digest()
                    or parsed.base_archive_sha256 != lineage._sha(base_archive)
                    or parsed.base_state_sha256 != lineage._sha(base_state_bytes)
                    or (parsed.contract_sha256, parsed.evaluator_kind, parsed.evaluator_fingerprint,
                        parsed.runner_fingerprint, parsed.dependency_sha256, parsed.environment_sha256) != authority
                    or (admission.contract_sha256, admission.evaluator_kind, admission.evaluator_fingerprint,
                        admission.runner_fingerprint, admission.dependency_sha256, admission.environment_sha256) != authority
                    or tuple((item.bundle_id, item.bundle_sha256) for item in parsed.candidates) !=
                    tuple((item.bundle_id, item.bundle_sha256) for item in admission.bundles)
                    or parsed.population_config_sha256 != lineage._sha(lineage._raw(
                        EvolutionConfig.to_dict(self._strategy_config)))
                    or parsed.num_islands != self._strategy_config.num_islands):
                _fail("before_binding_invalid")
            state = json.loads(base_state_bytes)
            if (type(state) is not dict or state.get("config") != EvolutionConfig.to_dict(self._strategy_config)
                    or state.get("candidate_integrity_authority") !=
                    CandidateIntegrityAuthority.to_dict(self._strategy_authority)
                    or state.get("contract_sha256") != parsed.contract_sha256):
                _fail("native_configuration_drift")
            self._initial_window(base_archive, base_state_bytes)
            if (type(state.get("active_ids")) is not dict
                    or parsed.archive_prefix_sha256 != compute_archive_prefix_digest(
                        lineage._sha(base_archive), lineage._sha(base_state_bytes),
                        strategy_config_sha256=lineage._sha(lineage._raw(state["config"])),
                        active_ids_sha256=lineage._sha(lineage._raw(state["active_ids"])))):
                _fail("before_prefix_drift")
            if parsed.python_handoff_file_pin is None or parsed.native_execution_receipt_sha256 is None:
                _fail("before_handoff_required")
            held = read_python_producer_admission_handoff_pinned(
                self._workspace / "evolution/producer-batches" / self._plan.journal_id,
                expected_file_pin=parsed.python_handoff_file_pin,
            ).handoff
            if ((held.run_id, held.journal_id, held.parent_task_id, held.task_id, held.binding_sha256,
                 held.launch_intent_sha256, held.attestation_sha256, held.handoff_sha256,
                 held.native_execution_receipt_sha256, held.admission_plan_sha256) !=
                (self._run_id, self._plan.journal_id, self._plan.parent_task_id, self._plan.task_id,
                 binding.binding_sha256, binding.intent_sha256, binding.attestation_sha256,
                 parsed.python_handoff_sha256, parsed.native_execution_receipt_sha256, admission.digest())):
                _fail("before_handoff_drift")
            self._live_before(base_archive, base_state_bytes)
            PopulationStrategy._validate_candidate_integrity_state(strategy, state)
            PopulationStrategy._active(strategy, state)
            self._check_owner()
            self._before_control_live()
            self._identity()
            self._before_channel()
            capture = lineage._raw({"journal": parsed.to_dict(), "admission_plan": admission.to_dict()})
            if (self._validated_before is not None and self._validated_before != capture
                    or self._prepared is not None and self._prepared != parsed):
                _fail("before_capture_drift")
            self._live_before(base_archive, base_state_bytes)
            self._validated_before = capture
            return ()
        except BaseException:
            self._poisoned = True
            raise

    def _before_wire(self, journal, admission, archive_pin, state_pin, descriptor_pin, sources):
        before = ProducerLineageBeforeIntent(self._run_id, journal.journal_id, 0, None, None, archive_pin, state_pin)
        return {**self._association, "batches": [{
            "journal_id": journal.journal_id, "ordinal": 0, "episode_id": self._request.episode_id,
            "request_sha256": self._request.digest(), "memory_snapshot_sha256": self._memory.digest(),
            "native_plan_sha256": self._plan.plan_sha256, "admission_plan": admission.to_dict(),
            "prepared_journal": journal.to_dict(), "before": before.to_dict(),
            "before_file_pin": descriptor_pin.to_dict(),
            "snapshots": {"archive-before": archive_pin.to_dict(), "state-before": state_pin.to_dict()},
            "before_sources": sources, "state": "before", "evidence_pins": {},
        }], "head": None, "rejections": []}

    def retain_before(self, journal: Any, base_archive: bytes, base_state_bytes: bytes) -> None:
        """Create genuine first-before evidence, then use the original checkpoint CAS."""
        try:
            self._before_unlocked()
            if self._retaining_before or self._phase != "new" or self._validated_before is None:
                _fail("before_retention_unavailable")
            self._retaining_before = True
            admission = parse_producer_bundle_admission_plan(json.loads(self._validated_before)["admission_plan"])
            self.validate_before(journal, base_archive, base_state_bytes, self._strategy, admission_plan=admission)
            self._before_channel()
            empty = {**self._association, "batches": [], "head": None, "rejections": []}
            total = lineage.RSIPublicationLineage._retained_bytes(empty, self._state)
            if total + len(base_archive) + len(base_state_bytes) > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("capacity_exceeded")
            archive_path, state_path = self._workspace / "evolution/archive.jsonl", self._workspace / "evolution/state.json"
            try:
                archive_path.lstat()
            except FileNotFoundError:
                archive_source = None
                sources = {"archive": {"missing": True, "parent": lineage._root_pin(archive_path.parent)}}
            else:
                archive_source = capture_lineage_snapshot_pin(archive_path, name="archive-before")
                sources = {"archive": archive_source.to_dict()}
            state_source = capture_lineage_snapshot_pin(state_path, name="state-before")
            sources["state"] = state_source.to_dict()
            for source, raw in ((archive_source, base_archive), (state_source, base_state_bytes)):
                if source is not None and (source.sha256 != lineage._sha(raw) or source.size != len(raw)):
                    _fail("before_source_drift")
            # Maximum inode/stat fields bound the checkpoint before any create.
            # These synthetic pins are used only for capacity; never as evidence.
            def capacity_pin(name, size):
                maximum = 2**64 - 1
                return LineageSnapshotPin(name, "f" * 64, size, maximum, maximum, maximum, maximum,
                    mtime_ns=maximum, ctime_ns=maximum)
            projected = self._before_wire(journal, admission,
                capacity_pin("archive-before.snapshot", len(base_archive)),
                capacity_pin("state-before.snapshot", len(base_state_bytes)), capacity_pin("before.json", 4096), sources)
            lineage.RSIPublicationLineage._retained_bytes(projected, self._state)
            lineage._raw(lineage._publication_lineage_checkpoint_delta(self._payload, projected))
            self.validate_before(journal, base_archive, base_state_bytes, self._strategy, admission_plan=admission)
            self._before_channel()
            if archive_source is None:
                archive_file, archive_pin = persist_lineage_bytes_snapshot(self._workspace, journal.journal_id,
                    name="archive-before", raw=base_archive, expected_sha256=lineage._sha(base_archive), retained_bytes=total)
            else:
                archive_file, archive_pin = persist_lineage_snapshot(self._workspace, journal.journal_id,
                    name="archive-before", source=archive_path, expected_pin=archive_source, retained_bytes=total)
            state_file, state_pin = persist_lineage_snapshot(self._workspace, journal.journal_id,
                name="state-before", source=state_path, expected_pin=state_source, retained_bytes=total + archive_pin.size)
            for path, pin, raw in ((archive_file, archive_pin, base_archive), (state_file, state_pin, base_state_bytes)):
                verify_persisted_lineage_snapshot(path, pin)
                if _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES) != raw:
                    _fail("before_snapshot_drift")
                verify_persisted_lineage_snapshot(path, pin)
            before = ProducerLineageBeforeIntent(self._run_id, journal.journal_id, 0, None, None, archive_pin, state_pin)
            _path, descriptor_pin = persist_lineage_descriptor(self._workspace, before)
            wire = self._before_wire(journal, admission, archive_pin, state_pin, descriptor_pin, sources)
            self.validate_before(journal, base_archive, base_state_bytes, self._strategy, admission_plan=admission)
            if self._retaining_before is not True:
                _fail("before_retention_scope_drift")
            self._before_channel()
            _BRSLineageCheckpointOwner.checkpoint_before(self, wire)
        except BaseException:
            self._poisoned = True
            raise
        finally:
            self._retaining_before = False

    def _candidate_materials(self, entry, files, archive_after: bytes, *, staged: bool):
        """Bind archive rows to verified materials and retain exact source bytes."""
        from .candidate_bundle import parse_candidate_source_bundle
        from .evolution import Candidate
        from .producer_bundle_transaction import _records_from_archive

        records = {record.candidate_id: record for record in _records_from_archive(archive_after)}
        overrides = {}
        for cid, material in files.items():
            root = (recovery._path(self._workspace, f"stage/candidates/{cid}", directory=
                                  recovery._batch(self._workspace, self._plan.journal_id)) if staged else
                    recovery._path(self._workspace, f"evolution/candidates/{cid}"))
            descriptors = {}
            for descriptor in material["paths"]:
                name = descriptor["path"]
                prefix = f"stage/candidates/{cid}/"
                name = name.removeprefix(prefix)
                if name in descriptors:
                    _fail("candidate_materials_invalid")
                descriptors[name] = descriptor
            record_names = [name for name in descriptors if name == "record.json" or name.endswith("/record.json")]
            if len(record_names) != 1 or cid not in records:
                _fail("candidate_materials_invalid")
            raw = _files.read_regular_file(recovery._path(self._workspace, record_names[0], directory=root), 64 * 1024)
            record = Candidate.from_dict(json.loads(raw))
            if (lineage._sha(raw) != material["record_sha256"]
                    or record.candidate_id != cid or record.to_dict() != records[cid].to_dict()):
                _fail("archive_material_record_drift")
            live_root = f"evolution/candidates/{cid}/"
            if not record.code_path.startswith(live_root):
                _fail("candidate_materials_invalid")
            if record.bundle_evidence is None:
                paths = (record.code_path[len(live_root):],)
                declarations = None
            else:
                evidence = record.bundle_evidence
                if evidence["source_root"] != live_root[:-1] or not evidence["bundle_path"].startswith(live_root):
                    _fail("candidate_materials_invalid")
                name = evidence["bundle_path"][len(live_root):]
                if name not in descriptors:
                    _fail("candidate_materials_invalid")
                bundle_raw = _files.read_regular_file(recovery._path(self._workspace, name, directory=root), 256 * 1024)
                bundle = parse_candidate_source_bundle(json.loads(bundle_raw))
                planned = next((candidate for candidate in self._prepared.candidates if candidate.candidate_id == cid), None)
                if (lineage._sha(bundle_raw) != descriptors[name]["sha256"]
                        or planned is None or bundle.digest() != evidence["bundle_sha256"]
                        or evidence["bundle_sha256"] != planned.bundle_sha256
                        or bundle.contract_sha256 != self._prepared.contract_sha256
                        or record.code_path != live_root + bundle.entrypoint):
                    _fail("candidate_materials_invalid")
                paths = tuple(item.path for item in bundle.files)
                declarations = {item.path: item for item in bundle.files}
            sources = {}
            for name in paths:
                if name not in descriptors:
                    _fail("candidate_materials_invalid")
                descriptor = descriptors[name]
                content = _files.read_regular_file(recovery._path(self._workspace, name, directory=root), descriptor["size"] + 1)
                if len(content) != descriptor["size"] or lineage._sha(content) != descriptor["sha256"]:
                    _fail("candidate_material_source_drift")
                if declarations is not None and (len(content) != declarations[name].size
                        or lineage._sha(content) != declarations[name].sha256):
                    _fail("candidate_bundle_source_drift")
                sources[name] = content
            overrides[cid] = sources
        if tuple(overrides) != tuple(entry["staged"]["candidate_ids"]):
            _fail("candidate_materials_invalid")
        return overrides

    def _verify_staged_projection(self, entry, raw, source_overrides) -> None:
        """Verify the first transition while new candidate source is still staged."""
        from .evolution import CandidateIntegrityAuthority, EvolutionConfig, PopulationStrategy
        from .producer_bundle_transaction import _records_from_archive

        before, after = raw["archive-before"], raw["archive-after"]
        if not after.startswith(before):
            _fail("archive_prefix_drift")
        before_records, after_records = _records_from_archive(before), _records_from_archive(after)
        ids = tuple(entry["staged"]["candidate_ids"])
        if tuple(item.candidate_id for item in after_records) != (*tuple(item.candidate_id for item in before_records), *ids):
            _fail("archive_additions_drift")
        base, observed = json.loads(raw["state-before"]), json.loads(raw["state-after"])
        if (base.get("config") != EvolutionConfig.to_dict(self._strategy_config)
                or base.get("candidate_integrity_authority") != CandidateIntegrityAuthority.to_dict(self._strategy_authority)
                or base.get("contract_sha256") != self._prepared.contract_sha256):
            _fail("native_configuration_drift")
        events = {"schema_version": "1", "events": [{"after_iteration": 0, "candidate_ids": list(ids)}]}
        active, best, migration, stagnation = PopulationStrategy._reconstruct_population_projection(
            self._strategy, base | {"producer_admissions": events}, after_records, source_overrides=source_overrides,
        )
        expected = base | {
            "schema_version": "1", "strategy": "population", "status": "running", "iteration": 0,
            "contract_sha256": self._prepared.contract_sha256, "config": dict(base["config"]),
            "active_ids": {str(key): item for key, item in active.items()}, "producer_admissions": events,
            "best_candidate_id": best, "rng_seed": base.get("rng_seed", base["config"].get("rng_seed")),
            "last_migration_iteration": migration, "stagnation": stagnation, "error": None,
            "candidate_integrity_schema_version": "1", "candidate_integrity_authority": base["candidate_integrity_authority"],
            "candidate_archive_sha256": lineage._sha(canonical_json(
                [item.to_dict() for item in after_records], maximum=16 * 1024 * 1024,
            )),
        }
        if observed != expected or lineage._sha(raw["state-after"]) != entry["state_projection_sha256"]:
            _fail("state_projection_drift")

    def _success_entry(self, wire: object, *, phase: str, observing: bool = False,
                       fixed: bool = False) -> dict[str, Any]:
        from .rsi_python_admission import validate_rsi_python_admission_shapes

        scope, allowance = self._retaining_success, self._success_deadline
        validate_rsi_python_admission_shapes(wire)
        if type(observing) is not bool or type(fixed) is not bool:
            _fail("success_invalid")
        if observing or fixed:
            self._strategy_identity()
            if self._native is None:
                _fail("native_strategy_required")
        else:
            self._native_strategy()
        if scope is not None:
            self._success_scope(scope)
            self._success_cap_unchanged(allowance)
        # The shared terminal schema binds its task directly to this episode.
        # Legacy root-task before/prepared evidence cannot mint that association.
        if self._plan.task_id != self._request.episode_id:
            _fail("success_episode_task_required")
        if type(wire) is not dict or phase not in {"staged", "terminal"}:
            _fail("success_invalid")
        detached = json.loads(lineage._raw(wire))
        if (set(detached) != {*self._association, "batches", "head", "rejections"}
                or any(detached[key] != value for key, value in self._association.items())
                or detached["rejections"] != [] or type(detached["batches"]) is not list
                or len(detached["batches"]) != 1):
            _fail("success_invalid")
        entry = detached["batches"][0]
        if type(entry) is not dict or entry.get("state") != phase:
            _fail("success_invalid")
        self._validate_entry_shape(entry)
        old = json.loads(self._payload).get(_FIELD)
        if (type(old) is not dict or old != self._state.get(_FIELD)
                or (observing and (self._phase != "staged" or phase != "staged" or detached != old))
                or (not observing and (self._phase, phase) not in {
                    ("prepared-evidence", "staged"), ("staged", "terminal")
                })):
            _fail("success_unavailable")
        previous = old["batches"][0]
        for key, value in previous.items():
            if key in {"snapshots", "evidence_pins"}:
                if any(entry[key].get(name) != pin for name, pin in value.items()):
                    _fail("success_delta_invalid")
            elif key != "state" and entry.get(key) != value:
                _fail("success_delta_invalid")
        before_wire = json.loads(self._before_bytes)
        before_wire["batches"][0] = {
            key: entry[key] for key in before_wire["batches"][0]
        }
        before_wire["batches"][0].update(
            state="before", snapshots={name: entry["snapshots"][name] for name in ("archive-before", "state-before")},
            evidence_pins={"journal.prepared.json": entry["evidence_pins"]["journal.prepared.json"]},
        )
        self._before_entry(before_wire, live_sources=phase == "staged")
        lineage.RSIPublicationLineage._retained_bytes(detached, self._state)
        transition = self._verify_descriptor(entry, "staged")
        before = ProducerLineageBeforeIntent.from_dict(entry["before"])
        if (type(transition) is not ProducerLineageStagedTransition
                or (transition.run_id, transition.journal_id, transition.ordinal, transition.before_sha256) !=
                (self._run_id, self._plan.journal_id, 0, before.digest())):
            _fail("staged_binding_invalid")
        batch = recovery._batch(self._workspace, self._plan.journal_id)
        staged = recovery._read_journal(batch / "journal.staged.json")
        original = replace(
            staged, state="prepared", publication_phase="preflight", terminal_marker_sha256=None,
            archive_after_sha256=None, state_after_sha256=None, journal_sha256=None,
            candidates=tuple(replace(item, status="planned", execution_receipt_sha256=None,
                                     evaluation_receipt_sha256=None, publication_receipt_sha256=None)
                             for item in staged.candidates),
        )
        if (original != self._prepared or staged.state != "publishing"
                or staged.digest() != transition.journal_sha256
                or staged.population_config_sha256 != lineage._sha(lineage._raw(self._strategy_config.to_dict()))
                or staged.num_islands != self._strategy_config.num_islands):
            _fail("staged_journal_drift")
        preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
        preflight_sha = recovery._check_preflight(preflight, staged, parse_producer_bundle_admission_plan(entry["admission_plan"]))
        manifest = recovery._read_json(batch / "manifest.json", 256 * 1024)
        manifest_sha, ids, _paths, files = recovery._manifest(manifest, staged, preflight_sha)
        if (manifest.get("status") != "staged" or manifest_sha != transition.manifest_sha256
                or ids != transition.candidate_ids
                or manifest["base_archive_sha256"] != self._prepared.base_archive_sha256
                or manifest["base_state_sha256"] != self._prepared.base_state_sha256
                or manifest["archive_after_sha256"] != transition.archive_after_sha256
                or manifest["state_after_sha256"] != transition.state_after_sha256):
            _fail("staged_manifest_drift")
        if phase == "terminal":
            terminal = ProducerLineageTerminal.from_dict(entry["terminal"])
            if detached["head"] != {
                "journal_id": self._plan.journal_id, "terminal_sha256": terminal.terminal_sha256,
                "lineage_sha256": terminal.digest(),
            }:
                _fail("terminal_head_invalid")
            archive, state_bytes = self._verify_terminal_entry(entry, ordinal=0, previous=None)
            self._initial_window(
                self._snapshot_bytes(self._plan.journal_id, entry["snapshots"]["archive-before"], name="archive-before"),
                self._snapshot_bytes(self._plan.journal_id, entry["snapshots"]["state-before"], name="state-before"),
            )
            self._candidate_materials(entry, files, archive, staged=False)
            lineage._require_marker_absent(self._workspace)
            for name, expected in (("archive", archive), ("state", state_bytes)):
                path = self._workspace / "evolution" / (name + (".jsonl" if name == "archive" else ".json"))
                pin = LineageSnapshotPin.from_dict(entry["head_sources"][name])
                verify_persisted_lineage_snapshot(path, pin)
                if _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES) != expected:
                    _fail("terminal_head_drift")
                verify_persisted_lineage_snapshot(path, pin)
        else:
            if detached["head"] is not None:
                _fail("staged_head_invalid")
            lineage.RSIPublicationLineage._verify_after_source_pins(self, entry)
            snapshots = entry["snapshots"]
            raw = {name: self._snapshot_bytes(self._plan.journal_id, pin, name=name)
                   for name, pin in snapshots.items()}
            if (lineage._sha(raw["archive-after"]) != transition.archive_after_sha256
                    or lineage._sha(raw["state-after"]) != transition.state_after_sha256):
                _fail("staged_snapshot_drift")
            self._initial_window(raw["archive-before"], raw["state-before"])
            plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
            recovery._verify_python_handoff(batch, staged, plan)
            recovery._verify_manifest_files(self._workspace, batch, files, staged)
            overrides = self._candidate_materials(entry, files, raw["archive-after"], staged=True)
            self._verify_staged_projection(entry, raw, overrides)
            recovery._verify_manifest_files(self._workspace, batch, files, staged)
            recovery._marker(self._workspace, staged)
            lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
            lineage.RSIPublicationLineage._verify_after_source_pins(self, entry)
        for name, held_pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(held_pin))
        if scope is not None:
            self._success_scope(scope)
            self._success_cap_unchanged(allowance)
        return detached

    def _before_entry(self, wire: object, *, live_sources: bool = True) -> dict[str, Any]:
        from .rsi_python_admission import validate_rsi_python_admission_shapes

        validate_rsi_python_admission_shapes(wire)
        if type(wire) is not dict:
            _fail("before_invalid")
        detached = json.loads(lineage._raw(wire))
        if (set(detached) != {*self._association, "batches", "head", "rejections"}
                or any(detached[key] != value for key, value in self._association.items())
                or detached["head"] is not None or detached["rejections"] != []
                or type(detached["batches"]) is not list or len(detached["batches"]) != 1):
            _fail("before_invalid")
        entry = detached["batches"][0]
        if type(entry) is not dict or entry.get("state") != "before":
            _fail("before_invalid")
        self._validate_entry_shape(entry)
        before = ProducerLineageBeforeIntent.from_dict(entry["before"])
        plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
        journal = parse_producer_bundle_publication_journal(entry["prepared_journal"])
        if ((entry["journal_id"], entry["ordinal"], entry["episode_id"], entry["request_sha256"],
             entry["memory_snapshot_sha256"], entry["native_plan_sha256"]) !=
                (self._plan.journal_id, 0, self._request.episode_id, self._request.digest(),
                 self._memory.digest(), self._plan.plan_sha256)
                or (before.run_id, before.journal_id, before.ordinal, before.predecessor_terminal_sha256,
                    before.predecessor_lineage_sha256) != (self._run_id, self._plan.journal_id, 0, None, None)
                or journal.state != "prepared" or journal.admission_sha256 != plan.digest()
                or (journal.run_id, journal.journal_id, journal.parent_task_id, journal.task_id) !=
                (self._run_id, self._plan.journal_id, self._plan.parent_task_id, self._plan.task_id)
                or before.archive.to_dict() != entry["snapshots"]["archive-before"]
                or before.state.to_dict() != entry["snapshots"]["state-before"]
                or before.archive.sha256 != journal.base_archive_sha256 or before.state.sha256 != journal.base_state_sha256):
            _fail("before_binding_invalid")
        binding = self._sidecar.binding
        authority = (binding.contract_sha256, self._plan.evaluator_kind, binding.evaluator_fingerprint,
                     binding.intent.runner_fingerprint, binding.dependency_sha256, binding.environment_sha256)
        if ((plan.contract_sha256, plan.evaluator_kind, plan.evaluator_fingerprint, plan.runner_fingerprint,
             plan.dependency_sha256, plan.environment_sha256) != authority
                or (journal.contract_sha256, journal.evaluator_kind, journal.evaluator_fingerprint,
                    journal.runner_fingerprint, journal.dependency_sha256, journal.environment_sha256) != authority
                or tuple((candidate.bundle_id, candidate.bundle_sha256) for candidate in journal.candidates) !=
                tuple((item.bundle_id, item.bundle_sha256) for item in plan.bundles)):
            _fail("before_authority_invalid")
        # Preserve the common ready-capsule + lineage snapshot budget before
        # observing retained files. This BRS protocol uses the pure V1 accounting
        # branch; it neither installs nor impersonates a DRS publication flag.
        lineage.RSIPublicationLineage._retained_bytes(detached, self._state)
        if self._verify_descriptor(entry, "before") != before:
            _fail("before_descriptor_drift")
        for name in ("archive-before", "state-before"):
            self._snapshot_bytes(entry["journal_id"], entry["snapshots"][name], name=name)
        if live_sources:
            lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
        if entry["evidence_pins"]:
            path = self._workspace / "evolution/producer-batches" / self._plan.journal_id / "journal.prepared.json"
            pin = LineageSnapshotPin.from_dict(entry["evidence_pins"]["journal.prepared.json"])
            verify_persisted_lineage_snapshot(path, pin)
            raw = _files.read_regular_file(path, lineage._MAX_CHECKPOINT_BYTES)
            if parse_producer_bundle_publication_journal(json.loads(raw)) != journal:
                _fail("prepared_journal_drift")
            verify_persisted_lineage_snapshot(path, pin)
        return detached

    def _write(self, wire: dict[str, Any]) -> str:
        retaining_before = self._retaining_before
        retaining_success = self._retaining_success
        if type(retaining_before) is not bool:
            _fail("before_retention_scope_drift")
        self._success_scope(retaining_success)
        self._check_owner()
        phase = wire["batches"][0]["state"]
        wire = self._before_entry(wire) if phase == "before" else self._success_entry(wire, phase=phase)
        if self._phase == "new":
            if self._state.get(_FIELD) is not None or wire["batches"][0]["evidence_pins"]:
                _fail("before_unavailable")
        elif self._phase == "prepared-reference":
            original = json.loads(self._before_bytes)
            pins = wire["batches"][0]["evidence_pins"]
            original["batches"][0]["evidence_pins"] = pins
            if set(pins) != {"journal.prepared.json"} or original != wire:
                _fail("prepared_evidence_delta_invalid")
        elif (self._phase, phase) in {("prepared-evidence", "staged"), ("staged", "terminal")}:
            pass  # Exact adjacent evidence delta was checked by _success_entry.
        else:
            _fail("checkpoint_unavailable")
        expected = lineage._publication_lineage_checkpoint_delta(self._payload, wire)
        payload = self._controller._python_admission_flow_payload(expected)
        self._identity()
        if self._retaining_before is not retaining_before:
            _fail("before_retention_scope_drift")
        self._success_scope(retaining_success)
        if retaining_before:
            self._before_control_live()
            self._identity()
            with self._ledger.read_only_observations():
                self._running()
                self._controller._python_admission_active_brs_owner(self._wave)
                self._history()
            self._before_entry(wire)
            self._before_channel()
        if retaining_success is not None:
            started = time.monotonic()
            self._success_entry(wire, phase=phase)
            self._success_control_live(started)
            self._success_fixed()
            self._success_entry(wire, phase=phase, fixed=True)
            self._success_scope(retaining_success)
            self._success_fixed()
        head = self._ledger.write_controller_checkpoint(self._run_id, expected, expected_sha256=self._head)
        if retaining_success is not None:
            self._success_control_live(time.monotonic())
        elif retaining_before:
            self._before_control_live()
        if retaining_success is not None:
            self._success_entry(wire, phase=phase, fixed=True)
        with self._ledger.read_only_observations():
            observed = self._ledger.controller_checkpoint(self._run_id)
            observed_head = None if observed is None else observed[0]
            observed_payload = None
            if observed is not None and observed_head == head:
                observed_payload = self._controller._python_admission_flow_payload(observed[1])
            lineage._validate_publication_lineage_checkpoint_readback(
                expected_head=head, expected_payload=payload, observed_head=observed_head, observed_payload=observed_payload,
            )
            self._identity()
            self._running()
            self._controller._validate_original_run_checkpoint_producer_binding(
                self._ledger.get_run(self._run_id), expected,
            )
            self._history(expected)
        if retaining_success is not None:
            self._success_allowance()
            self._before_channel()
        # No shared state or captured authority advances before the entire readback.
        with self._controller._python_admission_brs_observations(), (
            self._before_channel_condition if retaining_before or retaining_success is not None else nullcontext()
        ):
            # Keep source fingerprints and all configuration hooks out of this
            # short observation mutex. The complete gate just ran above.
            self._controller._python_admission_assert_brs_wave(self._wave, owner=True)
            if self._retaining_before is not retaining_before:
                _fail("before_retention_scope_drift")
            self._success_scope(retaining_success)
            if retaining_success is not None:
                self._success_allowance()
            if retaining_before or retaining_success is not None:
                self._before_channel()
            if (self._wave.state is not self._state or self._wave.selected_handoff is not self._handoff
                    or self._wave.selected_context is not self._selected_context
                    or self._wave.checkpoint_sha256 != self._head or self._wave.payload != self._payload
                    or self._controller.ledger is not self._ledger or self._controller.gateway is not self._gateway
                    or self._controller.producer_workspace is not self._workspace
                    or self._controller.producer_sidecar is not self._sidecar):
                _fail("owner_drift")
            self._state[_FIELD] = json.loads(lineage._raw(wire))
            self._wave.checkpoint_sha256, self._wave.payload = head, payload
            self._head, self._payload = head, payload
        return head

    def checkpoint_before(self, wire: object) -> str:
        """CAS one genuine first-before observation; no descriptor creation/publication."""
        try:
            retaining_before = self._retaining_before
            self._check_owner()
            if self._retaining_before is not retaining_before:
                _fail("before_retention_scope_drift")
            if self._phase != "new" or self._state.get(_FIELD) is not None:
                _fail("before_unavailable")
            detached = self._before_entry(wire)
            if detached["batches"][0]["evidence_pins"]:
                _fail("before_invalid")
            head = self._write(detached)
            self._before_bytes = lineage._raw(detached)
            self._prepared = parse_producer_bundle_publication_journal(detached["batches"][0]["prepared_journal"])
            self._phase = "before"
            return head
        except BaseException:
            self._poisoned = True
            raise

    def _accept_prepared_reference(self, journal: object, record_sha256: object) -> None:
        from .producer_bundle_publication import ProducerBundlePublicationJournal
        lineage._publication_shapes(journal, record_sha256)
        if (self._phase != "before" or type(journal) is not ProducerBundlePublicationJournal
                or ProducerBundlePublicationJournal.to_dict(journal) != self._prepared.to_dict()
                or type(record_sha256) is not str or len(record_sha256) != 64
                or any(char not in "0123456789abcdef" for char in record_sha256)):
            _fail("prepared_reference_invalid")
        self._check_owner(captured=False)
        reference_head, reference_payload = self._wave.checkpoint_sha256, self._wave.payload
        captured, current = json.loads(self._payload), json.loads(reference_payload)
        refs = current.get("python_admission_refs", {})
        reference = refs.get(self._request.episode_id)
        if (type(reference) is not dict or reference.get("record_sha256") != record_sha256
                or reference.get("native_plan") != self._plan.to_dict()
                or reference.get("prepared_journal") != self._prepared.to_dict()
                or self._request.episode_id in captured.get("python_admission_refs", {})):
            _fail("prepared_reference_invalid")
        expected = json.loads(self._payload)
        expected["python_admission_refs"] = captured.get("python_admission_refs", {}) | {self._request.episode_id: reference}
        if expected != current or self._controller._python_admission_flow_payload(expected) != self._wave.payload:
            _fail("prepared_reference_delta_invalid")
        with self._ledger.read_only_observations():
            history = self._ledger.controller_checkpoint_history(self._run_id)
            if (len(history) < 2 or history[-2] != (self._head, captured)
                    or history[-1] != (reference_head, current)):
                _fail("prepared_reference_revision_invalid")
            retained = self._ledger.python_admission_record(
                self._run_id, self._request.episode_id, self._plan.journal_id, expected_record_sha256=record_sha256,
            )
            if retained.native_plan_sha256 != self._plan.plan_sha256:
                _fail("prepared_reference_invalid")
            self._controller._validate_python_admission_references(self._run_id, current)
        self._check_owner(captured=False)
        if (self._wave.checkpoint_sha256 != reference_head or self._wave.payload != reference_payload
                or reference_payload != self._controller._python_admission_flow_payload(current)):
            _fail("prepared_reference_delta_invalid")
        with self._ledger.read_only_observations():
            repeated = self._ledger.controller_checkpoint_history(self._run_id)
            if (repeated != history or repeated[-2] != (self._head, captured)
                    or repeated[-1] != (reference_head, current)):
                _fail("prepared_reference_revision_invalid")
        # Advance only to the originally observed adjacent reference, never a
        # same-payload later revision introduced by a reentrant hook.
        self._head, self._payload = reference_head, reference_payload
        self._phase = "prepared-reference"

    def acknowledge_prepared(self, journal: object, record_sha256: object) -> str:
        """Observe the exact reference CAS, then perform a separate evidence CAS."""
        try:
            self._identity(captured=False)
            self._accept_prepared_reference(journal, record_sha256)
            wire = self._before_entry(json.loads(self._before_bytes))
            path = self._workspace / "evolution/producer-batches" / self._plan.journal_id / "journal.prepared.json"
            pin = capture_lineage_snapshot_pin(path, name="journal.prepared.json")
            raw = _files.read_regular_file(path, lineage._MAX_CHECKPOINT_BYTES)
            if parse_producer_bundle_publication_journal(json.loads(raw)) != self._prepared:
                _fail("prepared_journal_drift")
            verify_persisted_lineage_snapshot(path, pin)
            wire["batches"][0]["evidence_pins"] = {"journal.prepared.json": pin.to_dict()}
            self._before_entry(wire)
            head = self._write(wire)
            self._phase = "prepared-evidence"
            return head
        except BaseException:
            self._poisoned = True
            raise

    def _success_scope(self, expected: str | None) -> None:
        current = self._retaining_success
        if (current is not None and (type(current) is not str or current not in {"staged", "terminal"})
                or current != expected or self._retaining_rejection is not False
                or (current is not None and self._retaining_before is not False)):
            _fail("success_retention_scope_drift")

    def _success_fixed(self, _stage: str | None = None) -> dict[str, Any]:
        """Observe fixed original pins only; never invoke hooks or reacquire the run lease."""
        self._identity()
        self._success_allowance()
        with self._ledger.read_only_observations():
            self._running()
            self._controller._python_admission_active_brs_owner(self._wave)
            self._history()
        self._before_channel()
        return self._state

    def _success_allowance(self) -> None:
        """Charge this retention's conservative monotonic cap without user callbacks."""
        if self._before_control_state() != self._before_control_pin:
            _fail("before_control_drift")
        if self._before_control is not None:
            with self._before_control._lock:
                if self._before_control._cancelled is not False:
                    _fail("before_control_cancelled")
        if self._success_deadline is not None:
            if self._retaining_success is None or type(self._success_deadline) is not float:
                _fail("success_allowance_drift")
            if time.monotonic() >= self._success_deadline:
                _fail("success_allowance_exhausted")

    def _success_cap_unchanged(self, expected: float | None) -> None:
        if ((expected is not None and type(expected) is not float)
                or self._success_deadline is not expected):
            _fail("success_allowance_drift")

    def _success_control_live(self, started: float) -> None:
        scope, allowance = self._retaining_success, self._success_deadline
        self._success_allowance()
        remaining = self._before_control_live()
        self._success_scope(scope)
        self._success_cap_unchanged(allowance)
        self._success_allowance()
        if remaining is not None and scope is not None:
            deadline = started + remaining
            if allowance is None:
                self._success_deadline = deadline
            else:
                self._success_deadline = min(allowance, deadline)
        self._success_allowance()

    def _success_observe(self, _stage: str | None = None) -> dict[str, Any]:
        """Run original full source/control observations outside publication locks."""
        self._before_unlocked()
        started = time.monotonic()
        self._check_owner()
        self._success_control_live(started)
        return self._success_fixed()

    def _success_capacity(self, wire: dict[str, Any]) -> int:
        """Bound real snapshot bytes and conservative new file pins before any create."""
        total = lineage.RSIPublicationLineage._retained_bytes(wire, self._state)
        projected = json.loads(lineage._raw(wire))
        entry = projected["batches"][0]
        maximum = 2**64 - 1
        names = ("staged_file_pin",) if entry["state"] == "staged" else ("terminal_file_pin",)
        pins = [entry[name] for name in names]
        if entry["state"] == "staged":
            pins.extend(entry["snapshots"][name] for name in ("archive-after", "state-after"))
        for pin in pins:
            pin.update({name: maximum for name in
                        ("device", "inode", "parent_device", "parent_inode", "mtime_ns", "ctime_ns")})
        lineage._raw(lineage._publication_lineage_checkpoint_delta(self._payload, projected))
        return total

    def retain_staged(self, staged: Any, manifest: Any) -> None:
        """Retain genuine native after evidence, then acknowledge its original BRS CAS."""
        from .producer_bundle_publication import ProducerBundlePublicationJournal
        from .producer_bundle_staging import ProducerBundlePublicationManifest

        if type(self) is not _BRSLineageCheckpointOwner:
            _fail("owner_invalid")
        try:
            self._before_unlocked()
            lineage._publication_shapes(staged, manifest)
            if (type(staged) is not ProducerBundlePublicationJournal
                    or type(manifest) is not ProducerBundlePublicationManifest
                    or self._phase != "prepared-evidence" or self._retaining_success is not None
                    or self._retaining_before is not False or self._plan.task_id != self._request.episode_id):
                _fail("staged_retention_unavailable")
            self._retaining_success = "staged"
            self._success_deadline = None
            self._success_observe()
            wire = json.loads(self._payload)[_FIELD]
            entry = wire["batches"][0]
            lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
            batch = recovery._batch(self._workspace, self._plan.journal_id)
            if (staged.journal_id != self._plan.journal_id or staged.state != "publishing"
                    or staged.publication_phase != "staged" or manifest.journal_id != staged.journal_id
                    or manifest.journal_sha256 != staged.digest()
                    or manifest.base_archive_sha256 != self._prepared.base_archive_sha256
                    or manifest.base_state_sha256 != self._prepared.base_state_sha256):
                _fail("staged_association_invalid")
            evidence = {name: capture_lineage_snapshot_pin(batch / name, name=name).to_dict()
                        for name in ("journal.staged.json", "manifest.json", "preflight.json")}
            if recovery._read_journal(batch / "journal.staged.json") != staged:
                _fail("staged_journal_drift")
            preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
            preflight_sha = recovery._check_preflight(preflight, staged,
                parse_producer_bundle_admission_plan(entry["admission_plan"]))
            raw_manifest = recovery._read_json(batch / "manifest.json", 256 * 1024)
            manifest_sha, ids, _paths, _files_map = recovery._manifest(raw_manifest, staged, preflight_sha)
            if manifest_sha != manifest.digest() or ids != manifest.candidate_ids or raw_manifest != manifest.to_dict():
                _fail("staged_manifest_drift")
            sources, contents, snapshots = {}, {}, {}
            for name in ("archive", "state"):
                path = batch / "stage" / (name + (".jsonl" if name == "archive" else ".json"))
                source = capture_lineage_snapshot_pin(path, name=name + "-after")
                raw = _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES)
                if lineage._sha(raw) != getattr(manifest, name + "_after_sha256") or source.sha256 != lineage._sha(raw):
                    _fail("staged_snapshot_drift")
                sources[name], contents[name] = source.to_dict(), raw
                snapshots[name + "-after"] = replace(source, name=name + "-after.snapshot").to_dict()
            transition = ProducerLineageStagedTransition(self._run_id, staged.journal_id, 0,
                entry["before"]["descriptor_sha256"], staged.digest(), manifest.digest(),
                manifest.archive_after_sha256, manifest.state_after_sha256, manifest.candidate_ids)
            capacity_pin = replace(LineageSnapshotPin.from_dict(sources["state"]), name="staged.json",
                sha256=lineage._sha(transition.to_json()), size=len(transition.to_json()))
            entry.update(state="staged", staged=transition.to_dict(), staged_file_pin=capacity_pin.to_dict(),
                state_projection_sha256=lineage._sha(contents["state"]), after_sources=sources)
            entry["snapshots"].update(snapshots)
            entry["evidence_pins"].update(evidence)
            self._success_capacity(wire)
            total = lineage.RSIPublicationLineage._retained_bytes(json.loads(self._payload)[_FIELD], self._state)
            self._success_observe()
            lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
            for name, pin in evidence.items():
                verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(pin))
            for name in ("archive", "state"):
                source = batch / "stage" / (name + (".jsonl" if name == "archive" else ".json"))
                path, pin = persist_lineage_snapshot(self._workspace, staged.journal_id,
                    name=name + "-after", source=source, expected_pin=LineageSnapshotPin.from_dict(sources[name]),
                    retained_bytes=total)
                if _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES) != contents[name]:
                    _fail("staged_snapshot_drift")
                verify_persisted_lineage_snapshot(path, pin)
                entry["snapshots"][name + "-after"] = pin.to_dict()
                total += pin.size
            _path, pin = persist_lineage_descriptor(self._workspace, transition)
            entry["staged_file_pin"] = pin.to_dict()
            self._success_scope("staged")
            _BRSLineageCheckpointOwner.checkpoint_staged(self, wire)
        except BaseException:
            self._poisoned = True
            raise
        finally:
            self._retaining_success = None
            self._success_deadline = None

    def verify_precommit(self, staged: Any, manifest: Any) -> None:
        """Read original staged evidence under its genuine lock, without user hooks."""
        from . import producer_bundle_staging as staging
        from .producer_bundle_publication import ProducerBundlePublicationJournal

        if type(self) is not _BRSLineageCheckpointOwner:
            _fail("owner_invalid")
        try:
            lineage._publication_shapes(staged, manifest)
            if (type(staged) is not ProducerBundlePublicationJournal
                    or type(manifest) is not staging.ProducerBundlePublicationManifest
                    or self._phase != "staged" or self._retaining_success is not None
                    or self._success_deadline is not None):
                _fail("precommit_state_invalid")
            held = staging._HELD_PUBLICATION_LOCKS.get()
            if not any(path.parent.parent == self._workspace for path, _fd, _info in held):
                _fail("publication_lock_required")
            staging._check_held_publication_lock()
            self._success_fixed()
            wire = self._success_entry(json.loads(self._payload)[_FIELD], phase="staged", observing=True)
            transition = ProducerLineageStagedTransition.from_dict(wire["batches"][0]["staged"])
            if (staged.journal_id != self._plan.journal_id or staged.digest() != transition.journal_sha256
                    or manifest.digest() != transition.manifest_sha256):
                _fail("precommit_association_invalid")
            marker, _raw_marker = staging._load_marker(self._workspace / "evolution/producer-publication.json")
            if (marker["status"] != "staged" or marker["journal_id"] != staged.journal_id
                    or marker["journal_sha256"] != staged.digest() or marker["manifest_sha256"] != manifest.digest()):
                _fail("precommit_marker_drift")
            self._success_fixed()
            staging._check_held_publication_lock()
        except BaseException:
            self._poisoned = True
            raise

    def retain_terminal(self, published: Any, manifest: Any) -> None:
        """Retain an already published native success terminal; never commit or settle."""
        from .producer_bundle_publication import ProducerBundlePublicationJournal
        from .producer_bundle_staging import ProducerBundlePublicationManifest

        if type(self) is not _BRSLineageCheckpointOwner:
            _fail("owner_invalid")
        try:
            self._before_unlocked()
            lineage._publication_shapes(published, manifest)
            if (type(published) is not ProducerBundlePublicationJournal
                    or type(manifest) is not ProducerBundlePublicationManifest or self._phase != "staged"
                    or self._retaining_success is not None or self._retaining_before is not False):
                _fail("terminal_retention_unavailable")
            self._retaining_success = "terminal"
            self._success_deadline = None
            self._success_observe()
            wire = json.loads(self._payload)[_FIELD]
            entry = wire["batches"][0]
            transition = self._verify_descriptor(entry, "staged")
            batch = recovery._batch(self._workspace, self._plan.journal_id)
            if (published.journal_id != self._plan.journal_id or published.state != "published"
                    or published.publication_phase != "committed" or manifest.digest() != transition.manifest_sha256
                    or published.archive_after_sha256 != transition.archive_after_sha256
                    or published.state_after_sha256 != transition.state_after_sha256
                    or tuple(item.candidate_id for item in published.candidates if item.status == "admitted")
                        != transition.candidate_ids):
                _fail("terminal_association_invalid")
            evidence = {name: capture_lineage_snapshot_pin(batch / name, name=name).to_dict()
                        for name in ("journal.published.json", "terminal.json")}
            if recovery._read_journal(batch / "journal.published.json") != published:
                _fail("published_journal_drift")
            observed = recovery._verify_terminal_batch_evidence(self._workspace, batch, published, manifest.digest())
            if observed.terminal_marker_sha256 != published.terminal_marker_sha256:
                _fail("terminal_marker_drift")
            lineage._require_marker_absent(self._workspace)
            terminal = ProducerLineageTerminal(self._run_id, published.journal_id, 0, transition.digest(),
                published.terminal_marker_sha256, transition.archive_after_sha256, transition.state_after_sha256)
            head_sources = {name: capture_lineage_snapshot_pin(self._workspace / "evolution" /
                (name + (".jsonl" if name == "archive" else ".json")), name=name + "-before").to_dict()
                for name in ("archive", "state")}
            capacity_pin = replace(LineageSnapshotPin.from_dict(head_sources["state"]), name="terminal.json",
                sha256=lineage._sha(terminal.to_json()), size=len(terminal.to_json()))
            entry.update(state="terminal", terminal=terminal.to_dict(), terminal_file_pin=capacity_pin.to_dict(),
                published_journal=published.to_dict(), head_sources=head_sources)
            entry["evidence_pins"].update(evidence)
            wire["head"] = {"journal_id": published.journal_id, "terminal_sha256": terminal.terminal_sha256,
                "lineage_sha256": terminal.digest()}
            self._success_capacity(wire)
            self._success_observe()
            for name, pin in evidence.items():
                verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(pin))
            _path, pin = persist_lineage_descriptor(self._workspace, terminal)
            entry["terminal_file_pin"] = pin.to_dict()
            self._success_scope("terminal")
            _BRSLineageCheckpointOwner.checkpoint_terminal(self, wire)
        except BaseException:
            self._poisoned = True
            raise
        finally:
            self._retaining_success = None
            self._success_deadline = None

    def checkpoint_staged(self, wire: object) -> str:
        """Acknowledge existing staged success evidence, without staging artifacts."""
        try:
            self._check_owner()
            detached = self._success_entry(wire, phase="staged")
            head = self._write(detached)
            self._phase = "staged"
            return head
        except BaseException:
            self._poisoned = True
            raise

    def checkpoint_terminal(self, wire: object) -> str:
        """Acknowledge an existing success terminal while the claim is still started."""
        try:
            self._check_owner()
            detached = self._success_entry(wire, phase="terminal")
            head = self._write(detached)
            self._phase = "terminal"
            return head
        except BaseException:
            self._poisoned = True
            raise

    _rejection_scope = rejection._rejection_scope
    _rejection_allowance = rejection._rejection_allowance
    _rejection_cap_unchanged = rejection._rejection_cap_unchanged
    _rejection_control_live = rejection._rejection_control_live
    _rejection_fixed = rejection._rejection_fixed
    _rejection_observe = rejection._rejection_observe
    _rejection_materials = rejection._rejection_materials
    _rejection_capacity = rejection._rejection_capacity
    _rejected_entry = rejection._rejected_entry
    _rejection_readback = rejection._rejection_readback
    _rejection_readback_observe = rejection._rejection_readback_observe
    _rejection_final_readback = rejection._rejection_final_readback
    retain_rejected_terminal = rejection.retain_rejected_terminal
    checkpoint_rejected = rejection.checkpoint_rejected
    rejection_provenance_binding = provenance.rejection_provenance_binding
    retain_rejection_provenance = provenance.retain_rejection_provenance
    acknowledge_rejection_provenance = provenance.acknowledge_rejection_provenance
    rejection_provenance_file_pin = provenance.rejection_provenance_file_pin
    retain_rejection_ready_capture = ready_owner.retain_rejection_ready_capture
    service_rejection_ready = ready_service.service_rejection_ready
