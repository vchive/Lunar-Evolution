# Feature 178 — Linux native target descriptor handoff

Status: implementation in progress; final-head Linux validation pending.
Priority: P0, a bounded inherited-descriptor prerequisite after Feature176.

The host runner already uses close_fds and explicit pass_fds, but the native child does not
independently close every unexpected inherited descriptor. The sealed bootstrap descriptor can
also remain inherited by the target. Environment-selected broker FD numbers are not yet validated
against reserved protocol descriptors or their actual pipe direction before target exec.

New Linux builds use native-bootstrap-linux-fd-handoff-v1. Formal attempts require this version
before budget, input preflight, nonce consumption or spawn. Historical load/recovery stays
read-only at its original descriptor scope. The original child-supervision, control/frame,
guardian, deadline, receipt, cleanup, broker journal and publication protocols are unchanged.

After the original gate and before isolation/exec, the Linux child keeps only host standard
streams, the internal close-on-exec error writer, the bound executable handle when required and
an optional explicitly validated broker pair. Close all other descriptors using a finite number
of close_range segments extending through UINT_MAX; do not rely on current RLIMIT_NOFILE or a
finite guessed maximum. Unsupported/failed closing refuses target start instead of falling back
to a partial scan. The error writer must disappear at exec; the explicitly allowed executable FD retains its existing
non-CLOEXEC behavior so a sealed shebang script can reopen the same bytes. No extra bootstrap/control/gate/frame/
owner FD reaches target code. Broker endpoints require a complete pair, strict FD numbers,
distinct non-reserved handles and correct actual read/write pipe types/directions. Any stronger
anonymous-pipe claim must have an explicit Linux proof, beyond S_IFIFO alone.

Refuse aliases before the child handoff closes or duplicates live reserved descriptors.
Retain original control/gate FD numbers in the parent alias check before allocating new handles. Refusals have no target marker
and cannot be converted into success evidence. Native command construction rejects duplicate
protocol FDs. Preserve Darwin execution behavior; it gains no Linux close_range claim.

This does not close pathname/grant overlap or inode identity, regular-file ioctls, inherited
standard-stream authority, dynamic loader/runtime sealing, all network egress, bootstrap death/
pause supervision or external production adapters. The standard streams remain host-controlled;
no blanket complete FD or containment claim is made. No new execute/evaluate/publication rights.

Only inert local C/bootstrap/filesystem/pipe/socket/loopback fixtures and existing GitHub CI.
No model, remote/company evaluator, WebAgent, upstream campaign, .env or credentials.
