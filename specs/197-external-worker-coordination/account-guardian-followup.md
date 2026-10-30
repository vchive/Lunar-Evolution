# Account isolation preflight and abnormal guardian evidence

Status: the installed-account read-only preflight is implemented and locally
tested; it is not an actual account switch or active isolation acceptance. The
installed native bridge and independent restart vault are implemented in the
companion custody continuation. Account transition and abnormal durable guardian
evidence remain design/software gaps; no production acceptance is supplied.
Continue `native-lifecycle-followup.md`; do not replace the single-controller
local CLI model or add a service/scheduler/evaluator/lease protocol.

## Account isolation preflight: smallest useful software slice

The trusted wrapper signing account must not execute arbitrary candidate code.
A launcher invoking host Python under the signing account cannot satisfy this
boundary. Keep fixed inert channel acceptance separate from native candidate
acceptance. Define preflight only for an installed profile; a public channel may
select neither UID/GID, executable, runtime root, key path nor arbitrary argv.
No caller-provided `isolation_accepted=true` boolean can enable execution.

A later local read-only preflight should compare an independently installed,
private, fixed profile with current machine state and produce a bounded fixed-code
report. It must not provision accounts, chmod/chown, start candidates, request
privilege, write a successful acceptance record or update an original deadline.
The report should distinguish configuration absent, unsupported, observed refusal,
and ready-for-acceptance. Ready-for-acceptance is not isolation acceptance.

The trusted installed profile should bind at least:

- Original trusted-wrapper and candidate-account numeric UID/GID and relevant
  supplementary groups, with explicit inequality and no candidate membership in a
  signing-key group. Names alone are not stable identity.
- Original key/config/state directory chain and regular-file identities, restrictive
  ownership/modes and absence of symlinks/hardlinks. Candidate account access must
  be denied; unreadable ACL/capability/namespace evidence is unknown or refusal,
  rather than a mode-bit proof of denied access.
- The already reviewed installed native runtime/artifact and its isolation profile
  digest. Missing accepted static/native runtime remains unaccepted; a successful
  host interpreter invocation is not a substitute.
- The exact installed account-transition mechanism and authority, independent of
  `PATH`, shell argv, caller environment or remote supplied commands. Inspecting
  setuid/root bits or helper bytes is only a preflight fact, not proof of a safe
  transition.
- Platform/kernel isolation prerequisites required by that profile. Unsupported
  bwrap/userns, denied namespace operations or absent required privilege remain
  explicit unsupported/refusal; do not silently change runtime/profile.

Existing 5090gpu observations (no sudo/KVM; bwrap/userns EPERM) are historical
constraints, not newly executed preflight. KVM is needed only for a profile that
requires it. Do not make a remote probe or weaken the selected isolation boundary
as part of implementing a local report.

After code review and environment provisioning, actual acceptance must execute a
fixed no-secret probe under the distinct candidate identity, show no access to
signing key/state and no inherited secret-bearing descriptors/environment, and
observe the original installed runtime/isolation contract. Those are environment
and active acceptance tasks; static preflight cannot close them.

## Guardian abnormal durable evidence: independent native design required

The current independent guardian holds the original group pidfd, owner/lifeline,
finish/ack channels and original absolute deadline. Its abnormal path invokes a
group signal and exits 78; the signal return is currently ignored. It has no
prebound durable evidence sink. Do not reinterpret exit 78, successful SIGKILL,
leader pidfd readiness, numeric PGID absence or later Popen exit as whole-group
cleanup proof. Current read-only native inspection must stay unknown when no
valid original terminal/cleanup proof exists.

A future native-only evidence path needs its own reviewed protocol. Minimum
requirements before changing C:

1. The original trusted launcher creates an exclusive bounded private sink before
   guardian readiness and target gate release. Capture the creator FD identity;
   bind sink, original native launch/registration, original deadline/binding and
   installed guardian artifact/profile. The target must never inherit this FD or
   gain path access. Any additional descriptor delivery must be reviewed against
   the current fixed native control framing; no unreviewed spare-FD side channel.
2. Use a fixed-size/versioned record with explicit trigger (original deadline,
   lifeline EOF, or supervisor abnormality), original context digest, observed
   signal attempt/result/errno and independently established proof status. Do
   not write keys, attestation nonce, arbitrary prose or candidate bytes. Distinguish
   signal attempted, proof unavailable, write incomplete and durable diagnostic;
   none imply successful cleanup on their own.
