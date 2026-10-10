"""Canonical journal DTOs for producer-bundle publication transactions.

This module records a bounded transaction intent only.  It does not execute candidates, evaluate
sources, publish an archive, or resume a transaction.  The later publication layer will use the
journal digest as an authority boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

from . import _benchmark_files as _files
from .candidate_evaluation_spec import strict_json
from .producer_bundle_handoff import ProducerBundleHandoffError
from .producer_bundle_handoff import _identifier as _producer_identifier
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoffError,
    PythonProducerAdmissionHandoffFilePin,
    parse_python_producer_admission_handoff_file_pin,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = "1"
_PROTOCOL = "lunar-producer-bundle-publication-v1"
MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES = 256 * 1024
MAX_PUBLICATION_CANDIDATES = 32

_CANDIDATE_FIELDS = {
    "candidate_id", "bundle_id", "bundle_sha256", "parent_id", "generation", "iteration",
    "island_id", "preparation_receipt_sha256", "execution_receipt_sha256",
    "evaluation_receipt_sha256", "publication_receipt_sha256", "status",
}
_JOURNAL_FIELDS = {
    "schema_version", "protocol", "journal_id", "run_id", "parent_task_id", "task_id",
    "admission_sha256", "archive_prefix_sha256", "base_archive_sha256", "base_state_sha256",
    "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
    "dependency_sha256", "environment_sha256", "budget_sha256", "strategy",
    "population_config_sha256", "num_islands", "candidates", "state", "publication_phase",
    "terminal_marker_sha256", "archive_after_sha256", "state_after_sha256", "journal_sha256",
}
_JOURNAL_OPTIONAL_FIELDS = {
    "native_execution_receipt_sha256",
    # Feature 191 Python-worker handoff identity.  Optional so legacy/non-Python
    # journals retain their exact canonical bytes and digest.
    "python_handoff_sha256",
    "python_handoff_file_pin",
}
_STATES = frozenset({"prepared", "executing", "publishing", "published", "all_rejected", "failed", "unknown"})
_PHASES = frozenset({"preflight", "staged", "committed", "recovery_required"})
_STATE_PHASES = {
    "prepared": "preflight",
    "executing": "staged",
    "publishing": "staged",
    "published": "committed",
    "all_rejected": "committed",
    "failed": "recovery_required",
    "unknown": "recovery_required",
}
_CANDIDATE_STATUSES = frozenset({"planned", "rejected", "admitted", "unknown"})


class ProducerBundlePublicationError(ValueError):
    """Fixed-code publication-journal failure without caller-controlled prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundlePublicationError(code)


