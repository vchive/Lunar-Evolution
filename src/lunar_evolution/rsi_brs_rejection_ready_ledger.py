"""Bounded raw SQLite comparison data for a future original-owner ready gate.

This private helper grants no owner or ACK authority and performs no semantic record
validation. Its caller must independently freeze the full episode domain, validate
the original records in the same snapshot or between equal captures, and retain the
original database inode separately. A same-path replacement is not detected here.
"""

from __future__ import annotations

import re
import sqlite3
from typing import NoReturn
from urllib.parse import quote

from .producer_bundle_lineage import MAX_LINEAGE_SNAPSHOT_BYTES
from .rsi_learning import RSILearningError

_MAX_ROWS = 4096
_MAX_IDS = 4096
# Deliberately narrower than the store's 128 KiB payload cap: include row metadata.
_MAX_ROW_BYTES = 128 * 1024
_MAX_BYTES = MAX_LINEAGE_SNAPSHOT_BYTES
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

# name, explicit columns, scope, stable order, integer columns, nullable columns
_TABLES = (
    ("rsi_records", ("logical_id,revision,kind,state,request_sha256,parent_record_sha256,"
     "payload,record_sha256,created_at"), "records", "logical_id COLLATE BINARY,revision",
     (1,), (5,)),
    ("rsi_controller_journal", "run_id,revision,parent_sha256,payload,checkpoint_sha256",
     "run", "revision", (1,), (2,)),
    ("rsi_python_admissions", ("run_id,episode_id,journal_id,attempt_id,payload,record_sha256,"
     "created_at"), "run", "episode_id COLLATE BINARY,journal_id COLLATE BINARY", (), ()),
    ("rsi_native_episode_claims", "episode_id,request_sha256,plan_sha256,claim_sha256,created_at",
     "episodes", "episode_id COLLATE BINARY", (), ()),
    ("rsi_episode_results", ("episode_id,request_sha256,request_payload,result_payload,"
     "result_sha256,created_at"), "episodes", "episode_id COLLATE BINARY", (), ()),
    ("rsi_episode_reconciliations", ("episode_id,revision,parent_record_sha256,worker_state,"
     "evidence,result_sha256,journal_sha256,created_at"), "episodes",
     "episode_id COLLATE BINARY,revision", (1,), (5,)),
)
_SCHEMA_SPEC = ("sqlite_schema", "type,name,tbl_name,rootpage,sql", "schema", "name", (3,), ())

_Value = str | int | None
_Row = tuple[_Value, ...]
_Groups = tuple[tuple[str, tuple[_Row, ...]], ...]
_Snapshot = tuple[str, str, tuple[str, ...], tuple[_Row, ...], _Groups]


def _fail(reason: str) -> NoReturn:
    raise RSILearningError("rsi_brs_rejection_ready_ledger_" + reason)


def _path(value: object) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 4096
            or not value.startswith("/") or "\x00" in value):
        _fail("path_invalid")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _fail("path_invalid")
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail("domain_invalid")
    return value


def _domain(run_id: object, episode_ids: object) -> tuple[str, ...]:
    _identifier(run_id)
    if type(episode_ids) is not tuple or not 1 <= len(episode_ids) <= _MAX_IDS:
        _fail("domain_invalid")
    for episode_id in episode_ids:
        _identifier(episode_id)
    if len(set(episode_ids)) != len(episode_ids) or run_id in episode_ids:
        _fail("domain_invalid")
    return tuple(sorted(episode_ids))


def _row_size(row: object, specification: tuple) -> int:
    _, columns, _, _, integers, nullable = specification
    if type(row) is not tuple or len(row) != len(columns.split(",")):
        _fail("row_invalid")
    total = 16
    for index, value in enumerate(row):
        if value is None and index in nullable:
            size = 1
        elif index in integers:
            if type(value) is not int or not -(2**63) <= value < 2**63:
                _fail("row_invalid")
            size = 8
        elif type(value) is str:
            if len(value) > _MAX_ROW_BYTES:
                _fail("capacity_exceeded")
            try:
                size = len(value.encode("utf-8"))
            except UnicodeError:
                _fail("row_invalid")
        else:
            _fail("row_invalid")
        total += 8 + size
        if total > _MAX_ROW_BYTES:
            _fail("capacity_exceeded")
    return total


def _schema_size(rows: object) -> int:
    if type(rows) is not tuple or len(rows) != len(_TABLES):
        _fail("schema_changed")
    size = 16
    names = sorted(specification[0] for specification in _TABLES)
    for row, name in zip(rows, names, strict=True):
        size += _row_size(row, _SCHEMA_SPEC)
        if row[:3] != ("table", name, name) or row[3] <= 0:
            _fail("schema_changed")
    return size


