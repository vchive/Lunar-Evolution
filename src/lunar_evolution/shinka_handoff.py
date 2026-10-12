"""Read-only exporter for native ShinkaEvolve run directories.

Shinka stores its population and the producer's evaluation observations in SQLite, while the
candidate source is written under ``gen_<generation>/main.<extension>`` and, opportunistically,
copied to ``best/main.<extension>``.  This module is deliberately an exporter rather than a
Shinka client: it never imports or starts Shinka, invokes an evaluator, follows a scheduler, or
uses the producer's score as Lunar Evolution authority.  It snapshots a bounded set of source files into a
new directory and writes the generic ``lunar-producer-result-v1`` envelope there.  The caller can
pass that directory directly to :func:`lunar_evolution.producer_handoff.admit_producer_result`.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .evolution import MAX_SOURCE_BYTES
from .producer_handoff import (
    MAX_PRODUCER_BUDGET_FIELDS,
    MAX_PRODUCER_ENVELOPE_BYTES,
    MAX_PRODUCER_LINEAGE_ITEMS,
    MAX_PRODUCER_MATERIALS,
    PRODUCER_BUDGET_INVALID,
    PRODUCER_RESULT_PROTOCOL,
    ProducerHandoffError,
    ProducerMaterial,
    ProducerResultEnvelope,
)

SHINKA_PRODUCER_ID = "shinka"
SHINKA_RESULT_PROTOCOL = PRODUCER_RESULT_PROTOCOL

# Native/current Shinka uses programs.sqlite.  A few older launchers and notebooks call the
# database evolution_db.sqlite, so the fallback is intentionally explicit and deterministic.
SHINKA_PRIMARY_DATABASE = "programs.sqlite"
SHINKA_FALLBACK_DATABASE = "evolution_db.sqlite"
SHINKA_ENVELOPE_FILENAME = "producer-result.json"

MAX_SHINKA_TOP_K = MAX_PRODUCER_MATERIALS
MAX_SHINKA_GENERATION = 1_000_000_000
MAX_SHINKA_DATABASE_BYTES = 512 * 1024 * 1024
MAX_SHINKA_PROGRAM_ID_BYTES = 128
MAX_SHINKA_PATH_BYTES = 1_024

SHINKA_ROOT_UNSAFE = "shinka_root_unsafe"
SHINKA_DATABASE_MISSING = "shinka_database_missing"
SHINKA_DATABASE_PATH_UNSAFE = "shinka_database_path_unsafe"
SHINKA_DATABASE_NOT_REGULAR = "shinka_database_not_regular"
SHINKA_DATABASE_TOO_LARGE = "shinka_database_too_large"
SHINKA_DATABASE_WAL_UNSUPPORTED = "shinka_database_wal_unsupported"
SHINKA_DATABASE_CHANGED = "shinka_database_changed"
SHINKA_DATABASE_INVALID = "shinka_database_invalid"
SHINKA_DATABASE_SCHEMA_INVALID = "shinka_database_schema_invalid"
SHINKA_TOP_K_INVALID = "shinka_top_k_invalid"
SHINKA_NO_CORRECT_PROGRAMS = "shinka_no_correct_programs"
SHINKA_PROGRAM_INVALID = "shinka_program_invalid"
SHINKA_PROGRAM_ID_INVALID = "shinka_program_id_invalid"
SHINKA_PROGRAM_NOT_FOUND = "shinka_program_not_found"
SHINKA_PROGRAM_SELECTION_INVALID = "shinka_program_selection_invalid"
SHINKA_LANGUAGE_UNSUPPORTED = "shinka_language_unsupported"
SHINKA_GENERATION_INVALID = "shinka_generation_invalid"
SHINKA_SOURCE_PATH_UNSAFE = "shinka_source_path_unsafe"
SHINKA_SOURCE_MISSING = "shinka_source_missing"
SHINKA_SOURCE_NOT_REGULAR = "shinka_source_not_regular"
SHINKA_SOURCE_TOO_LARGE = "shinka_source_too_large"
SHINKA_SOURCE_CHANGED = "shinka_source_changed"
SHINKA_SOURCE_ENCODING_INVALID = "shinka_source_encoding_invalid"
SHINKA_SOURCE_EMPTY = "shinka_source_empty"
SHINKA_SOURCE_DIGEST_MISMATCH = "shinka_source_digest_mismatch"
SHINKA_DATABASE_CODE_ENCODING_INVALID = "shinka_database_code_encoding_invalid"
SHINKA_DATABASE_CODE_MISMATCH = "shinka_database_code_mismatch"
SHINKA_LINEAGE_INVALID = "shinka_lineage_invalid"
SHINKA_LINEAGE_MISSING = "shinka_lineage_missing"
SHINKA_LINEAGE_CYCLE = "shinka_lineage_cycle"
SHINKA_LINEAGE_TOO_DEEP = "shinka_lineage_too_deep"
SHINKA_EXPORT_ROOT_UNSAFE = "shinka_export_root_unsafe"
SHINKA_EXPORT_PATH_UNSAFE = "shinka_export_path_unsafe"
SHINKA_EXPORT_WRITE_FAILED = "shinka_export_write_failed"
SHINKA_EXPORT_CLEANUP_FAILED = "shinka_export_cleanup_failed"
SHINKA_EXPORT_COMMIT_UNKNOWN = "shinka_export_commit_unknown"
SHINKA_ENVELOPE_TOO_LARGE = "shinka_envelope_too_large"
SHINKA_FINGERPRINT_REQUIRED = "shinka_fingerprint_required"
SHINKA_CONTRACT_REQUIRED = "shinka_contract_required"
SHINKA_BUDGET_INVALID = "shinka_budget_invalid"
SHINKA_BINDING_MISMATCH = "shinka_binding_mismatch"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_LANGUAGE_EXTENSIONS = {
    "cuda": "cu",
    "cu": "cu",
    "cpp": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "cpp",
    "go": "go",
    "golang": "go",
    "python": "py",
    "python3": "py",
    "py": "py",
    "rust": "rs",
    "swift": "swift",
    "json": "json",
    "json5": "json",
    "julia": "jl",
    "jl": "jl",
    "markdown": "md",
    "md": "md",
    "fortran": "f90",
    "f90": "f90",
    "f95": "f90",
    "f03": "f90",
    "f08": "f90",
    "wolfram": "wl",
    "wl": "wl",
    "wls": "wl",
    "mathematica": "wl",
    "verilog": "sv",
    "sv": "sv",
    "sverilog": "sv",
    "systemverilog": "sv",
}


class ShinkaHandoffError(ProducerHandoffError):
    """A fixed-code failure while exporting a Shinka run."""


@dataclass(frozen=True, slots=True)
class _ProgramRow:
    program_id: str
    code: str
    language: str
    parent_id: str | None
    generation: int
    combined_score: float | int | None
    correct: bool


def _raise(code: str) -> None:
    raise ShinkaHandoffError(code)


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _raise(code)
    return value


def _utf8(value: str, code: str) -> bytes:
    if not isinstance(value, str):
        _raise(code)
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
        _raise(code)
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        _raise(code)


def _code_utf8(value: str, code: str) -> bytes:
    """Encode source text while permitting ordinary source newlines and tabs."""

    if not isinstance(value, str):
        _raise(code)
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        _raise(code)


def _safe_id(value: object, code: str = SHINKA_PROGRAM_ID_INVALID) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _raise(code)
    if len(_utf8(value, code)) > MAX_SHINKA_PROGRAM_ID_BYTES:
        _raise(code)
    return value


def _root(value: str | os.PathLike[str], code: str) -> Path:
    try:
        path = Path(value).expanduser()
        info = path.lstat()
    except (OSError, TypeError, ValueError, RuntimeError):
        _raise(code)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _raise(code)
    # Resolve parent aliases once so overlap checks cannot be bypassed by placing the export
    # directory below a symlinked results parent.  The final component was already rejected as a
    # symlink above; using the canonical path also makes descriptor-relative reads deterministic.
    return Path(os.path.realpath(path))


def _relative_path(value: object, code: str) -> str:
    try:
        raw = os.fspath(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, RuntimeError):
        _raise(code)
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        _raise(code)
    if len(_utf8(raw, code)) > MAX_SHINKA_PATH_BYTES:
        _raise(code)
    try:
        path = Path(raw)
    except (TypeError, ValueError, RuntimeError):
        _raise(code)
    if not path.parts or path.is_absolute() or raw != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        _raise(code)
    return path.as_posix()


def _open_flags(*, directory: bool = False) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    # O_NOFOLLOW prevents a final symlink; O_NONBLOCK ensures a FIFO cannot make an exporter hang
    # before fstat proves that it is not a regular file.
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    return flags


def _read_regular(
    root: Path,
    relative: str,
    *,
    limit: int,
    missing: str,
    regular: str,
    large: str,
    changed: str,
    unsafe: str,
) -> bytes:
    descriptors: list[int] = []
    try:
        root_fd = os.open(root, _open_flags(directory=True))
        descriptors.append(root_fd)
        parent_fd = root_fd
        parts = relative.split("/")
        for part in parts[:-1]:
            next_fd = os.open(part, _open_flags(directory=True), dir_fd=parent_fd)
            descriptors.append(next_fd)
            parent_fd = next_fd
        file_fd = os.open(parts[-1], _open_flags(), dir_fd=parent_fd)
        descriptors.append(file_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            _raise(regular)
        if before.st_size > limit:
            _raise(large)
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(file_fd)
        if len(content) > limit:
            _raise(large)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or after.st_size != len(content)
        ):
            _raise(changed)
        return content
    except ShinkaHandoffError:
        raise
    except FileNotFoundError:
        _raise(missing)
    except (NotADirectoryError, PermissionError):
        _raise(unsafe)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            _raise(missing)
        if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM}:
            _raise(unsafe)
        _raise(changed)
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _database_signature(path: Path) -> tuple[object, ...]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        _raise(SHINKA_DATABASE_MISSING)
    except OSError:
        _raise(SHINKA_DATABASE_PATH_UNSAFE)
    if stat.S_ISLNK(info.st_mode):
        _raise(SHINKA_DATABASE_PATH_UNSAFE)
    if not stat.S_ISREG(info.st_mode):
        _raise(SHINKA_DATABASE_NOT_REGULAR)
    if info.st_size > MAX_SHINKA_DATABASE_BYTES:
        _raise(SHINKA_DATABASE_TOO_LARGE)
    sidecars: list[tuple[object, ...]] = []
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        try:
            sidecar_info = sidecar.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _raise(SHINKA_DATABASE_PATH_UNSAFE)
        if stat.S_ISLNK(sidecar_info.st_mode) or not stat.S_ISREG(sidecar_info.st_mode):
            _raise(SHINKA_DATABASE_WAL_UNSUPPORTED)
        _raise(SHINKA_DATABASE_WAL_UNSUPPORTED)
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        tuple(sidecars),
    )


def _database_path(root: Path) -> Path:
    for name in (SHINKA_PRIMARY_DATABASE, SHINKA_FALLBACK_DATABASE):
        candidate = root / name
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _raise(SHINKA_DATABASE_PATH_UNSAFE)
        # SQLite may create -shm while merely opening a WAL database read-only. Refuse a live or
        # uncheckpointed WAL/SHM/rollback-journal snapshot instead of claiming a side-effect-free
        # exporter or silently reading a database without its latest frames.
        _database_signature(candidate)
        return candidate
    _raise(SHINKA_DATABASE_MISSING)


def _open_database(path: Path) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        uri = f"{path.as_uri()}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
    except (OSError, sqlite3.Error, ValueError):
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        _raise(SHINKA_DATABASE_INVALID)


def _check_schema(connection: sqlite3.Connection) -> None:
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "programs" not in tables:
            _raise(SHINKA_DATABASE_SCHEMA_INVALID)
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(programs)")
        }
    except ShinkaHandoffError:
        raise
    except sqlite3.Error:
        _raise(SHINKA_DATABASE_SCHEMA_INVALID)
    required = {"id", "code", "language", "parent_id", "generation", "combined_score", "correct"}
    if not required.issubset(columns):
        _raise(SHINKA_DATABASE_SCHEMA_INVALID)
    try:
        duplicate = connection.execute(
            "SELECT id FROM programs GROUP BY id HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        _raise(SHINKA_DATABASE_SCHEMA_INVALID)
    if duplicate is not None:
        # A parent lookup with LIMIT 1 would otherwise make lineage depend on SQLite row order.
        _raise(SHINKA_PROGRAM_INVALID)


def _language_extension(value: object) -> str:
    if not isinstance(value, str):
        _raise(SHINKA_LANGUAGE_UNSUPPORTED)
    normalized = value.strip().lower()
    extension = _LANGUAGE_EXTENSIONS.get(normalized)
    if extension is None:
        _raise(SHINKA_LANGUAGE_UNSUPPORTED)
    return extension


def _generation(value: object) -> int:
    if type(value) is not int or value < 0 or value > MAX_SHINKA_GENERATION:
        _raise(SHINKA_GENERATION_INVALID)
    return value


def _score(value: object) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _raise(SHINKA_PROGRAM_INVALID)
    try:
        if not math.isfinite(float(value)):
            _raise(SHINKA_PROGRAM_INVALID)
    except (OverflowError, ValueError):
        _raise(SHINKA_PROGRAM_INVALID)
    return value


def _row_from_sql(row: sqlite3.Row) -> _ProgramRow:
    program_id = _safe_id(row["id"])
    code = row["code"]
    if not isinstance(code, str):
        _raise(SHINKA_PROGRAM_INVALID)
    code_bytes = _code_utf8(code, SHINKA_DATABASE_CODE_ENCODING_INVALID)
    if not code_bytes or not code.strip():
        _raise(SHINKA_SOURCE_EMPTY)
    if len(code_bytes) > MAX_SOURCE_BYTES:
        _raise(SHINKA_SOURCE_TOO_LARGE)
    language = row["language"]
    _language_extension(language)
    parent_id = row["parent_id"]
    if parent_id is not None:
        _safe_id(parent_id, SHINKA_LINEAGE_INVALID)
    generation = _generation(row["generation"])
    combined_score = _score(row["combined_score"])
    correct = row["correct"]
    if isinstance(correct, bool):
        correct_value = correct
    elif type(correct) is int and correct in {0, 1}:
        correct_value = bool(correct)
    else:
        _raise(SHINKA_PROGRAM_INVALID)
    return _ProgramRow(
        program_id=program_id,
        code=code,
        language=str(language),
        parent_id=parent_id,
        generation=generation,
        combined_score=combined_score,
        correct=correct_value,
    )


def _select_rows(
    connection: sqlite3.Connection,
    top_k: int | None,
    program_ids: Sequence[str] | None = None,
) -> list[_ProgramRow]:
    if program_ids is not None:
        if isinstance(program_ids, (str, bytes)) or not isinstance(program_ids, Sequence):
            _raise(SHINKA_PROGRAM_SELECTION_INVALID)
        try:
            requested_list: list[object] = []
            for index, program_id in enumerate(program_ids):
                if index >= MAX_SHINKA_TOP_K:
                    _raise(SHINKA_PROGRAM_SELECTION_INVALID)
                requested_list.append(program_id)
        except ShinkaHandoffError:
            raise
        except Exception:  # noqa: BLE001 - an untrusted sequence must fail closed
            _raise(SHINKA_PROGRAM_SELECTION_INVALID)
        requested = tuple(requested_list)
        if not requested:
            _raise(SHINKA_PROGRAM_SELECTION_INVALID)
        # An explicit ordered ID list is already the complete selection.  Requiring ``None``
        # avoids an ambiguous API where a default top-k value silently coexists with the list.
        if top_k is not None:
            _raise(SHINKA_PROGRAM_SELECTION_INVALID)
        for program_id in requested:
            _safe_id(program_id, SHINKA_PROGRAM_SELECTION_INVALID)
        if len(set(requested)) != len(requested):
            _raise(SHINKA_PROGRAM_SELECTION_INVALID)
        placeholders = ",".join("?" for _ in requested)
        try:
            rows = connection.execute(
                f"""
                SELECT id, code, language, parent_id, generation, combined_score, correct
                FROM programs
                WHERE id IN ({placeholders})
                """,
                requested,
            ).fetchall()
        except sqlite3.Error:
            _raise(SHINKA_DATABASE_INVALID)
        by_id: dict[str, _ProgramRow] = {}
        for raw in rows:
            parsed = _row_from_sql(raw)
            if parsed.program_id in by_id:
                _raise(SHINKA_PROGRAM_INVALID)
            by_id[parsed.program_id] = parsed
        if any(program_id not in by_id for program_id in requested):
            _raise(SHINKA_PROGRAM_NOT_FOUND)
        # Preserve the caller's order.  The external database score is not used to choose an
        # explicitly requested material, and a row marked incorrect is still sent to Lunar Evolution's
        # exact evaluator for the authoritative decision.
        return [by_id[program_id] for program_id in requested]
    effective_top_k = 1 if top_k is None else top_k
    if type(effective_top_k) is not int or not 1 <= effective_top_k <= MAX_SHINKA_TOP_K:
        _raise(SHINKA_TOP_K_INVALID)
    try:
        rows = connection.execute(
            """
            SELECT id, code, language, parent_id, generation, combined_score, correct
            FROM programs
            WHERE correct = 1
            ORDER BY
                CASE WHEN typeof(combined_score) IN ('integer', 'real')
                     AND combined_score IS NOT NULL THEN 0 ELSE 1 END ASC,
                combined_score DESC,
                generation DESC,
                id ASC
            LIMIT ?
            """,
            (effective_top_k,),
        ).fetchall()
    except sqlite3.Error:
        _raise(SHINKA_DATABASE_INVALID)
    if not rows:
        _raise(SHINKA_NO_CORRECT_PROGRAMS)
    selected = [_row_from_sql(row) for row in rows]
    if any(not row.correct for row in selected):
        _raise(SHINKA_PROGRAM_INVALID)
    if len({row.program_id for row in selected}) != len(selected):
        _raise(SHINKA_PROGRAM_INVALID)
    return selected


def _lineage(connection: sqlite3.Connection, row: _ProgramRow) -> tuple[str, ...]:
    current = row.parent_id
    seen = {row.program_id}
    newest_first: list[str] = []
    while current is not None:
        parent_id = _safe_id(current, SHINKA_LINEAGE_INVALID)
        if parent_id in seen:
            _raise(SHINKA_LINEAGE_CYCLE)
        if len(newest_first) >= MAX_PRODUCER_LINEAGE_ITEMS:
            _raise(SHINKA_LINEAGE_TOO_DEEP)
        seen.add(parent_id)
        try:
            parent = connection.execute(
                "SELECT id, parent_id FROM programs WHERE id = ? LIMIT 1",
                (parent_id,),
            ).fetchone()
        except sqlite3.Error:
            _raise(SHINKA_DATABASE_INVALID)
        if parent is None:
            _raise(SHINKA_LINEAGE_MISSING)
        actual_id = _safe_id(parent["id"], SHINKA_LINEAGE_INVALID)
        if actual_id != parent_id:
            _raise(SHINKA_LINEAGE_INVALID)
        newest_first.append(parent_id)
        current = parent["parent_id"]
    newest_first.reverse()
    return tuple(newest_first)


def _candidate_source(root: Path, row: _ProgramRow) -> tuple[str, bytes]:
    extension = _language_extension(row.language)
    generation_path = f"gen_{row.generation}/main.{extension}"
    try:
        source = _read_regular(
            root,
            generation_path,
            limit=MAX_SOURCE_BYTES,
            missing=SHINKA_SOURCE_MISSING,
            regular=SHINKA_SOURCE_NOT_REGULAR,
            large=SHINKA_SOURCE_TOO_LARGE,
            changed=SHINKA_SOURCE_CHANGED,
            unsafe=SHINKA_SOURCE_PATH_UNSAFE,
        )
        origin = generation_path
    except ShinkaHandoffError as exc:
        if exc.code != SHINKA_SOURCE_MISSING:
            raise
        # `best/` is a convenience snapshot and may be stale.  It is used only when the
        # generation path is absent, and the DB code hash below must still match it.
        best_path = f"best/main.{extension}"
        source = _read_regular(
            root,
            best_path,
            limit=MAX_SOURCE_BYTES,
            missing=SHINKA_SOURCE_MISSING,
            regular=SHINKA_SOURCE_NOT_REGULAR,
            large=SHINKA_SOURCE_TOO_LARGE,
            changed=SHINKA_SOURCE_CHANGED,
            unsafe=SHINKA_SOURCE_PATH_UNSAFE,
        )
        origin = best_path
    try:
        source_text = source.decode("utf-8")
    except UnicodeDecodeError:
        _raise(SHINKA_SOURCE_ENCODING_INVALID)
    if not source_text.strip():
        _raise(SHINKA_SOURCE_EMPTY)
    try:
        expected = row.code.encode("utf-8")
    except UnicodeEncodeError:
        _raise(SHINKA_DATABASE_CODE_ENCODING_INVALID)
    if source != expected:
        _raise(SHINKA_DATABASE_CODE_MISMATCH)
    if hashlib.sha256(source).hexdigest() != hashlib.sha256(expected).hexdigest():
        _raise(SHINKA_SOURCE_DIGEST_MISMATCH)
    return origin, source


def _path_overlap(first: Path, second: Path) -> bool:
    first_abs = os.path.realpath(first)
    second_abs = os.path.realpath(second)
    try:
        return os.path.commonpath((first_abs, second_abs)) in {first_abs, second_abs}
    except ValueError:
        return False


def _prepare_export_root(source_root: Path, value: str | os.PathLike[str]) -> tuple[Path, Path]:
    try:
        raw = Path(value).expanduser()
    except (TypeError, ValueError, RuntimeError):
        _raise(SHINKA_EXPORT_ROOT_UNSAFE)
    if not raw.parts or any(part in {"", ".", ".."} for part in raw.parts):
        _raise(SHINKA_EXPORT_ROOT_UNSAFE)
    # Keep the destination lexical and reject every existing symlink component.  Resolving an
    # ancestor before the check would allow ``alias/out`` to publish into an unrelated tree and
    # would also make failure leave caller-owned parent directories behind.
    try:
        export_root = raw if raw.is_absolute() else Path.cwd() / raw
        export_root = Path(os.path.abspath(export_root))
        # macOS exposes the OS-owned temporary roots through stable `/var` and `/tmp` aliases.
        # Accept only those two known aliases after converting them to their canonical private
        # locations; arbitrary user symlink components remain rejected below.
        if sys.platform == "darwin":
            system_aliases = (
                (Path("/var"), Path("/private/var")),
                (Path("/tmp"), Path("/private/tmp")),
            )
            for alias, target in system_aliases:
                if export_root == alias or alias in export_root.parents:
                    export_root = target / export_root.relative_to(alias)
                    break
        parent = export_root.parent
        chain: list[Path] = []
        current = parent
        while True:
            chain.append(current)
            if current == current.parent:
                break
            current = current.parent
        for component in reversed(chain):
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                _raise(SHINKA_EXPORT_ROOT_UNSAFE)
    except ShinkaHandoffError:
        raise
    except (FileNotFoundError, OSError, ValueError):
        _raise(SHINKA_EXPORT_ROOT_UNSAFE)
    if _path_overlap(source_root, export_root):
        _raise(SHINKA_EXPORT_ROOT_UNSAFE)
    try:
        if export_root.exists() or export_root.is_symlink():
            # The whole result tree is committed with a directory rename.  Requiring a new leaf
            # avoids replacing even an empty caller-created directory and makes the ownership
            # contract explicit; callers can remove an abandoned export and retry deliberately.
            _raise(SHINKA_EXPORT_ROOT_UNSAFE)
    except ShinkaHandoffError:
        raise
    except (OSError, ValueError):
        _raise(SHINKA_EXPORT_ROOT_UNSAFE)
    return export_root, parent


def _remove_staging(path: Path) -> bool:
    """Remove one exporter-owned staging path without following a replacement symlink."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        return True
    except (OSError, RuntimeError):
        return False
    try:
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            shutil.rmtree(path)
        else:
            # A staging directory must never be a symlink, but unlinking a raced replacement is
            # safer than passing it to rmtree and accidentally following an outside tree.
            path.unlink()
    except Exception:  # noqa: BLE001 - cleanup status is converted to a fixed code below
        return False
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except (OSError, RuntimeError):
        return False
    return False


