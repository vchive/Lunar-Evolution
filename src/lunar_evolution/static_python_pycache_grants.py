"""Opt-in inotify diagnostics bound to a live original held-grant context.

This authenticates the diagnostic's root relationship to the original held
objects. It does not account for inherited writable handles, restrict the
native writer, observe original writer quiescence, or accept cache absence.
The native attempt does not select this diagnostic automatically.
"""

from __future__ import annotations

from dataclasses import replace

from .producer_grant_anchors import HeldProducerGrantPlan, ProducerGrantError
from .static_python_pycache_monitor import (
    FINITE_WRITE_VIEW_PROFILE,
    FinitePycacheMonitor,
    PycacheMonitorDiagnostic,
    parse_reviewed_write_view,
)

ORIGINAL_GRANT_DIAGNOSTIC_PROFILE = "original-grant-bound-pycache-diagnostic-v1"
_ORIGINAL_READER_RELEASE = FinitePycacheMonitor._release


class PycacheGrantBindingError(ValueError):
    """A fixed refusal of the live original-grant relationship."""


def _fail(reason: str) -> None:
    raise PycacheGrantBindingError("static_python_pycache_grants_" + reason)


def _held_snapshot(owner: HeldProducerGrantPlan) -> tuple:
    """Read actual held FDs and their entire currently validated manifest."""
    if type(owner) is not HeldProducerGrantPlan:
        _fail("original_owner_required")
    try:
        owner.validate()
        manifest = owner.manifest
        manifest.validate()
        anchors = owner.anchors
        # No returned anchor or manifest can recreate the context-owned plan.
        # Retain all roles and descriptors, including non-writable grants, so
        # a later change cannot silently redefine the original grant set.
        result = (manifest.manifest_sha256, tuple(
            (anchor.record.path, anchor.record.roles, anchor.record.identity.device,
             anchor.record.identity.inode, anchor.record.identity.kind, anchor.fd)
            for anchor in anchors
        ))
        owner.validate()
        return result
    except ProducerGrantError as exc:
        raise PycacheGrantBindingError(
            "static_python_pycache_grants_original_owner_unavailable",
        ) from exc


def _write_roots(snapshot: tuple) -> dict[str, tuple[int, int]]:
    return {path: (device, inode) for path, roles, device, inode, _kind, _fd in snapshot[1]
            if "writable-directory" in roles}


def _release_capture(capture: FinitePycacheMonitor, primary: BaseException) -> None:
    try:
        capture.finish()
    except BaseException:  # noqa: BLE001 - cleanup cannot replace the original refusal
        primary.add_note("static_python_pycache_grants_reader_cleanup_unknown")
        try:
            # A finish callable can fail before releasing the acquired reader,
            # including before any wrapper instance has been initialized.
            _ORIGINAL_READER_RELEASE(capture)
        except BaseException:  # noqa: BLE001 - retain the first refusal even if resource retirement fails
            primary.add_note("static_python_pycache_grants_original_reader_cleanup_unknown")


class GrantBoundPycacheMonitor:
    """Live-context diagnostic; no detached input supplies an original owner.

    Arm, drain and finish inside the same ``hold_producer_grants`` context.
    Its original roots must all occur in the finite reviewed view. Every
    operation revalidates that context before and after reading diagnostics.
    Finish still records ``original_quiescence_unavailable`` and stops only
    the inotify reader; callers remain responsible for their native writers.
    """

    __slots__ = ("_capture", "_failed", "_original", "_original_capture", "_original_owner", "_owner")

    def __init__(self) -> None:
        _fail("use_arm_before_target")

    def __copy__(self):
        _fail("original_owner_required")

    def __deepcopy__(self, _memo):
        _fail("original_owner_required")

    def __reduce__(self):
        _fail("original_owner_required")

    @classmethod
    def arm_before_target(
        cls, *, held_grants: HeldProducerGrantPlan, reviewed_grants_bytes: bytes,
        expected_grants_sha256: str, deadline_monotonic_ns: int,
        diagnostic_profile: str | None = None,
    ) -> GrantBoundPycacheMonitor:
        """Bind the original grant set before any target may execute.

        This entry point acquires actual directory watches. A matching digest
        or a parsed manifest without its still-live held owner is insufficient.
        Unknown inherited handles/enclosure/quiescence stay unproven.
        """
        if (type(diagnostic_profile) is not str
                or diagnostic_profile != ORIGINAL_GRANT_DIAGNOSTIC_PROFILE):
            _fail("profile_disabled")
        if cls is not GrantBoundPycacheMonitor:
            _fail("original_owner_required")
        original = _held_snapshot(held_grants)
        view = parse_reviewed_write_view(
            reviewed_grants_bytes, expected_sha256=expected_grants_sha256,
            original_grants_sha256=original[0],
        )
        roots = _write_roots(original)
        if not roots or set(roots) != {root.path for root in view.roots}:
            _fail("writable_root_set_changed")
        capture = FinitePycacheMonitor.arm_before_target(
            reviewed_grants_bytes=reviewed_grants_bytes,
            expected_grants_sha256=expected_grants_sha256,
            original_grants_sha256=original[0], deadline_monotonic_ns=deadline_monotonic_ns,
            diagnostic_profile=FINITE_WRITE_VIEW_PROFILE,
        )
        try:
            instance = object.__new__(cls)
            instance._owner, instance._original_owner, instance._original = held_grants, held_grants, original
            instance._capture, instance._original_capture, instance._failed = capture, capture, False
            instance._check_original()
            return instance
        except BaseException as exc:
            # Allocation/slot initialization can fail before an instance owns
            # any fields. The already-started original reader still needs
            # cleanup directly, without dereferencing that partial instance.
            _release_capture(capture, exc)
            raise

    def _check_original(self) -> None:
        if self._failed:
            _fail("capture_refused")
        if self._owner is not self._original_owner:
            _fail("original_owner_changed")
        if (type(self._capture) is not FinitePycacheMonitor
                or self._capture is not self._original_capture):
            _fail("original_capture_changed")
        if _held_snapshot(self._owner) != self._original:
            _fail("original_owner_changed")
        roots = _write_roots(self._original)
        observed = self._capture.snapshot()
        actual = {item.path: (item.device, item.inode) for item in observed.directories
                  if item.relative_path == "."}
        if (observed.original_grants_sha256 != self._original[0] or actual != roots
                or len(actual) != sum(item.relative_path == "." for item in observed.directories)):
            _fail("original_root_identity_changed")

    def _release_after_refusal(self, primary: BaseException) -> None:
        self._failed = True
        _release_capture(self._original_capture, primary)

    def _observe(self, operation: str) -> PycacheMonitorDiagnostic:
        try:
            self._check_original()
            observed = getattr(self._capture, operation)()
            self._check_original()
            # Descriptive only. Serialization/copy does not retain this live
            # acquisition, and the remaining authority fields stay false.
            return replace(
                observed, original_grants_authenticated=True, writer_enclosure_verified=False,
                original_quiescence_observed=False, coverage_complete=False,
                strict_view_accepted=False, production_admission=False,
            )
        except BaseException as exc:
            self._release_after_refusal(exc)
            raise

    def drain(self) -> PycacheMonitorDiagnostic:
        """Drain original kernel events while all original grant FDs stay live."""
        return self._observe("drain")

    def snapshot(self) -> PycacheMonitorDiagnostic:
        """Export diagnostics without transferring the original acquisition."""
        return self._observe("snapshot")

    def finish(self) -> PycacheMonitorDiagnostic:
        """Stop monitoring, preserving missing enclosure and quiescence."""
        return self._observe("finish")
