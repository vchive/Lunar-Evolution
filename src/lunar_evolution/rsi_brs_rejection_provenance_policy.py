"""Finite original native P dependencies, without dispatch or owner authority.

The enclosing BRS policy also binds this module's source and its policy helpers.
Shared canonical JSON, DirectoryChain, journal/rejected/handoff DTOs and source
identities remain covered by that policy; this projection checks their live
native imports and the methods actually used by native P as well.
"""

from __future__ import annotations

import dataclasses
import gc
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import sys
from types import FunctionType, MappingProxyType, ModuleType

from . import _candidate_workspace_io as workspace_io
from . import candidate_evaluation_spec as json_spec
from . import producer_bundle_lineage_v2 as lineage_v2
from . import producer_bundle_publication as publication
from . import python_producer_admission_handoff as handoff
from . import rsi_gateway as gateway
from . import rsi_identity as identity
from . import rsi_native_plan as native_plan
from . import rsi_native_provenance_names as provenance_names
from . import rsi_native_rejection as native
from . import rsi_native_scheduler as scheduler
from . import rsi_store as store
from .rsi_learning import RSILearningError


def _fail() -> None:
    raise RSILearningError("rsi_brs_publication_lineage_rejection_provenance_policy_drift")


def _capture_function(group, owner, name):
    """Capture only explicit declarations; never follow a discovered call graph."""
    member = vars(owner)[name]
    function = member.__func__ if type(member) in {classmethod, staticmethod} else (
        member.fget if type(member) is property else member)
    if type(function) is not FunctionType:
        raise TypeError("native P policy requires declared Python functions")
    namespace = vars(owner if type(owner) is ModuleType else sys.modules[owner.__module__])
    if function.__globals__ is not namespace:
        _fail()
    return (group, owner, name, member, function, namespace, function.__code__,
            function.__defaults__, function.__kwdefaults__,
            tuple((function.__kwdefaults__ or {}).items()), function.__closure__,
            tuple(cell.cell_contents for cell in (function.__closure__ or ())),
            tuple(function.__dict__.items()))


_FUNCTION_GROUPS = (
    ("native", native, (
        "_fail", "_canonical", "_sha", "_identifier", "_integer", "_shape", "_plain_mapping",
        "_dto_shape", "_ids", "_digests", "_reparse", "_ledger_identity", "_metadata", "_directory",
        "_assert_exclusive", "_pin", "_read_once", "_record", "_read",
        "read_native_rsi_rejection_provenance", "persist_native_rsi_rejection_provenance")),
    *(("dto", kind, ("__init__", "__post_init__", "to_dict", "from_dict", "__eq__")) for kind in (
        native.NativeRSIRejectionFilePin, native.RejectionLineageC1Binding, native.NativeRSIRejectionEvidence)),
    ("dto", native.NativeRSIRejectionEvidence, ("claim_sha256",)),
    ("dto", native.NativeRSIRejectionError, ("__init__",)),
    ("ledger", scheduler, ("_read_ledger_identity", "_fail")),
    ("ledger", scheduler.NativeRSISchedulerProviderError, ("__init__",)),
    ("ledger", store.NativeEpisodeClaim, ("__init__", "to_dict", "__eq__")),
    ("ledger", store.RSILedger, ("_native_claim_digest",)),
    ("plan", native_plan, ("_fail", "_id", "_sha", "_digest", "_strict_mapping")),
    ("plan", native_plan.NativeRSIExecutionPlan, (
        "__init__", "__post_init__", "to_dict", "from_dict", "digest", "__eq__")),
    ("plan", native_plan.NativeRSIExecutionPlanError, ("__init__",)),
    ("request", gateway, ("_digest", "_id", "_record_digest", "_bounded_map", "_wire_record")),
    ("request", gateway.SolverRequest, (
        "__init__", "__post_init__", "build", "from_dict", "to_dict", "digest", "__eq__")),
    ("json", json_spec, ("canonical_json", "strict_json", "_fail", "_maximum", "_json_bytes")),
    ("identity", identity, ("component_fingerprint",)),
    ("directory", workspace_io, ("fail", "identity")),
    ("directory", workspace_io.DirectoryChain, ("__init__", "fd", "check", "close")),
    ("path", pathlib.Path, ("__new__", "absolute", "expanduser")),
    ("path", pathlib.PurePath, ("__str__", "__fspath__", "is_absolute", "parts", "parent", "name", "anchor")),
    ("shared_dto", lineage_v2.ProducerLineageRejectedTerminalV2, (
        "__init__", "__post_init__", "_validated_payload", "to_dict", "to_json", "digest", "from_dict", "__eq__")),
    ("shared_dto", publication.ProducerBundlePublicationJournal, (
        "__init__", "__post_init__", "_payload_dict", "to_dict", "from_dict", "digest", "__eq__")),
    ("shared_dto", publication.ProducerBundlePublicationCandidate, (
        "__init__", "__post_init__", "to_dict", "from_dict", "__eq__")),
    ("shared_dto", handoff.PythonProducerAdmissionHandoffFilePin, (
        "__init__", "__post_init__", "_payload", "to_dict", "__eq__")),
)
_FUNCTION_BINDINGS = tuple(_capture_function(group, owner, name)
                           for group, owner, names in _FUNCTION_GROUPS for name in names)