def _digest(value: object, code: str = "producer_bundle_publication_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _identifier(value: object, code: str = "producer_bundle_publication_identifier_invalid") -> str:
    try:
        return _producer_identifier(value, code)
    except ProducerBundleHandoffError:
        _fail(code)


def _optional_identifier(value: object, code: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, code)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundlePublicationError("producer_bundle_publication_canonical_invalid") from exc
    if len(encoded) > MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES:
        _fail("producer_bundle_publication_too_large")
    return encoded


def _object(value: object, fields: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code)
    return value


def _bounded_int(value: object, code: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        _fail(code)
    return value


@dataclass(frozen=True, slots=True)
class ProducerBundlePublicationCandidate:
    """One fixed candidate slot in a producer-bundle publication journal."""

    candidate_id: str
    bundle_id: str
    bundle_sha256: str
    parent_id: str | None
    generation: int
    iteration: int
    island_id: int
    preparation_receipt_sha256: str
    execution_receipt_sha256: str | None = None
    evaluation_receipt_sha256: str | None = None
    publication_receipt_sha256: str | None = None
    status: str = "planned"

    def __post_init__(self) -> None:
        _identifier(self.candidate_id, "producer_bundle_publication_candidate_id_invalid")
        _identifier(self.bundle_id, "producer_bundle_publication_bundle_id_invalid")
        _digest(self.bundle_sha256, "producer_bundle_publication_bundle_digest_invalid")
        _optional_identifier(self.parent_id, "producer_bundle_publication_parent_id_invalid")
        _bounded_int(self.generation, "producer_bundle_publication_generation_invalid", maximum=1_000_000)
        _bounded_int(self.iteration, "producer_bundle_publication_iteration_invalid", maximum=1_000_000)
        _bounded_int(self.island_id, "producer_bundle_publication_island_invalid", maximum=4096)
        _digest(self.preparation_receipt_sha256, "producer_bundle_publication_preparation_receipt_invalid")
        for value, code in (
            (self.execution_receipt_sha256, "producer_bundle_publication_execution_receipt_invalid"),
            (self.evaluation_receipt_sha256, "producer_bundle_publication_evaluation_receipt_invalid"),
            (self.publication_receipt_sha256, "producer_bundle_publication_publication_receipt_invalid"),
        ):
            if value is not None:
                _digest(value, code)
        if not isinstance(self.status, str) or self.status not in _CANDIDATE_STATUSES:
            _fail("producer_bundle_publication_candidate_status_invalid")
        if self.parent_id == self.candidate_id:
            _fail("producer_bundle_publication_parent_cycle")
        if (
            (self.evaluation_receipt_sha256 is not None and self.execution_receipt_sha256 is None)
            or (self.publication_receipt_sha256 is not None
                and (self.evaluation_receipt_sha256 is None or self.status != "admitted"))
            or (self.status == "admitted" and self.evaluation_receipt_sha256 is None)
            or (self.status == "planned" and any(value is not None for value in (
                self.execution_receipt_sha256, self.evaluation_receipt_sha256,
                self.publication_receipt_sha256,
            )))
        ):
            _fail("producer_bundle_publication_receipt_sequence_invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "bundle_id": self.bundle_id,
            "bundle_sha256": self.bundle_sha256,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "iteration": self.iteration,
            "island_id": self.island_id,
            "preparation_receipt_sha256": self.preparation_receipt_sha256,
            "execution_receipt_sha256": self.execution_receipt_sha256,
            "evaluation_receipt_sha256": self.evaluation_receipt_sha256,
            "publication_receipt_sha256": self.publication_receipt_sha256,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundlePublicationCandidate:
        raw = _object(value, _CANDIDATE_FIELDS, "producer_bundle_publication_candidate_schema_invalid")
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProducerBundlePublicationJournal:
    """Canonical authority and recovery descriptor for one producer-bundle batch."""

    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    admission_sha256: str
    archive_prefix_sha256: str
    base_archive_sha256: str
    base_state_sha256: str
    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    runner_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    budget_sha256: str
    strategy: str
    population_config_sha256: str
    num_islands: int
    candidates: tuple[ProducerBundlePublicationCandidate, ...]
    state: str = "prepared"
    publication_phase: str = "preflight"
    terminal_marker_sha256: str | None = None
    archive_after_sha256: str | None = None
    state_after_sha256: str | None = None
    # Optional Feature 156 formal process receipt identity.  It is omitted from legacy
    # journals when absent so their canonical bytes and digest remain unchanged.
    native_execution_receipt_sha256: str | None = None
    journal_sha256: str | None = None
    schema_version: str = _SCHEMA_VERSION
    protocol: str = _PROTOCOL
    python_handoff_sha256: str | None = None
    python_handoff_file_pin: PythonProducerAdmissionHandoffFilePin | None = None

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION or self.protocol != _PROTOCOL:
            _fail("producer_bundle_publication_schema_invalid")
        for name, value in (
            ("journal_id", self.journal_id), ("run_id", self.run_id),
            ("parent_task_id", self.parent_task_id), ("task_id", self.task_id),
        ):
            _identifier(value, f"producer_bundle_publication_{name}_invalid")
        for name, value in (
            ("admission_sha256", self.admission_sha256), ("archive_prefix_sha256", self.archive_prefix_sha256),
            ("base_archive_sha256", self.base_archive_sha256), ("base_state_sha256", self.base_state_sha256),
            ("contract_sha256", self.contract_sha256), ("evaluator_fingerprint", self.evaluator_fingerprint),
            ("runner_fingerprint", self.runner_fingerprint), ("dependency_sha256", self.dependency_sha256),
            ("environment_sha256", self.environment_sha256), ("budget_sha256", self.budget_sha256),
            ("population_config_sha256", self.population_config_sha256),
        ):
            _digest(value, f"producer_bundle_publication_{name}_invalid")
        _identifier(self.evaluator_kind, "producer_bundle_publication_evaluator_kind_invalid")
        if self.strategy != "population":
            _fail("producer_bundle_publication_strategy_invalid")
        _bounded_int(self.num_islands, "producer_bundle_publication_num_islands_invalid", maximum=4096)
        if self.num_islands == 0:
            _fail("producer_bundle_publication_num_islands_invalid")
        if (
            not isinstance(self.candidates, tuple)
            or not 1 <= len(self.candidates) <= MAX_PUBLICATION_CANDIDATES
            or any(not isinstance(item, ProducerBundlePublicationCandidate) for item in self.candidates)
        ):
            _fail("producer_bundle_publication_candidates_invalid")
        try:
            normalized = tuple(ProducerBundlePublicationCandidate.from_dict(item.to_dict())
                               for item in self.candidates)
        except ProducerBundlePublicationError:
            raise
        except Exception as exc:
            raise ProducerBundlePublicationError("producer_bundle_publication_candidates_invalid") from exc
        object.__setattr__(self, "candidates", normalized)
        candidate_ids = [item.candidate_id for item in self.candidates]
        bundle_ids = [item.bundle_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            _fail("producer_bundle_publication_candidate_duplicate")
        if len(bundle_ids) != len(set(bundle_ids)):
            _fail("producer_bundle_publication_bundle_duplicate")
        if any(item.island_id >= self.num_islands for item in self.candidates):
            _fail("producer_bundle_publication_island_invalid")
        if not isinstance(self.state, str) or self.state not in _STATES:
            _fail("producer_bundle_publication_state_invalid")
        if not isinstance(self.publication_phase, str) or self.publication_phase not in _PHASES:
            _fail("producer_bundle_publication_phase_invalid")
        if _STATE_PHASES[self.state] != self.publication_phase:
            _fail("producer_bundle_publication_state_phase_invalid")
        for name, value in (
            ("terminal_marker_sha256", self.terminal_marker_sha256),
            ("archive_after_sha256", self.archive_after_sha256),
            ("state_after_sha256", self.state_after_sha256),
            ("native_execution_receipt_sha256", self.native_execution_receipt_sha256),
            ("python_handoff_sha256", self.python_handoff_sha256),
            ("journal_sha256", self.journal_sha256),
        ):
            if value is not None:
                _digest(value, f"producer_bundle_publication_{name}_invalid")
        if self.python_handoff_sha256 is not None and self.native_execution_receipt_sha256 is None:
            _fail("producer_bundle_publication_python_handoff_execution_link_missing")
        if self.python_handoff_file_pin is not None:
            try:
                pin = parse_python_producer_admission_handoff_file_pin(self.python_handoff_file_pin)
            except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
                raise ProducerBundlePublicationError(
                    "producer_bundle_publication_python_handoff_pin_invalid"
                ) from exc
            if (
                self.python_handoff_sha256 is None
                or pin.handoff_sha256 != self.python_handoff_sha256
                or pin.run_id != self.run_id
                or pin.journal_id != self.journal_id
                or pin.parent_task_id != self.parent_task_id
                or pin.task_id != self.task_id
            ):
                _fail("producer_bundle_publication_python_handoff_pin_mismatch")
            object.__setattr__(self, "python_handoff_file_pin", pin)
        receipts = [value for item in self.candidates for value in (
            item.preparation_receipt_sha256, item.execution_receipt_sha256,
            item.evaluation_receipt_sha256, item.publication_receipt_sha256,
        ) if value is not None]
        if len(receipts) != len(set(receipts)):
            _fail("producer_bundle_publication_receipt_reused")
        statuses = {item.status for item in self.candidates}
        if self.state == "prepared" and statuses != {"planned"}:
            _fail("producer_bundle_publication_state_candidates_invalid")
        if self.state in {"publishing", "published"} and (
            not statuses <= {"admitted", "rejected"} or "admitted" not in statuses
        ):
            _fail("producer_bundle_publication_state_candidates_invalid")
        if self.state == "all_rejected" and statuses != {"rejected"}:
            _fail("producer_bundle_publication_state_candidates_invalid")
        if self.state not in {"unknown", "failed"} and "unknown" in statuses:
            _fail("producer_bundle_publication_state_candidates_invalid")
        terminal = (self.terminal_marker_sha256, self.archive_after_sha256, self.state_after_sha256)
        if self.state == "all_rejected":
            if (
                any(value is None for value in terminal)
                or self.archive_after_sha256 != self.base_archive_sha256
                or self.state_after_sha256 != self.base_state_sha256
                or any(item.execution_receipt_sha256 is None
                       or item.evaluation_receipt_sha256 is None
                       or item.publication_receipt_sha256 is not None
                       for item in self.candidates)
            ):
                _fail("producer_bundle_publication_terminal_evidence_invalid")
        elif self.state == "published":
            if any(value is None for value in terminal) or any(
                item.status == "admitted" and item.publication_receipt_sha256 is None
                for item in self.candidates
            ):
                _fail("producer_bundle_publication_terminal_evidence_invalid")
        elif self.state != "unknown" and any(value is not None for value in terminal):
            _fail("producer_bundle_publication_terminal_evidence_invalid")
        if self.state in {"prepared", "executing", "failed"} and any(
            item.publication_receipt_sha256 is not None for item in self.candidates
        ):
            _fail("producer_bundle_publication_terminal_evidence_invalid")
        expected = hashlib.sha256(_canonical(self._payload_dict())).hexdigest()
        if self.journal_sha256 is None:
            object.__setattr__(self, "journal_sha256", expected)
        elif self.journal_sha256 != expected:
            _fail("producer_bundle_publication_journal_digest_mismatch")
        _canonical(self.to_dict())

    def _payload_dict(self) -> dict[str, object]:
        payload = self.to_dict(include_journal_sha256=False)
        return payload

    def to_dict(self, *, include_journal_sha256: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "journal_id": self.journal_id,
            "run_id": self.run_id,
            "parent_task_id": self.parent_task_id,
            "task_id": self.task_id,
            "admission_sha256": self.admission_sha256,
            "archive_prefix_sha256": self.archive_prefix_sha256,
            "base_archive_sha256": self.base_archive_sha256,
            "base_state_sha256": self.base_state_sha256,
            "contract_sha256": self.contract_sha256,
            "evaluator_kind": self.evaluator_kind,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "runner_fingerprint": self.runner_fingerprint,
            "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
            "budget_sha256": self.budget_sha256,
            "strategy": self.strategy,
            "population_config_sha256": self.population_config_sha256,
            "num_islands": self.num_islands,
            "candidates": [item.to_dict() for item in self.candidates],
            "state": self.state,
            "publication_phase": self.publication_phase,
            "terminal_marker_sha256": self.terminal_marker_sha256,
            "archive_after_sha256": self.archive_after_sha256,
            "state_after_sha256": self.state_after_sha256,
        }
        if self.native_execution_receipt_sha256 is not None:
            value["native_execution_receipt_sha256"] = self.native_execution_receipt_sha256
        if self.python_handoff_sha256 is not None:
            value["python_handoff_sha256"] = self.python_handoff_sha256
        if self.python_handoff_file_pin is not None:
            try:
                pin = parse_python_producer_admission_handoff_file_pin(self.python_handoff_file_pin)
            except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
                raise ProducerBundlePublicationError(
                    "producer_bundle_publication_python_handoff_pin_invalid"
                ) from exc
            value["python_handoff_file_pin"] = pin.to_dict()
        if include_journal_sha256:
            value["journal_sha256"] = self.journal_sha256
        return value

    def digest(self) -> str:
        try:
            normalized = parse_producer_bundle_publication_journal(self.to_dict())
            return hashlib.sha256(_canonical(normalized._payload_dict())).hexdigest()
        except ProducerBundlePublicationError:
            raise
        except Exception as exc:
            raise ProducerBundlePublicationError("producer_bundle_publication_journal_invalid") from exc

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundlePublicationJournal:
        if not isinstance(value, dict):
            _fail("producer_bundle_publication_schema_invalid")
        keys = set(value)
        if not _JOURNAL_FIELDS <= keys or not (keys - _JOURNAL_FIELDS) <= _JOURNAL_OPTIONAL_FIELDS:
            _fail("producer_bundle_publication_schema_invalid")
        raw = value
        if "native_execution_receipt_sha256" in raw and raw["native_execution_receipt_sha256"] is None:
            _fail("producer_bundle_publication_execution_receipt_link_invalid")
        if "python_handoff_sha256" in raw and raw["python_handoff_sha256"] is None:
            _fail("producer_bundle_publication_python_handoff_link_invalid")
        if "python_handoff_file_pin" in raw and raw["python_handoff_file_pin"] is None:
            _fail("producer_bundle_publication_python_handoff_pin_invalid")
        if "python_handoff_file_pin" in raw and type(raw["python_handoff_file_pin"]) is not dict:
            _fail("producer_bundle_publication_python_handoff_pin_invalid")
        _digest(raw["journal_sha256"], "producer_bundle_publication_journal_sha256_invalid")
        if not isinstance(raw["candidates"], list) or not 1 <= len(raw["candidates"]) <= MAX_PUBLICATION_CANDIDATES:
            _fail("producer_bundle_publication_candidates_invalid")
        return cls(
            **{**raw, "candidates": tuple(ProducerBundlePublicationCandidate.from_dict(item)
                                             for item in raw["candidates"])}  # type: ignore[arg-type]
        )


def build_producer_bundle_publication_journal(**kwargs: object) -> ProducerBundlePublicationJournal:
    """Build a canonical journal without touching the filesystem or any runtime."""
    candidates = kwargs.get("candidates")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, (list, tuple)):
        _fail("producer_bundle_publication_candidates_invalid")
    normalized: list[ProducerBundlePublicationCandidate] = []
    for value in candidates:
        if not isinstance(value, ProducerBundlePublicationCandidate):
            _fail("producer_bundle_publication_candidate_invalid")
        normalized.append(value)
    values = dict(kwargs)
    values["candidates"] = tuple(normalized)
    try:
        return ProducerBundlePublicationJournal(**values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ProducerBundlePublicationError("producer_bundle_publication_schema_invalid") from exc


def parse_producer_bundle_publication_journal(
    source: Mapping[str, object] | str | os.PathLike[str],
) -> ProducerBundlePublicationJournal:
    """Parse one bounded canonical journal; parsing never performs publication or recovery."""
    try:
        if isinstance(source, Mapping):
            snapshot = dict(source)
            if "python_handoff_file_pin" in snapshot:
                # Validate before JSON can coerce callback dictionaries/scalars into
                # apparently exact pin wire types. No nested caller callback is invoked.
                supplied_pin = snapshot["python_handoff_file_pin"]
                if type(supplied_pin) is not dict:
                    _fail("producer_bundle_publication_python_handoff_pin_invalid")
                try:
                    parse_python_producer_admission_handoff_file_pin(supplied_pin)
                except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
                    raise ProducerBundlePublicationError(
                        "producer_bundle_publication_python_handoff_pin_invalid"
                    ) from exc
            raw = strict_json(_canonical(snapshot), MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
        else:
            try:
                content = _files.read_regular_file(
                    _files.absolute_path(source), MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES,
                )
            except _files.BenchmarkFileError as exc:
                if exc.reason == "too_large":
                    _fail("producer_bundle_publication_too_large")
                raise
            raw = strict_json(content, MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
        return ProducerBundlePublicationJournal.from_dict(raw)
    except ProducerBundlePublicationError:
        raise
    except Exception as exc:
        raise ProducerBundlePublicationError("producer_bundle_publication_journal_invalid") from exc


__all__ = [
    "MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES",
    "MAX_PUBLICATION_CANDIDATES",
    "ProducerBundlePublicationCandidate",
    "ProducerBundlePublicationError",
    "ProducerBundlePublicationJournal",
    "build_producer_bundle_publication_journal",
    "parse_producer_bundle_publication_journal",
]