def _snapshot_shape(snapshot: object) -> _Snapshot:
    if type(snapshot) is not tuple or len(snapshot) != 5:
        _fail("snapshot_invalid")
    path, run_id, episodes, schema, groups = snapshot
    _path(path)
    if _domain(run_id, episodes) != episodes:
        _fail("snapshot_invalid")
    if type(groups) is not tuple or len(groups) != len(_TABLES):
        _fail("snapshot_invalid")
    count = len(schema) if type(schema) is tuple else 0
    size = _schema_size(schema) + len(path.encode("utf-8")) + len(run_id) + sum(map(len, episodes))
    for group, specification in zip(groups, _TABLES, strict=True):
        if (type(group) is not tuple or len(group) != 2 or type(group[0]) is not str
                or group[0] != specification[0] or type(group[1]) is not tuple):
            _fail("snapshot_invalid")
        size += len(group[0]) + 16
        for row in group[1]:
            size += _row_size(row, specification)
            count += 1
            if count > _MAX_ROWS or size > _MAX_BYTES:
                _fail("capacity_exceeded")
            if group[0] == "rsi_python_admissions" and row[1] not in episodes:
                _fail("domain_invalid")
    return snapshot


def _read(path: str, run_id: str, episodes: tuple[str, ...],
          held: _Snapshot | None) -> tuple[tuple[_Row, ...], _Groups]:
    connection = None
    try:
        connection = sqlite3.connect("file:" + quote(path, safe="/") + "?mode=ro",
                                     uri=True, timeout=30.0, isolation_level=None)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_ROW_BYTES)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        names = tuple(specification[0] for specification in _TABLES)
        schema = tuple(connection.execute(
            "SELECT type,name,tbl_name,rootpage,sql FROM sqlite_schema WHERE name IN "
            f"({','.join('?' for _ in names)}) ORDER BY name COLLATE BINARY LIMIT ?",
            (*names, len(names) + 1),
        ))
        size = _schema_size(schema) + len(path.encode("utf-8")) + len(run_id) + sum(map(len, episodes))
        if held is not None and schema != held[3]:
            _fail("schema_changed")
        groups = []
        count = len(schema)
        for index, specification in enumerate(_TABLES):
            name, columns, scope, order, _, _ = specification
            if scope == "records":
                key, values = "logical_id", (run_id, *episodes)
            elif scope == "run":
                key, values = "run_id", (run_id,)
            else:
                key, values = "episode_id", episodes
            expected = None if held is None else held[4][index][1]
            limit = _MAX_ROWS - count + 1 if expected is None else len(expected) + 1
            cursor = connection.execute(
                f"SELECT {columns} FROM {name} WHERE {key} IN "
                f"({','.join('?' for _ in values)}) ORDER BY {order} LIMIT ?", (*values, limit),
            )
            rows = []
            size += len(name) + 16
            for row in cursor:
                size += _row_size(row, specification)
                count += 1
                if count > _MAX_ROWS or size > _MAX_BYTES:
                    _fail("capacity_exceeded")
                if name == "rsi_python_admissions" and row[1] not in episodes:
                    _fail("domain_invalid")
                if expected is not None and (len(rows) >= len(expected) or row != expected[len(rows)]):
                    _fail("rows_changed")
                rows.append(row)
            if expected is not None and len(rows) != len(expected):
                _fail("rows_changed")
            groups.append((name, tuple(rows)))
        return schema, tuple(groups)
    except sqlite3.DataError as exc:
        raise RSILearningError("rsi_brs_rejection_ready_ledger_capacity_exceeded") from exc
    except (sqlite3.Error, UnicodeError) as exc:
        raise RSILearningError("rsi_brs_rejection_ready_ledger_read_failed") from exc
    finally:
        if connection is not None:
            connection.close()


def read_rejection_ready_rows(database_path: str, *, run_id: str,
                              episode_ids: tuple[str, ...]) -> _Snapshot:
    """Capture comparison data only; caller independently validates semantics/inode.

    The episode tuple is the caller's complete frozen wave/held-reference closure,
    including absent domains. No current row may add an episode to that closure.
    Counts are narrower helper limits, not changes to ledger or publication caps.
    """
    path = _path(database_path)
    episodes = _domain(run_id, episode_ids)
    schema, groups = _read(path, run_id, episodes, None)
    return path, run_id, episodes, schema, groups


def assert_rejection_ready_rows(database_path: str, snapshot: tuple) -> None:
    """Compare original rows in one new read-only transaction; never refresh baseline."""
    path = _path(database_path)
    held_path, run_id, episodes, _, _ = _snapshot_shape(snapshot)
    if path != held_path:
        _fail("path_changed")
    _read(path, run_id, episodes, snapshot)


__all__ = ["assert_rejection_ready_rows", "read_rejection_ready_rows"]