# Capture canonical import edges independently. Replacing both an application
# alias and its apparent canonical module member with one foreign clone fails.
_ALIASES = (
    *((native, name, original) for name, original in (
        ("gc", gc), ("hashlib", hashlib), ("os", os), ("re", re), ("stat", stat),
        ("fields", dataclasses.fields), ("MappingProxyType", MappingProxyType),
        ("DirectoryChain", workspace_io.DirectoryChain), ("canonical_json", json_spec.canonical_json),
        ("strict_json", json_spec.strict_json), ("Path", pathlib.Path),
        ("PosixPath", pathlib.PosixPath), ("WindowsPath", pathlib.WindowsPath),
        ("NativeRSIExecutionPlan", native_plan.NativeRSIExecutionPlan),
        ("SolverRequest", gateway.SolverRequest), ("NativeEpisodeClaim", store.NativeEpisodeClaim),
        ("RSILedger", store.RSILedger), ("ProducerBundlePublicationJournal", publication.ProducerBundlePublicationJournal),
        ("ProducerBundlePublicationCandidate", publication.ProducerBundlePublicationCandidate),
        ("ProducerLineageRejectedTerminalV2", lineage_v2.ProducerLineageRejectedTerminalV2),
        ("PythonProducerAdmissionHandoffFilePin", handoff.PythonProducerAdmissionHandoffFilePin),
    )),
    *((scheduler, name, original) for name, original in (
        ("DirectoryChain", workspace_io.DirectoryChain), ("os", os), ("stat", stat), ("RSILedger", store.RSILedger))),
    *((workspace_io, name, original) for name, original in (
        ("os", os), ("stat", stat), ("sys", sys), ("Path", pathlib.Path))),
    (os, "path", os.path),
    *((pathlib, name, vars(pathlib)[name]) for name in ("Path", "PurePath", "PosixPath", "WindowsPath")),
    (json_spec, "json", json), (json_spec, "math", math),
    *((native_plan, name, original) for name, original in (
        ("hashlib", hashlib), ("math", math), ("canonical_json", json_spec.canonical_json),
        ("strict_json", json_spec.strict_json), ("SolverRequest", gateway.SolverRequest))),
    (gateway, "hashlib", hashlib), (gateway, "canonical_json", json_spec.canonical_json),
    (store, "hashlib", hashlib), (store, "canonical_json", json_spec.canonical_json),
    *((owner, name, vars(owner)[name]) for owner, names in (
        (native, ("NativeRSIRejectionEvidence", "NativeRSIRejectionFilePin", "RejectionLineageC1Binding", "NativeRSIRejectionError")),
        (scheduler, ("NativeRSISchedulerProviderError",)), (workspace_io, ("DirectoryChain",)),
        (native_plan, ("NativeRSIExecutionPlan",)), (gateway, ("Mapping", "SolverRequest")),
        (store, ("NativeEpisodeClaim", "RSILedger")), (lineage_v2, ("ProducerLineageRejectedTerminalV2",)),
        (publication, ("ProducerBundlePublicationJournal", "ProducerBundlePublicationCandidate")),
        (handoff, ("PythonProducerAdmissionHandoffFilePin",)), (dataclasses, ("_FIELD",)),
        (identity, ("component_fingerprint",)),
    ) for name in names),
)
_RUNTIME = tuple((owner, name, vars(owner)[name], getattr(vars(owner)[name], "__code__", None))
                 for owner, names in (
                     (os, ("open", "read", "write", "fchmod", "fsync", "fstat", "stat", "close", "getcwd")),
                     (stat, ("S_ISREG", "S_ISDIR", "S_IMODE")),
                     (gc, ("get_referents",)), (dataclasses, ("fields",)),
                     (json, ("loads", "dumps")), (hashlib, ("sha256",)), (math, ("isfinite",)),
                     (sys, ("exception",)), (os.path, ("expanduser",)),
                 ) for name in names)
_RUNTIME_FUNCTIONS = tuple(_capture_function("runtime", owner, name)
                           for owner, name, function, _code in _RUNTIME if type(function) is FunctionType)


def _constant(value):
    """Project only the bounded primitive constants declared below."""
    if type(value) in {str, int}:
        return value
    if type(value) is set and all(type(item) is str for item in value):
        return sorted(value)
    if type(value) is tuple and all(type(item) is str for item in value):
        return list(value)
    if type(value) is re.Pattern and type(value.pattern) is str:
        return [value.pattern, value.flags]
    _fail()