def _cleanup_staging_or_raise(path: Path) -> None:
    if not _remove_staging(path):
        _raise(SHINKA_EXPORT_CLEANUP_FAILED)


def _make_staging_root(destination_root: Path, destination_parent: Path) -> Path:
    """Create a private sibling directory for one complete export transaction."""

    staging: Path | None = None
    try:
        # ``mkdtemp`` has no ``mode`` keyword on supported Python versions.  Set and verify the
        # mode after creation so an unusual umask or a replaced path cannot widen the private
        # staging boundary.
        staging = Path(
            tempfile.mkdtemp(prefix=f".{destination_root.name}.", dir=destination_parent)
        )
        os.chmod(staging, 0o700)
        info = staging.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            _raise(SHINKA_EXPORT_WRITE_FAILED)
        if stat.S_IMODE(info.st_mode) != 0o700:
            _raise(SHINKA_EXPORT_WRITE_FAILED)
        return staging
    except ShinkaHandoffError:
        if staging is not None:
            _cleanup_staging_or_raise(staging)
        raise
    except (OSError, TypeError, ValueError, RuntimeError):
        if staging is not None:
            _cleanup_staging_or_raise(staging)
        _raise(SHINKA_EXPORT_WRITE_FAILED)


def _fsync_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        _raise(SHINKA_EXPORT_WRITE_FAILED)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _fsync_tree(root: Path) -> None:
    """Persist files and directory entries in a private staging tree bottom-up."""

    try:
        for directory, subdirectories, filenames in os.walk(root, topdown=False, followlinks=False):
            for filename in filenames:
                file_path = Path(directory) / filename
                info = file_path.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    _raise(SHINKA_EXPORT_PATH_UNSAFE)
            for child in subdirectories:
                child_path = Path(directory) / child
                info = child_path.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    _raise(SHINKA_EXPORT_PATH_UNSAFE)
                _fsync_directory(child_path)
            _fsync_directory(Path(directory))
    except ShinkaHandoffError:
        raise
    except OSError:
        _raise(SHINKA_EXPORT_WRITE_FAILED)


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Publish a directory without replacing a target created by a concurrent caller."""

    # Both supported desktop platforms expose a no-replace directory rename primitive, but
    # Python does not currently wrap either one.  Use the native call when available; the final
    # fallback retains the preflight check for platforms without that primitive.
    at_fdcwd = getattr(os, "AT_FDCWD", -2)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            rename = libc.renameatx_np
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            rename.restype = ctypes.c_int
            result = rename(
                at_fdcwd,
                os.fsencode(source),
                at_fdcwd,
                os.fsencode(destination),
                0x00000004,  # RENAME_EXCL
            )
        elif sys.platform != "darwin" and hasattr(libc, "renameat2"):
            rename = libc.renameat2
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            rename.restype = ctypes.c_int
            result = rename(
                at_fdcwd,
                os.fsencode(source),
                at_fdcwd,
                os.fsencode(destination),
                0x00000001,  # RENAME_NOREPLACE
            )
        else:
            result = None
    except (AttributeError, OSError, TypeError, ValueError):
        result = None
    if result is not None:
        if result != 0:
            error_number = ctypes.get_errno() or errno.EIO
            raise OSError(error_number, os.strerror(error_number), str(destination))
        return
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(destination))
    os.replace(source, destination)


def _ensure_directory(root: Path, relative: str) -> Path:
    current = root
    for part in relative.split("/"):
        current = current / part
        try:
            if current.exists() or current.is_symlink():
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    _raise(SHINKA_EXPORT_PATH_UNSAFE)
            else:
                current.mkdir(mode=0o700)
        except ShinkaHandoffError:
            raise
        except OSError:
            _raise(SHINKA_EXPORT_WRITE_FAILED)
    return current


def _write_export_file(root: Path, relative: str, content: bytes) -> None:
    parent = _ensure_directory(root, str(Path(relative).parent))
    destination = root / relative
    try:
        if destination.exists() or destination.is_symlink():
            # Never overwrite a caller-owned artifact.  A fresh export root makes the result
            # reviewable and keeps a retry from silently changing an earlier envelope.
            _raise(SHINKA_EXPORT_PATH_UNSAFE)
        fd, temporary_name = tempfile.mkstemp(prefix=".shinka-export-", dir=parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except ShinkaHandoffError:
        raise
    except OSError:
        _raise(SHINKA_EXPORT_WRITE_FAILED)


def _canonical_envelope_bytes(envelope: ProducerResultEnvelope) -> bytes:
    try:
        encoded = json.dumps(
            envelope.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _raise(SHINKA_EXPORT_WRITE_FAILED)
    if len(encoded) > MAX_PRODUCER_ENVELOPE_BYTES:
        _raise(SHINKA_ENVELOPE_TOO_LARGE)
    return encoded


def _bounded_budget(value: object) -> dict[str, int | float]:
    """Detach a caller mapping with a hard iteration bound before envelope validation."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        _raise(SHINKA_BUDGET_INVALID)
    result: dict[str, int | float] = {}
    try:
        iterator = iter(value)
        for _ in range(MAX_PRODUCER_BUDGET_FIELDS + 1):
            try:
                key = next(iterator)
            except StopIteration:
                break
            if not isinstance(key, str) or key in result:
                _raise(SHINKA_BUDGET_INVALID)
            result[key] = value[key]  # type: ignore[index]
        else:
            _raise(SHINKA_BUDGET_INVALID)
    except ShinkaHandoffError:
        raise
    except Exception:  # noqa: BLE001 - arbitrary adapter mappings are untrusted
        _raise(SHINKA_BUDGET_INVALID)
    return result