3. Specify who can establish group termination under the exact platform primitive.
   A pidfd for the leader alone cannot establish that fact. If the existing group
   primitive offers no documented/accepted termination acknowledgement, the
   maximum record is cleanup unknown. Do not invent an acknowledgement from poll,
   kill return or exit status.
4. Define bounded partial-write/crash behavior and byte/inode/deadline validation.
   The guardian must not depend on the dying Python parent or a newly started
   background service. A preallocated fixed sink plus crash-detectable format is
   a design option, not a decision here. Directory durability, exclusive publication
   and fsync failure semantics require review. Missing/truncated/duplicate/conflicting
   records must remain unknown; the reader never repairs or fabricates them.
5. Use the original deadline for every action. At expiry there is no renewed grace
   period or post-expiry unbounded fsync/handshake. Specify which observations can
   fit before expiry, what still occurs as the original emergency stop, and why
   an incomplete evidence write leaves unknown. The cleanup action must not wait
   on optional diagnostics at the expense of the existing original stop behavior.
6. Keep this as a separate abnormal diagnostic record. Do not manufacture the
   normal native terminal/execution receipt, completed lifecycle, result admission
   or controller-observed remote cleanup authority. A worker-local authenticated
   assertion remains worker-local until separately reviewed observation semantics
   exist. All current publication/native-success/remote-cleanup authority stays false.

Required future real acceptance cases: genuine SSH loss before native terminal,
wrapper death, launcher death, owner/lifeline EOF, original deadline expiry,
guardian/sink failures and partial writes; exact original target start count,
no deadline renewal, private FD absence in target, immutable original binding,
conservative unknown on incomplete evidence and unchanged controller unknown.
Do not use a previously sealed receipt with dropped response as a substitute.

## Work split and honest completion criteria

Software still open: reviewed installed account transition and actual access /
runtime evidence consumers; accepted build/input custody and production CLI
composition; independently reviewed guardian evidence protocol, surviving trusted
persistence boundary and implementation/tests. Read-only account preflight and
installed native bridge / independent same-boot restart-anchor restoration are
implemented; their actual production acceptance remains separate. Environment still open: distinct-account provisioning,
required profile privileges/kernel support, accepted isolated runtime and active
hard-disconnect/account-access acceptance. These are separate items. None is
closed by static pins, syntax checks or inert SSH/HMAC success.

### Deadline and durability constraint

A regular file is not a bounded diagnostic channel merely because the host
preopens, preallocates or pins it. Regular-file `write`/`pwrite` and `fsync` can
block; `O_NONBLOCK` does not establish a hard completion bound for those calls.
Checking the original deadline before and after a call detects an overrun but
cannot prevent it. The guardian must stop the original group before optional
diagnostics, and an attempted write, exit status or successful signal must never
stand in for a durable acknowledgement. At expiry there is no additional budget
for a file flush or handshake.

A single bounded nonblocking pipe write can limit submitted bytes and retries,
but it does not provide restart-readable evidence after controller death. If the
only reader belongs to that controller, its death also removes the receiving
path. Even an accepted pipe frame is not a durable acknowledgement. Adding an
observation-only pipe protocol would therefore leave the durable-evidence gap
open while adding another descriptor ABI and validation surface; it is not part
of this continuation.

Distinguish the remaining work as follows:

- **Unimplemented software:** original-context/deadline-bound sink delivery,
  abnormal trigger and signal result/errno capture, crash/partial-write handling,
  conservative read-only inspection and corresponding negative tests. A DTO or
  parser alone does not implement that execution path.
- **An unresolved design prerequisite:** a separately trusted durable receiving
  boundary that survives controller death and can acknowledge persistence without
  making the original guardian wait beyond its deadline or delay its group stop.
  Its original identity, custody, lifetime and acknowledgement semantics require
  review before choosing a protocol. No new account, privileged helper or
  background service is introduced or authorized by this document. If persistence
  cannot be acknowledged inside the applicable original budget, evidence remains
  unknown; group-signal success still does not prove whole-group cleanup.
- **Subsequent acceptance:** once that design and its software exist, real
  disconnect, account-access, sink-failure and original-deadline cases still need
  execution under the selected installed profile. Missing machines or privileges
  are not the sole present blocker: the durable receiving design and its software
  are also unfinished.