_CONSTANTS = tuple((group, owner, name, type(vars(owner)[name]), _constant(vars(owner)[name]))
                  for group, owner, names in (
                      ("native", native, (
                          "MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES", "MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES",
                          "MAX_LINEAGE_BATCHES", "_PROTOCOL", "_C1_PROTOCOL", "_SHA", "_ID", "_MAX_INT",
                          "_PIN_FIELDS", "_C1_FIELDS", "_PAYLOAD_FIELDS", "_CLAIM_FIELDS",
                          "NATIVE_RSI_PROVENANCE_NAMES", "NATIVE_RSI_REJECTION_PROVENANCE_NAME")),
                      ("names", provenance_names, ("NATIVE_RSI_PROVENANCE_NAMES", "NATIVE_RSI_REJECTION_PROVENANCE_NAME")),
                      ("plan", native_plan, ("_PROTOCOL", "_SCHEMA_VERSION", "_SHA", "_ID", "_MAX_BYTES", "_TOP_FIELDS")),
                      ("request", gateway, ("MAX_SOLVER_SETTINGS", "MAX_SOLVER_BUDGET")),
                      ("directory", workspace_io, ("_FLAGS",)),
                      ("dataclasses", dataclasses, ("_FIELDS",)),
                      ("os", os, ("O_RDONLY", "O_RDWR", "O_CREAT", "O_EXCL", "O_NOFOLLOW",
                                  "O_NONBLOCK", "O_CLOEXEC", "O_DIRECTORY")),
                  ) for name in names)
_DTO_FIELDS = tuple((kind, vars(kind)["__dataclass_fields__"],
                     tuple((name, field, field.name, field._field_type)
                           for name, field in vars(kind)["__dataclass_fields__"].items()))
                    for kind in (
                        native.NativeRSIRejectionFilePin, native.RejectionLineageC1Binding,
                        native.NativeRSIRejectionEvidence, native_plan.NativeRSIExecutionPlan,
                        gateway.SolverRequest, store.NativeEpisodeClaim,
                        lineage_v2.ProducerLineageRejectedTerminalV2,
                        publication.ProducerBundlePublicationJournal,
                        publication.ProducerBundlePublicationCandidate,
                        handoff.PythonProducerAdmissionHandoffFilePin,
                    ))


def _check_function(binding) -> None:
    (_group, owner, name, member, function, namespace, code, defaults, kwdefaults,
     kwitems, closure, captures, attributes) = binding
    if (vars(owner).get(name) is not member or type(function) is not FunctionType
            or function.__globals__ is not namespace or function.__code__ is not code
            or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
            or function.__closure__ is not closure):
        _fail()
    for current, saved in ((function.__kwdefaults__ or {}, kwitems), (function.__dict__, attributes)):
        if (type(current) is not dict or any(type(key) is not str for key in current)
                or set(current) != {key for key, _value in saved}
                or any(current[key] is not value for key, value in saved)):
            _fail()
    for cell, value in zip(closure or (), captures):
        try:
            if cell.cell_contents is not value:
                _fail()
        except ValueError:
            _fail()


def native_rejection_provenance_policy() -> dict[str, object]:
    """Check canonical live bindings before computing the finite P source pins."""
    for owner, name, original in _ALIASES:
        if vars(owner).get(name) is not original:
            _fail()
    for owner, name, original, code in _RUNTIME:
        current = vars(owner).get(name)
        if current is not original or getattr(current, "__code__", None) is not code:
            _fail()
    for binding in (*_FUNCTION_BINDINGS, *_RUNTIME_FUNCTIONS):
        _check_function(binding)
    constants: dict[str, dict[str, object]] = {}
    for group, owner, name, kind, original in _CONSTANTS:
        current = vars(owner).get(name)
        if type(current) is not kind or _constant(current) != original:
            _fail()
        constants.setdefault(group, {})[name] = _constant(current)
    dto_fields = {}
    for kind, table, saved in _DTO_FIELDS:
        current = vars(kind).get("__dataclass_fields__")
        if (current is not table or type(current) is not dict
                or any(type(name) is not str for name in current)
                or set(current) != {name for name, _field, _label, _field_type in saved}):
            _fail()
        for name, field, label, field_type in saved:
            if (current[name] is not field or type(field.name) is not str
                    or field.name != label or field._field_type is not field_type):
                _fail()
        dto_fields[kind.__name__] = [label for _name, _field, label, _field_type in saved]
    functions: dict[str, dict[str, str]] = {}
    for group, owner, name, _member, function, *_rest in (*_FUNCTION_BINDINGS, *_RUNTIME_FUNCTIONS):
        label = name if type(owner) is type(native) else owner.__name__ + "." + name
        functions.setdefault(group, {})[label] = identity.component_fingerprint(function, config={})
    return {"functions": functions, "constants": constants, "dto_fields": dto_fields,
            "native_pin_mode": 0o400, "native_pin_nlink": 1}


__all__ = ["native_rejection_provenance_policy"]