def export_shinka_result(
    results_root: str | os.PathLike[str],
    export_root: str | os.PathLike[str],
    *,
    contract_sha256: str | Any,
    producer_fingerprint: str,
    top_k: int | None = None,
    producer_id: str = SHINKA_PRODUCER_ID,
    producer_run_id: str | None = None,
    budget: Mapping[str, int | float] | None = None,
    program_ids: Sequence[str] | None = None,
    envelope_path: str | os.PathLike[str] = SHINKA_ENVELOPE_FILENAME,
    binding: object | None = None,
) -> ProducerResultEnvelope:
    """Export selected Shinka programs into a generic envelope.

    The source root and SQLite database are opened read-only.  Every selected row must have a
    matching UTF-8 source file and a complete, bounded parent chain.  The returned envelope is
    also written below ``export_root``; its material paths refer only to copied files in that
    directory.  When ``program_ids`` is supplied, those IDs and their order are authoritative for
    selection; rows marked incorrect by Shinka are still exported so Lunar Evolution's exact evaluator can
    make the authoritative decision.  Without explicit IDs, ``top_k`` selects the native rows
    marked ``correct = 1`` by descending producer score as a convenience snapshot.  In both
    modes, producer score/correctness is represented solely as digest-only evidence by
    :class:`ProducerMaterial`; Lunar Evolution must re-evaluate each copied source locally.
    """

    if binding is not None:
        # Keep the import local: this exporter is also used by the generic producer
        # CLI, while the Python binding is an optional provider-free composition gate.
        try:
            from .python_producer_adapter import verify_python_producer_result_binding

            verify_binding = verify_python_producer_result_binding
        except (ImportError, AttributeError):
            _raise(SHINKA_BINDING_MISMATCH)
    else:
        verify_binding = None
    if top_k is not None and (type(top_k) is not int or not 1 <= top_k <= MAX_SHINKA_TOP_K):
        _raise(SHINKA_TOP_K_INVALID)
    contract_value: object = contract_sha256
    try:
        digest_method = getattr(contract_sha256, "digest", None)
    except Exception:  # noqa: BLE001 - opaque contract objects are untrusted here
        _raise(SHINKA_CONTRACT_REQUIRED)
    if not isinstance(contract_sha256, str) and callable(digest_method):
        try:
            contract_value = digest_method()
        except Exception:  # noqa: BLE001 - opaque contract objects are untrusted here
            _raise(SHINKA_CONTRACT_REQUIRED)
    contract_digest = _digest(contract_value, SHINKA_CONTRACT_REQUIRED)
    producer_digest = _digest(producer_fingerprint, SHINKA_FINGERPRINT_REQUIRED)
    source_root = _root(results_root, SHINKA_ROOT_UNSAFE)
    relative_envelope = _relative_path(envelope_path, SHINKA_EXPORT_PATH_UNSAFE)

    database = _database_path(source_root)
    database_before = _database_signature(database)
    connection = _open_database(database)
    try:
        _check_schema(connection)
        rows = _select_rows(connection, top_k, program_ids)
        prepared: list[tuple[_ProgramRow, tuple[str, ...], bytes, str]] = []
        for row in rows:
            lineage = _lineage(connection, row)
            origin, source = _candidate_source(source_root, row)
            prepared.append((row, lineage, source, origin))
    finally:
        try:
            connection.close()
        except sqlite3.Error:
            pass
    if _database_signature(database) != database_before:
        _raise(SHINKA_DATABASE_CHANGED)

    # Only validate the destination after all source/database checks have passed.  This keeps a
    # rejected or incomplete Shinka run from leaving a misleading empty export directory.
    material_paths = {
        f"candidates/{index:03d}-{row.program_id}/main.{_language_extension(row.language)}"
        for index, (row, _lineage, _source, _origin) in enumerate(prepared)
    }
    if relative_envelope in material_paths:
        _raise(SHINKA_EXPORT_PATH_UNSAFE)
    materials: list[ProducerMaterial] = []
    try:
        for index, (row, lineage, source, _origin) in enumerate(prepared):
            extension = _language_extension(row.language)
            material_path = f"candidates/{index:03d}-{row.program_id}/main.{extension}"
            _relative_path(material_path, SHINKA_EXPORT_PATH_UNSAFE)
            source_digest = hashlib.sha256(source).hexdigest()
            evidence: dict[str, Any] = {
                "correct": row.correct,
                "generation": row.generation,
                "program_id": row.program_id,
            }
            if row.combined_score is not None:
                evidence["combined_score"] = row.combined_score
            materials.append(
                ProducerMaterial(
                    kind="candidate_source",
                    path=material_path,
                    size=len(source),
                    sha256=source_digest,
                    lineage=lineage,
                    external_evidence=evidence,
                )
            )

        envelope_budget: dict[str, int | float]
        if budget is None:
            envelope_budget = {"top_k": len(materials)}
        else:
            envelope_budget = _bounded_budget(budget)
        try:
            envelope = ProducerResultEnvelope(
                schema_version="1",
                producer_id=producer_id,
                producer_fingerprint=producer_digest,
                producer_run_id=producer_run_id,
                status="completed",
                contract_sha256=contract_digest,
                budget=envelope_budget,
                materials=tuple(materials),
            )
        except ProducerHandoffError as exc:
            if exc.code == PRODUCER_BUDGET_INVALID:
                _raise(SHINKA_BUDGET_INVALID)
            _raise(exc.code)
        if verify_binding is not None:
            try:
                verify_binding(binding, envelope)
            except Exception as exc:
                if isinstance(exc, ShinkaHandoffError):
                    raise
                _raise(SHINKA_BINDING_MISMATCH)
        envelope_bytes = _canonical_envelope_bytes(envelope)

        destination_root, destination_parent = _prepare_export_root(source_root, export_root)
        staging_root = _make_staging_root(destination_root, destination_parent)
        committed = False
        try:
            for index, (_row, _lineage_ids, source, _origin) in enumerate(prepared):
                material_path = materials[index].path
                _write_export_file(staging_root, material_path, source)
            _write_export_file(staging_root, relative_envelope, envelope_bytes)
            _fsync_tree(staging_root)
            # Recheck the target immediately before the directory-level commit.  Any target that
            # appeared after the initial check is a conflict; the exporter never replaces a
            # caller-owned file, symlink, or directory.
            if destination_root.exists() or destination_root.is_symlink():
                _raise(SHINKA_EXPORT_ROOT_UNSAFE)
            try:
                _rename_noreplace(staging_root, destination_root)
            except FileExistsError:
                _raise(SHINKA_EXPORT_ROOT_UNSAFE)
            committed = True
            try:
                _fsync_directory(destination_parent)
            except ShinkaHandoffError:
                # The rename made the complete tree visible.  Do not report an ordinary write
                # failure and then delete/pretend to roll back that published result; durability
                # of the parent directory is now unknown and the caller must inspect the tree.
                _raise(SHINKA_EXPORT_COMMIT_UNKNOWN)
        except ShinkaHandoffError:
            if not committed:
                _cleanup_staging_or_raise(staging_root)
            raise
        except Exception:
            if not committed:
                _cleanup_staging_or_raise(staging_root)
            raise
        return envelope
    except ShinkaHandoffError:
        raise
    except ProducerHandoffError as exc:
        _raise(exc.code)
    except (OSError, ValueError, TypeError):
        _raise(SHINKA_EXPORT_WRITE_FAILED)


