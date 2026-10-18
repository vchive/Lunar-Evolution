"""Whole reserved-domain ledger observations, including claim-before-fence gaps.

This reader does not classify an intent as untouched. Filesystem/native material
and terminal ownership must be observed independently. It captures all six RSI
tables in one bounded, query-only SQLite snapshot and retains that exact snapshot
for a later comparison. No claim, cursor, permission or recovery write is created.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import PosixPath, WindowsPath

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_brs_reconcile import FIELD, parse_brs_reconcile_obligations
from .rsi_brs_rejection_ready_ledger import (
    _TABLES,
    _domain,
    _readonly_uri,
    _row_size,
    _schema_size,
    _snapshot_shape,
)
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import RSILearningError
from .rsi_native_scheduler import _read_ledger_identity
from .rsi_store import RSILedger

_MAX_BYTES = 128 * 1024
_MAX_CHILDREN = 8
_MAX_RAW_ROWS = 4096
_MAX_RAW_BYTES = 16 * 1024 * 1024


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_reserved_ledger_" + reason)


def _json(value: object) -> dict:
    if type(value) is not str:
        _fail("payload_invalid")
    try:
        parsed = strict_json(value, maximum=_MAX_BYTES)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_ledger_payload_invalid") from exc
    if type(parsed) is not dict:
        _fail("payload_invalid")
    return parsed


def _sha(value: object) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        _fail("digest_invalid")
    return value


def _rows(snapshot: tuple) -> dict[str, tuple[dict, ...]]:
    return {name: tuple(dict(zip(specification[1].split(","), row, strict=True)) for row in values)
            for (name, values), specification in zip(snapshot[4], _TABLES, strict=True)}


def _read_reserved_rows(path: str, *, run_id: str, episode_ids: tuple[str, ...]) -> tuple:
    """One raw snapshot, including admissions that misname an original child.

    The older ready-gate reader intentionally scopes admissions to its run. Here
    either the original run or an original child makes a row relevant. Conflicting
    run/child associations refuse; they cannot disappear from a freshness scan.
    """
    episodes = _domain(run_id, episode_ids)
    connection = None
    try:
        connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30, isolation_level=None)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_BYTES)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        names = tuple(item[0] for item in _TABLES)
        schema = tuple(connection.execute(
            "SELECT type,name,tbl_name,rootpage,sql FROM sqlite_schema WHERE name IN "
            f"({','.join('?' for _ in names)}) ORDER BY name COLLATE BINARY LIMIT ?",
            (*names, len(names) + 1),
        ))
        size = _schema_size(schema) + len(path.encode("utf-8")) + len(run_id) + sum(map(len, episodes))
        count, groups = len(schema), []
        for specification in _TABLES:
            name, columns, scope, order, _, _ = specification
            if name == "rsi_python_admissions":
                predicate = f"run_id = ? OR episode_id IN ({','.join('?' for _ in episodes)})"
                values = (run_id, *episodes)
            else:
                key, values = (("logical_id", (run_id, *episodes)) if scope == "records" else
                               ("run_id", (run_id,)) if scope == "run" else ("episode_id", episodes))
                predicate = f"{key} IN ({','.join('?' for _ in values)})"
            cursor = connection.execute(
                f"SELECT {columns} FROM {name} WHERE {predicate} ORDER BY {order} LIMIT ?",
                (*values, _MAX_RAW_ROWS - count + 1),
            )
            rows = []
            size += len(name) + 16
            for row in cursor:
                size += _row_size(row, specification)
                count += 1
                if count > _MAX_RAW_ROWS or size > _MAX_RAW_BYTES:
                    _fail("capacity_exceeded")
                if name == "rsi_python_admissions" and (row[0] != run_id or row[1] not in episodes):
                    _fail("admission_domain_drift")
                rows.append(row)
            groups.append((name, tuple(rows)))
        return _snapshot_shape((path, run_id, episodes, schema, tuple(groups)))
    except sqlite3.DataError as exc:
        raise RSILearningError("rsi_brs_reserved_ledger_capacity_exceeded") from exc
    except (sqlite3.Error, UnicodeError) as exc:
        raise RSILearningError("rsi_brs_reserved_ledger_read_failed") from exc
    finally:
        if connection is not None:
            connection.close()


@dataclass(frozen=True, slots=True)
class BRSReservedLedgerObservation:
    """Immutable comparison facts; absence here proves no filesystem absence."""

    run_id: str
    episode_ids: tuple[str, ...]
    checkpoint_sha256: str
    checkpoint_bytes: bytes
    ledger_identity_bytes: bytes
    raw_snapshot: tuple
    trace_bytes: tuple[tuple[str, bytes], ...]

    def ledger_traces(self) -> dict[str, dict]:
        return {episode_id: strict_json(raw, maximum=_MAX_BYTES)
                for episode_id, raw in self.trace_bytes}


def read_reserved_brs_ledger(
    ledger: RSILedger, *, run_id: str, episode_ids: tuple[str, ...],
    expected_checkpoint_sha256: str,
) -> BRSReservedLedgerObservation:
    """Observe the whole domain while retaining the original controller lease."""
    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    RSILedger._assert_controller_lock(ledger, run_id)
    result = _observe_reserved_brs_ledger(ledger, run_id=run_id, episode_ids=episode_ids,
        expected_checkpoint_sha256=expected_checkpoint_sha256)
    RSILedger._assert_controller_lock(ledger, run_id)
    return result


def read_reserved_brs_completion_ledger(
    ledger: RSILedger, *, run_id: str, episode_ids: tuple[str, ...],
    expected_checkpoint_sha256: str,
) -> BRSReservedLedgerObservation:
    """Read-only worker evidence; this never grants selection, ownership or a lease.

    Its complete original snapshot and independent readback are identical to the
    leased observer. Only an original controller can use the separate leased
    entry before selection or append. A worker cannot acquire that authority by
    supplying or receiving this descriptive observation.
    """
    return _observe_reserved_brs_ledger(ledger, run_id=run_id, episode_ids=episode_ids,
        expected_checkpoint_sha256=expected_checkpoint_sha256)


def _observe_reserved_brs_ledger(
    ledger: RSILedger, *, run_id: str, episode_ids: tuple[str, ...],
    expected_checkpoint_sha256: str,
) -> BRSReservedLedgerObservation:
    """Observe the entire original domain with a query-only coherent snapshot.

    Unlike terminal composition this operation requires no current obligation.
    A native claim alone, an orphan admission/reconciliation row, or a historical
    fence is returned as an attempt trace. Callers must combine these facts with
    independently retained material and prefix observations before selection.
    """
    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    if type(ledger.database) not in {PosixPath, WindowsPath}:
        _fail("ledger_path_invalid")
    if (type(run_id) is not str or not run_id or len(run_id) > 128
            or type(episode_ids) is not tuple or not 1 <= len(episode_ids) <= _MAX_CHILDREN
            or any(type(item) is not str for item in episode_ids)
            or len(set(episode_ids)) != len(episode_ids)):
        _fail("domain_invalid")
    _sha(expected_checkpoint_sha256)
    identity = canonical_json(_read_ledger_identity(ledger))
    snapshot = _read_reserved_rows(str(ledger.database), run_id=run_id, episode_ids=episode_ids)
    groups = _rows(snapshot)
    parent = None
    states, historical = [], {key: [] for key in episode_ids}
    for ordinal, row in enumerate(groups["rsi_controller_journal"]):
        state = _json(row["payload"])
        expected = RSILedger._checkpoint_digest(run_id, ordinal, parent, state)
        if (row["revision"] != ordinal or row["parent_sha256"] != parent
                or row["checkpoint_sha256"] != expected):
            _fail("checkpoint_corrupt")
        parent = expected
        states.append(state)
        obligations = parse_brs_reconcile_obligations(state.get(FIELD))
        if any(key not in historical for key in obligations):
            _fail("domain_invalid")
        for key, obligation in obligations.items():
            if obligation.run_id != run_id or obligation.episode_id != key:
                _fail("obligation_drift")
            digest = obligation.digest()
            if digest not in historical[key]:
                historical[key].append(digest)
    if not states or parent != expected_checkpoint_sha256:
        _fail("checkpoint_conflict")
    state = states[-1]
    plan, intents = state.get("plan"), state.get("intents")
    if (state.get("run_id") != run_id or state.get("mode") != "brs"
            or type(plan) is not dict or plan.get("mode") != "brs"
            or type(plan.get("wave")) is not int or type(plan.get("practices")) is not list
            or len(plan["practices"]) != len(episode_ids)
            or episode_ids != tuple(f"{run_id}-practice-{plan['wave']}-{index}"
                                    for index in range(len(episode_ids)))
            or type(intents) is not dict or set(intents) != set(episode_ids)):
        _fail("domain_invalid")
    requests = {}
    for key, intent in intents.items():
        if type(intent) is not dict or type(intent.get("request")) is not dict:
            _fail("request_invalid")
        request = SolverRequest.from_dict(intent["request"])
        if request.episode_id != key:
            _fail("request_invalid")
        requests[key] = request
    records = {key: [] for key in (run_id, *episode_ids)}
    for row in groups["rsi_records"]:
        record = RSILedger._row_to_record(row)
        previous = records[record.logical_id]
        if (record.revision != len(previous)
                or record.parent_record_sha256 != (previous[-1].record_sha256 if previous else None)
                or record.kind != ("run" if record.logical_id == run_id else "episode")):
            _fail("record_history_drift")
        if record.logical_id != run_id and (
            record.request_sha256 != requests[record.logical_id].digest()
            or record.payload.get("run_id") != run_id
        ):
            _fail("episode_drift")
        previous.append(record)
    if not records[run_id]:
        _fail("run_missing")
    results, claims = {}, {}
    for row in groups["rsi_episode_results"]:
        key = row["episode_id"]
        request = SolverRequest.from_dict(_json(row["request_payload"]))
        result = SolverResult.from_dict(_json(row["result_payload"]))
        if (request != requests[key] or row["request_sha256"] != request.digest()
                or result.episode_id != key or result.request_sha256 != request.digest()
                or hashlib.sha256(canonical_json(result.to_dict(), maximum=_MAX_BYTES)).hexdigest()
                != row["result_sha256"]):
            _fail("result_drift")
        results[key] = result
    for row in groups["rsi_native_episode_claims"]:
        key = row["episode_id"]
        claim = RSILedger._native_claim_row(row, status=results[key].status if key in results else "started")
        if claim.request_sha256 != requests[key].digest():
            _fail("claim_drift")
        claims[key] = claim
    if set(results) - set(claims):
        _fail("unclaimed_result")
    traces = []
    current_obligations = parse_brs_reconcile_obligations(state.get(FIELD))
    for key in episode_ids:
        trace = {
            "episode": records[key][-1].payload if records[key] else None,
            "claim": claims[key].to_dict() if key in claims else None,
            "result": results[key].to_dict() if key in results else None,
            "admission_rows": [row for row in groups["rsi_python_admissions"] if row["episode_id"] == key],
            "reconciliation_rows": [row for row in groups["rsi_episode_reconciliations"] if row["episode_id"] == key],
            "historical_obligation_sha256s": historical[key],
            "obligation_sha256": current_obligations[key].digest() if key in current_obligations else None,
        }
        traces.append((key, canonical_json(trace, maximum=_MAX_BYTES)))
    # The capture is already one transaction. Recheck the original named inode,
    # lease and same raw state after semantic parsing; never adopt a newer head.
    if _read_reserved_rows(str(ledger.database), run_id=run_id, episode_ids=episode_ids) != snapshot:
        _fail("rows_changed")
    if canonical_json(_read_ledger_identity(ledger)) != identity:
        _fail("ledger_identity_drift")
    return BRSReservedLedgerObservation(
        run_id, episode_ids, parent, canonical_json(state, maximum=_MAX_BYTES),
        identity, snapshot, tuple(traces),
    )


def assert_reserved_brs_ledger(ledger: RSILedger, observation: BRSReservedLedgerObservation) -> None:
    """Compare an original observation without refreshing its captured baseline."""
    if type(observation) is not BRSReservedLedgerObservation:
        _fail("observation_invalid")
    if (type(observation.checkpoint_bytes) is not bytes or len(observation.checkpoint_bytes) > _MAX_BYTES
            or type(observation.ledger_identity_bytes) is not bytes
            or len(observation.ledger_identity_bytes) > _MAX_BYTES
            or type(observation.trace_bytes) is not tuple
            or len(observation.trace_bytes) > _MAX_CHILDREN):
        _fail("observation_invalid")
    for item in observation.trace_bytes:
        if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not str
                or type(item[1]) is not bytes or len(item[1]) > _MAX_BYTES):
            _fail("observation_invalid")
    _snapshot_shape(observation.raw_snapshot)
    current = read_reserved_brs_ledger(
        ledger, run_id=observation.run_id, episode_ids=observation.episode_ids,
        expected_checkpoint_sha256=observation.checkpoint_sha256,
    )
    if current != observation:
        _fail("observation_drift")
