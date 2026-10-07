# Linux native target descriptor handoff

Feature178 adds an explicit descriptor handoff to the native Linux child. The host already starts
the bootstrap with close_fds and a pass_fds list. The child now also removes unexpected inherited
handles, including the bootstrap's own sealed executable descriptor, before producer execution.
Feature178 introduced native-bootstrap-linux-fd-handoff-v1. Feature179 supersedes the new-build/
formal default with native-bootstrap-linux-fd-control-v1 while retaining this handoff. Old descriptors
remain available for exact read-only load/recovery at their original scope.

The child keeps host-controlled stdin/stdout/stderr, the internal CLOEXEC exec-error writer, the
explicit executable handle when one was supplied, and an optional validated broker pair. A bounded
sorted keep list defines close_range segments through UINT_MAX; a lowered RLIMIT_NOFILE cannot hide
a previously opened high descriptor. Missing/failed closing refuses target start. The error writer
closes during successful exec. The executable handle preserves existing inherited semantics so a
sealed shebang interpreter can reopen its exact script bytes.

Broker declarations require both strict decimal FD numbers, distinct non-reserved handles and
correct endpoint directions. FIFO type and Linux PIPEFS_MAGIC distinguish anonymous pipes from
named FIFOs and sockets. The two directions must belong to different pipe objects. This proves
endpoint kind and direction; the existing trusted host creates and passes the fresh pipe pair.
These checks do not independently authenticate an arbitrary external process or remote worker.

Reserved aliases are refused before child handoff closes or duplicates live protocol descriptors;
the parent retains original control/gate numbers for checks before allocating new handles. Each new pre-exec
failure writes an explicit error to the existing parent pipe; a refusal must never be mistaken for
successful exec merely because the parent observed EOF. Original guardian, deadline, child-drain,
control/frame, cleanup, receipt, broker journal and publication contracts are unchanged.

This is a limited inherited-descriptor boundary. Standard streams remain host-controlled, and an
explicit target handle is deliberately allowed. Grant path/inode binding, read/write tree overlap,
regular-file ioctls, complete egress, immutable Python imports and independent supervision after
bootstrap death/pause remain separate work. Darwin is not upgraded to the Linux capability.
Local Darwin skips do not prove Linux execution. Tests use inert local C/bootstrap/pipe/filesystem
fixtures; no real producer campaign or model/evaluator is launched.
