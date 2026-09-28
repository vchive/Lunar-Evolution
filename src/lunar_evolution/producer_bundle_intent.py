"""Immutable prepared journals recorded before native producer draft execution.

This file is separate from the adjudicated ``journal.json`` written by staging.  Retrying a
native transaction may reuse retained evidence only when its complete prepared request matches.
This module neither runs candidates nor changes the existing generic staging protocol.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .producer_bundle_publication import (
    MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES,
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .producer_bundle_staging import (
    _batch,
    _locked,
    _present,
    _pretty,
    _read,
    _regular,
    _workspace,
)

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


__all__ = [
    "ProducerBundlePreparedIntentError",
    "persist_producer_bundle_prepared_intent",
    "verify_producer_bundle_prepared_intent",
]
