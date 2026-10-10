"""Immutable prepared journals recorded before native producer draft execution.

This file is separate from the adjudicated ``journal.json`` written by staging.  Retrying a
native transaction may reuse retained evidence only when its complete prepared request matches.
This module neither runs candidates nor changes the existing generic staging protocol.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .candidate_evaluation_spec import strict_json
from .producer_bundle_publication import (
    MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES,
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .producer_bundle_staging import (
    _batch,
    _check_held_publication_lock,
    _locked,
    _present,
    _pretty,
    _read,
    _regular,
    _workspace,
)
from .python_producer_admission_handoff import parse_python_producer_admission_handoff_file_pin

_INTENT_NAME = "journal.prepared.json"
_STARTED_NAMES = (
    "native-drafts", "stage", "journal.json", "journal.staged.json", "preflight.json",
    "manifest.json", "terminal.json", "journal.published.json", "rejections", "rejections.json",
)


class ProducerBundlePreparedIntentError(ValueError):
    """Fixed-code failure at the prepared-intent boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBundlePreparedIntentError(code)


def _intent_content(journal: ProducerBundlePublicationJournal) -> tuple[bytes, str]:
    if not isinstance(journal, ProducerBundlePublicationJournal):
        _fail("producer_bundle_prepared_intent_journal_invalid")
    try:
        validate_producer_bundle_python_handoff_pin(journal)
        normalized = parse_producer_bundle_publication_journal(journal.to_dict())
        if normalized.state != "prepared" or normalized.publication_phase != "preflight":
            _fail("producer_bundle_prepared_intent_journal_state_invalid")
        return (
            _pretty(normalized.to_dict(), MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES),
            normalized.digest(),
        )
    except ProducerBundlePreparedIntentError:
        raise
    except Exception as exc:
        raise ProducerBundlePreparedIntentError(
            "producer_bundle_prepared_intent_journal_invalid"
        ) from exc


def _locations(workspace: str | Path, journal_id: str) -> tuple[Path, Path]:
    try:
        root = _workspace(workspace)
        return root, _batch(root, journal_id)
    except Exception as exc:
        raise ProducerBundlePreparedIntentError(
            "producer_bundle_prepared_intent_path_invalid"
        ) from exc


