# Frozen topology and plan

The independently retained /tmp/lunar183-independent-guardian-plan.md section11 and
/tmp/lunar183-design-freeze-evidence.json freeze a smaller topology after rejecting
unannounced CLONE_PARENT child cleanup. The controller directly creates a second
original Popen child as a native watcher in a separate private session. It owns/reaps
both exact children from creation. The watcher never enters the bootstrap __WALL
wait set; bootstrap identity/group/subreaper/public frames remain unchanged.

The watcher inherits a fresh original bootstrap pidfd while that Popen child is live.
Linux PIDFD_SIGNAL_PROCESS_GROUP=4 applies the signal to its original struct pid/PGID,
including leader-dead/already-reaped but member-live groups; an empty original group
returns ESRCH instead of looking up a reused numeric PGID. Primary kernel sources
support this from mainline6.9. Actual signal0+flag4 startup probe is required: uname
or header presence is insufficient. Unsupported kernels refuse before ready/release,
with no flags0/numeric-PGID/CLONE_PARENT/ordinary-fork weaker fallback.

## Private interface

Latest bootstrap originalv2 argv appends `--guardian-finish-fd WR` and
`--guardian-ack-fd RD` (argc19). They are anonymous PIPEFS direction/flags/type-checked,
static/dynamic reserved, absent from target keep sets, and kept until guarded finish.
Older argc15/v2 and Darwin retain their original contract. New version gates are
separate and cannot be relabeled by old loading.

The same sealed native artifact has a trusted watcher-only role:
`--group-pidfd FD --controller-lifeline-fd RD --guardian-finish-fd RD
--guardian-ack-fd WR --deadline-monotonic-ns NS` (argc11). All fields strictly parsed,
pipes disjoint/non-ASYNC/PIPEFS, original live pidfd tested with signal0+flag4. Watcher
closes every other inherited FD including stdio/exec handle/grant/broker/source FDs.
The trusted watcher is not target-isolated; target retains existing pidfd/IPC denies.

Startup: watcher verifies original owner/deadline/bootstrap liveness and runtime group
flag support, then bounded-writes exact one-byte R to ack pipe. Host bounded-reads R
before any control write/readiness/release and closes its ack RD copy. Bootstrap does
not read ack before complete target drain. Controller closes every host copy of finish
WR/ack WR after spawning their sole native owners, avoiding suppressed EOF.

Normal finish: bootstrap retains original pthread checks and exact __WALL/ECHILD drain,
writes the existing terminal frame, writes exact F to finish pipe and closes its sole
writer. Watcher waits for F+EOF while polling original lifeline/bootstrap pidfd/deadline,
then rechecks owner/deadline/bootstrap alive, bounded-writes exact D, closes ack and
exits0. Bootstrap bounded-reads D+EOF under original checks, finishes original pthread
and exits with preserved direct target status. Host reaps its exact watcher Popen and
requires actual exit0 in addition to all existing normal terminal/cleanup evidence.
Malformed/truncated/extra F, premature EOF, death, owner data/EOF/error or deadline
trigger original pidfd group SIGKILL and watcher failure/unknown. No blocking read/
write may stop deadline monitoring; all R/D/F/EOF waits use poll original deadlines.
The host R wait uses poll as well, including for FD>=1024. It bounds and rounds
only the poll timeout, rechecks the same absolute deadline before and after read,
and rejects error/hangup/foreign or multiple events before consuming any byte.

Exceptional cleanup: controller closes original lifeline writer and keeps watcher
running until its group stop/exact exit/reap is observed, subject to bounded cleanup.
The original pidfd group-stop operation is attempted before watcher retirement.
If that operation fails, bounded exact watcher reap still runs but the attempt
remains unknown; failed group signaling never becomes clean termination. Startup failure before watcher
ownership is covered by existing original bootstrap/thread and host-owned process
cleanup. Failure to reap/normal-exit watcher refuses clean outcome; no persisted PID
signaling/relaunch/nonce/deadline refresh. Host module never wait(-1)s or signals a
saved PGID. Watcher group kill uses only the original pidfd, never its own/new group.

## Author ownership and validation

C author: native_bootstrap.c plus new tests/test_native_independent_guardian.py only.
Host author: new native_guardian.py and tests/test_native_guardian_host.py only.
Root: native_bootstrap.py, native_trusted_attempt.py, exports, selector/gate tests,
focused composition/spec/docs/HANDOFF/workflow. Authors do not commit/push or edit
one another's files. Source reviewers and exact-head CI independently check artifacts.

Test matrix: normal useful IO/broker/grants and exact F/EOF/D/reap; STOP/KILL at startup/
gate/running/post-direct-child-live-descendants; original controller EOF/data/deadline;
leader already reaped but group member alive and empty-group ESRCH no retarget; runtime
flag refusal; pipe/pidfd/alias/extra inheritedFD/malformed finish/ack and deadline races;
exact child ownership/no leaks/non-SIGCHLD/ECHILD traps/old scope and earliest gates.
All inert local fixtures, no model/provider/campaign/evaluator/.env. Actual Linux ABI
is required; Darwin skips and kernel text are not execution evidence. Final source
head/tree/parents, raw full three-version XML/log/ZIP and first failures precede merge.