# A descriptive alias keeps callers that think in terms of an envelope readable while the
# canonical API remains ``export_shinka_result``.
export_shinka_envelope = export_shinka_result


__all__ = [
    "MAX_SHINKA_DATABASE_BYTES",
    "MAX_SHINKA_GENERATION",
    "MAX_SHINKA_PATH_BYTES",
    "MAX_SHINKA_TOP_K",
    "SHINKA_BINDING_MISMATCH",
    "SHINKA_BUDGET_INVALID",
    "SHINKA_CONTRACT_REQUIRED",
    "SHINKA_DATABASE_CHANGED",
    "SHINKA_DATABASE_CODE_ENCODING_INVALID",
    "SHINKA_DATABASE_CODE_MISMATCH",
    "SHINKA_DATABASE_INVALID",
    "SHINKA_DATABASE_MISSING",
    "SHINKA_DATABASE_NOT_REGULAR",
    "SHINKA_DATABASE_PATH_UNSAFE",
    "SHINKA_DATABASE_SCHEMA_INVALID",
    "SHINKA_DATABASE_TOO_LARGE",
    "SHINKA_DATABASE_WAL_UNSUPPORTED",
    "SHINKA_ENVELOPE_FILENAME",
    "SHINKA_ENVELOPE_TOO_LARGE",
    "SHINKA_EXPORT_CLEANUP_FAILED",
    "SHINKA_EXPORT_COMMIT_UNKNOWN",
    "SHINKA_EXPORT_PATH_UNSAFE",
    "SHINKA_EXPORT_ROOT_UNSAFE",
    "SHINKA_EXPORT_WRITE_FAILED",
    "SHINKA_FALLBACK_DATABASE",
    "SHINKA_FINGERPRINT_REQUIRED",
    "SHINKA_GENERATION_INVALID",
    "SHINKA_LANGUAGE_UNSUPPORTED",
    "SHINKA_LINEAGE_CYCLE",
    "SHINKA_LINEAGE_INVALID",
    "SHINKA_LINEAGE_MISSING",
    "SHINKA_LINEAGE_TOO_DEEP",
    "SHINKA_NO_CORRECT_PROGRAMS",
    "SHINKA_PRIMARY_DATABASE",
    "SHINKA_PRODUCER_ID",
    "SHINKA_PROGRAM_ID_INVALID",
    "SHINKA_PROGRAM_INVALID",
    "SHINKA_PROGRAM_NOT_FOUND",
    "SHINKA_PROGRAM_SELECTION_INVALID",
    "SHINKA_RESULT_PROTOCOL",
    "SHINKA_ROOT_UNSAFE",
    "SHINKA_SOURCE_CHANGED",
    "SHINKA_SOURCE_DIGEST_MISMATCH",
    "SHINKA_SOURCE_EMPTY",
    "SHINKA_SOURCE_ENCODING_INVALID",
    "SHINKA_SOURCE_MISSING",
    "SHINKA_SOURCE_NOT_REGULAR",
    "SHINKA_SOURCE_PATH_UNSAFE",
    "SHINKA_SOURCE_TOO_LARGE",
    "SHINKA_TOP_K_INVALID",
    "ShinkaHandoffError",
    "export_shinka_envelope",
    "export_shinka_result",
]