def _verify_existing(path: Path, expected: bytes) -> None:
    try:
        _regular(path)
        content = _read(path, MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
        _regular(path)
    except Exception as exc:
        raise ProducerBundlePreparedIntentError(
            "producer_bundle_prepared_intent_path_invalid"
        ) from exc
    # Exact canonical bytes also check the full journal digest, strict schema, phase, and every
    # request pin. Equivalent JSON with changed formatting is not an immutable intent replay.
    if content != expected:
        _fail("producer_bundle_prepared_intent_mismatch")


def _started(batch: Path) -> bool:
    return any(_present(batch / name) for name in _STARTED_NAMES)


def _write_exclusive(chain: DirectoryChain, content: bytes) -> None:
    """Write through the held no-follow batch directory; retain failed writes for recovery."""
    _check_held_publication_lock()
    descriptor = os.open(
        _INTENT_NAME,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=chain.fd,
    )
    try:
        opened = os.fstat(descriptor)
        view = memoryview(content)
        while view:
            _check_held_publication_lock()
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("intent write made no progress")
            view = view[count:]
        os.fsync(descriptor)
        named = os.stat(_INTENT_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(named.st_mode)
            or named.st_nlink != 1
            or named.st_size != len(content)
            or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            _fail("producer_bundle_prepared_intent_path_invalid")
        chain.check()
        os.fsync(chain.fd)
    finally:
        os.close(descriptor)


def persist_producer_bundle_prepared_intent(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
    *, checkpoint: Callable[[str], object] | None = None,
) -> str:
    """Durably create the prepared full journal, or require a byte-identical retry.

    The caller must finish read-only transaction preflight first and create the system-derived
    batch directory. The returned value is the prepared journal digest. An existing started
    batch without its prepared intent is never adopted by this API.
    """
    content, digest = _intent_content(journal)
    root, batch = _locations(workspace, journal.journal_id)
    chain = None
    try:
        chain = DirectoryChain(batch, "producer_bundle_prepared_intent_path_invalid")
        with _locked(root, checkpoint=checkpoint):
            chain.check()
            if checkpoint is not None:
                checkpoint("producer_prepared_intent_locked")
            path = batch / _INTENT_NAME
            if _present(path):
                _verify_existing(path, content)
            else:
                if _started(batch) or _present(root / "evolution" / "producer-publication.json"):
                    _fail("producer_bundle_prepared_intent_recovery_required")
                _write_exclusive(chain, content)
                _verify_existing(path, content)
            chain.check()
    except (ProducerBundlePreparedIntentError, SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except Exception as exc:
        from .producer_bundle_transaction import NativeProducerBundleTransactionError

        if type(exc) is NativeProducerBundleTransactionError and exc.code in {
            "producer_bundle_transaction_python_handoff_invalid",
            "producer_bundle_transaction_python_handoff_mismatch",
            "producer_bundle_transaction_python_handoff_execution_link_missing",
        }:
            # A caller checkpoint already supplied the primary fixed handoff refusal.
            # Do not relabel evidence drift as an intent write failure.
            raise
        raise ProducerBundlePreparedIntentError(
            "producer_bundle_prepared_intent_write_failed"
        ) from exc
    finally:
        if chain is not None:
            chain.close()
    return digest


def verify_producer_bundle_prepared_intent(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
) -> str:
    """Read-only exact comparison with the immutable prepared journal on disk."""
    content, digest = _intent_content(journal)
    _root, batch = _locations(workspace, journal.journal_id)
    path = batch / _INTENT_NAME
    if not _present(path):
        if _started(batch):
            _fail("producer_bundle_prepared_intent_recovery_required")
        _fail("producer_bundle_prepared_intent_missing")
    _verify_existing(path, content)
    return digest


def validate_producer_bundle_python_handoff_pin(
    journal: ProducerBundlePublicationJournal,
) -> None:
    """Validate protected Python proof before any workspace I/O.

    Legacy digest-only journals stay parseable for inspection, but cannot enter a
    publication, settlement or recovery path without the original retained file pin.
    """
    try:
        if type(journal) is not ProducerBundlePublicationJournal:
            _fail("producer_bundle_prepared_intent_python_handoff_pin_invalid")
        if journal.python_handoff_file_pin is not None:
            parse_python_producer_admission_handoff_file_pin(journal.python_handoff_file_pin)
        if journal.python_handoff_sha256 is None and journal.python_handoff_file_pin is None:
            return
        normalized = parse_producer_bundle_publication_journal(journal.to_dict())
        if normalized != journal:
            _fail("producer_bundle_prepared_intent_python_handoff_pin_invalid")
        if normalized.python_handoff_sha256 is not None and normalized.python_handoff_file_pin is None:
            _fail("producer_bundle_prepared_intent_python_handoff_pin_missing")
    except ProducerBundlePreparedIntentError:
        raise
    except Exception as exc:
        raise ProducerBundlePreparedIntentError(
            "producer_bundle_prepared_intent_python_handoff_pin_invalid"
        ) from exc


def verify_producer_bundle_python_handoff_anchor(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
) -> None:
    """Require the unchanged original Python pin in the immutable prepared intent.

    Later journal states legitimately add receipts and terminal summaries. Their
    prepared projection must still equal the original create-only anchor in full.
    This function never creates or repairs an absent anchor.
    """
    validate_producer_bundle_python_handoff_pin(journal)
    if journal.python_handoff_sha256 is None:
        _root, batch = _locations(workspace, journal.journal_id)
        path = batch / _INTENT_NAME
        if _present(path):
            try:
                original = parse_producer_bundle_publication_journal(
                    strict_json(_read(path, MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES),
                                MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES),
                )
            except Exception as exc:
                raise ProducerBundlePreparedIntentError(
                    "producer_bundle_prepared_intent_python_handoff_anchor_invalid"
                ) from exc
            if original.python_handoff_sha256 is not None or original.python_handoff_file_pin is not None:
                _fail("producer_bundle_prepared_intent_python_handoff_anchor_mismatch")
        return
    prepared = replace(
        journal, state="prepared", publication_phase="preflight", journal_sha256=None,
        terminal_marker_sha256=None, archive_after_sha256=None, state_after_sha256=None,
        candidates=tuple(replace(
            item, status="planned", execution_receipt_sha256=None,
            evaluation_receipt_sha256=None, publication_receipt_sha256=None,
        ) for item in journal.candidates),
    )
    verify_producer_bundle_prepared_intent(workspace, prepared)


__all__ = [
    "ProducerBundlePreparedIntentError",
    "persist_producer_bundle_prepared_intent",
    "validate_producer_bundle_python_handoff_pin",
    "verify_producer_bundle_prepared_intent",
    "verify_producer_bundle_python_handoff_anchor",
]
