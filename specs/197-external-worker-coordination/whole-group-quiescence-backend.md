# WQ-01: cgroup v2 backend and original FD ownership

Status: WQ-01 design reviewed, including the event-field, original-child and
distinct-identity grant requirements below. No backend, native ABI, account
transition, enclosure, retirement observation or monitor consumer is implemented
by this document. WQ-02 through WQ-08 remain open. Read
[the ordered tasks](whole-group-quiescence-tasks.md),
[the existing receiver contract](guardian-receiver-custody.md) and
[the account boundary](account-guardian-followup.md) together with this contract.

## Selected profile and current conflicts

Select one new, explicit `linux-cgroup2-original-scope-v1` profile. It is a finite
local native attempt, with no service, remote scheduler, evaluator or account
provisioning. Unsupported prerequisites refuse this profile before candidate
execution. Existing profiles, defaults, installed image allowlists and F/D
semantics do not acquire a new meaning and are not a fallback.

The current Python launcher in `native_trusted_attempt.py` starts bootstrap B,
starts guardian G directly or through receiver R, publishes the native
registration, and releases the host gate. `native_bootstrap.c` currently creates
the target with `fork()` after that gate. Its existing controller pthread is
started before the fork. The current receiver is G's parent, so receiver death
loses that original reaping relationship. These paths cannot implement the new
contract merely by adding an FD or changing an acknowledgement parser.

Three topology changes are required by the new profile:

1. Only actual target T and its descendants enter the execution scope. B must
   stay outside: B waits for the supervisor's completion acknowledgement, so
   putting B inside creates a cycle between scope emptiness and B's exit.
2. A new finite sealed supervisor S is the actual parent of G and optional R.
   G and R are siblings. R performs storage only; its death or blocked fsync
   cannot remove S's exact-child relationship to G or delay independent stop.
3. B creates a trusted paused pre-exec T inside the original scope before
   publishing the new bootstrap-ready frame. The original host gate releases
   candidate execution only after enrollment, original registration and monitor
   preparation. This is an explicit new bootstrap/control ABI, not the old
   post-gate fork with an upgraded label.

## Platform and kernel contract

The first implementation supports native Linux x86-64 with a matching installed
ELF ABI, a single fixed host PID/user/mount/cgroup namespace context, and an
originally supplied cgroup v2 delegation. Other architectures/namespaces require
a separate reviewed profile. No host Python, user-namespace, PID-namespace,
process-group scan or cgroup v1 fallback is permitted.

The semantic minimum is Linux 5.14: `CLONE_INTO_CGROUP` requires 5.7;
`CLONE_PIDFD`/`waitid(P_PIDFD)` require 5.2/5.4; `cgroup.kill` requires 5.14.
This is not a version-string acceptance test. Before readiness, the actual
acquisition must successfully use the required clone3 flags, pidfd signal/poll
and exact-child wait operations, genuine cgroup v2 files and required leaf
limits under the installed profile. `ENOSYS`, `EOPNOTSUPP`, `EPERM`, missing files,
an incompatible seccomp policy or an unavailable delegation refuse. Failure of
the real T clone is not retried with fork plus numeric-PID migration. The old
guardian's Linux 6.9 process-group pidfd flag is not used or weakened by this new
mode; that old mode retains its own requirements.

The selected scope is one exclusively created non-root `domain` leaf. S must:

- Receive the original held delegation-directory FD from the trusted installed
  acquisition, not accept a worker pathname as authority. Validate its retained
  directory chain, owner, namespace/mount identity and original deadline.
- Verify `fstatfs(...).f_type == CGROUP2_SUPER_MAGIC` (`0x63677270`) on the held
  delegation, new scope and every opened cgroup control/event FD. A writable
  regular directory or copied `cgroup.events` file is never accepted.
- Use one `mkdirat` with a trusted create-only attempt name; `EEXIST` refuses.
  Open the child with `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`; join `fstat`,
  `fstatat(..., AT_SYMLINK_NOFOLLOW)`, device/inode and `statx` mount identity to
  that original creation. A later path lookup may compare but cannot recreate
  the acquisition. Revalidate those originals before enrollment, release and
  consuming an empty observation.
- Read the actual `cgroup.type` as `domain`, require empty
  `cgroup.subtree_control`, set and recheck `cgroup.max.depth=0` and
  `cgroup.max.descendants=0`, and refuse `threaded`/`domain invalid`, replacement,
  unexpected subgroups or mutation of this topology. No resource controller is
  required. The installation reserves this leaf from other management software.
- Open separate original file descriptions for S and G's `cgroup.events`
  readers and `cgroup.kill` writers with `openat`/`O_NOFOLLOW|O_CLOEXEC` beneath
  the held leaf, validating types/access, names and original inodes. Independent
  event readers must not share a dup'ed seek offset. Hold the event readers
  before enrollment; initial `populated=0` alone is not completion proof.

Kernel support and source design are separate from actual installed acceptance.
No current local host or 5090gpu support is asserted here.

## Actual permission prerequisite

The installed profile fixes trusted supervisor identity A and distinct candidate
identity U, including numeric UID/GID and all supplementary groups. S/G/B's
control authority must be inaccessible to U. B's trusted pre-exec child must
perform and verify the actual
fixed credential transition before declaring itself ready: real/effective/saved
UID/GID, supplementary groups, empty permitted/effective/inheritable/ambient
capabilities, a non-recoverable privilege drop and `no_new_privs`. The transition
mechanism must be an independently reviewed installed mechanism; the existing
account preflight/probe does not provide it. No new setuid binary, chmod/chown,
account creation or privilege request is authorized by this design.

The deployment must establish that U cannot write any relevant
`cgroup.procs`, `cgroup.threads`, ancestor common-migration control, topology or
permission control; obtain an enrollment/stop FD through inheritance, procfs,
ptrace, descriptor transfer or an installed manager; remount/reconfigure the
hierarchy; change identities/capabilities; or ask another service to migrate or
attach a process. Linux delegation permits migration within a delegated subtree
when destination and common-ancestor permissions allow it: therefore U must not
be the delegatee or share A's delegation authority. A protected cgroup pathname
or mode bits alone do not prove these denials. ACLs, groups, capabilities, user
namespace mappings, service interfaces and existing descriptor access matter.

The new installed profile must verify these facts with actual inert execution
under U, including attempted migration out, foreign attachment, scope/control
access, privilege recovery and descriptor acquisition. Static preflight and
same-UID fixtures remain insufficient. Existing Landlock/seccomp denies several
routes, including namespace control and pidfd_getfd, but must be validated for
the real credential/runtime path; it does not replace the permission premise.
Candidate ordinary forks/threads inherit the scope. Trusted host administrators
remain in the TCB and must not attach unrelated tasks or move scoped tasks. An
unreserved or externally managed scope refuses; observed foreign membership or
binding/topology drift becomes unknown, never a successful cleanup claim.

The credential transition and original held-grant publication form one new
profile contract. A's current private work/output directories do not become
usable merely by dropping to U. The fixed trusted installed grant publisher
must create each attempt's work/output leaf for numeric U and its fixed group
with mode 0700 beneath an A-controlled parent that U cannot rename or write.
Readonly input/runtime material remains A-owned; explicit POSIX ACL entries
grant only U's required read/search access, including search on the pinned
parent chain, with a restrictive ACL mask and no write permission. Candidate
write access is limited to the original selected writable leaves. R's custody
directory, signing/config/state roots, delegation and supervisor images receive
no U grant. Paths, groups or ACLs must not create an alias to those private roots.

The publisher is fixed trusted native code bound to the installed profile,
selected original root handles and numeric identities; a worker cannot choose
UID, ACL, path, group or arbitrary publisher command. Its required authority,
ownership and ACL setup are a deployment/software prerequisite, not supplied by
the current A-only acquisition. WQ-02/WQ-05 must acquire the held grants after
this publication, retain creator object/name/parent identities and bind actual
UID/GID, mode and complete effective ACL/mask to the original grant owner and
credential transition. Subsequent path reads compare originals, never replace
them. Unsupported ACLs or missing authority refuse this profile. Actual inert
acceptance under U must read every required input, write only the selected
leaves, and fail to access A's secrets or enclosure controls, with inode/grant
revalidation on both sides of the transition. Filesystem access acceptance
still proves no complete writer-capability enclosure. This document performs no
chmod/chown, ACL mutation, privilege or account provisioning.

## Processes and original ownership

```text
C: original Python controller
|-- B: original native bootstrap (outside execution scope)
|   `-- T: atomically created, trusted pre-exec target (inside scope)
|       `-- all candidate descendants/threads (inside scope)
`-- S: finite sealed native supervisor (outside execution scope)
    |-- G: sealed independent stop guardian (outside scope)
    `-- R: optional sealed persistence receiver (outside scope)
```

S survives C and R; G has an independent deadline and S/controller lifelines so
that S pause/death cannot remove every stop path. S and G are finite processes,
not daemons. A scheduler stall or simultaneous stop-owner loss grants no hard
real-time guarantee and no positive evidence.

S creates G and optional R itself with original
`clone3(CLONE_PIDFD, exit_signal=SIGCHLD)` handles. B creates T with original
`clone3(CLONE_INTO_CGROUP|CLONE_PIDFD, cgroup=held_scope_fd,
exit_signal=SIGCHLD)`. Do not use `CLONE_PARENT`, `CLONE_THREAD` or a numeric-PID
migration step. S/B must be single-threaded at these clone boundaries, with
`SIGCHLD` not ignored and no `SA_NOCLDWAIT`. In particular the new B path must not
start the current controller pthread before raw clone3; its original S/G
supervision and finite poll loop cover setup. Review child-side pre-exec code
and libc state as part of the new implementation.

A pidfd returned by clone3 is original observation/signal authority. Polling it
can observe that process's exit; it cannot prove reaping. S retires G/R only by
successful `waitid(P_PIDFD, original_fd, ..., WEXITED)` on its own original child,
with actual terminal status and no `WNOWAIT`. `ECHILD`, a transferred pidfd alone,
receiver exit, saved PID, EOF or current `/proc` state cannot replace this fact.
B similarly owns T's exact-child wait; S may receive T's original pidfd for exit
observation but cannot reap B's child. No claim is made that cgroup emptiness
reaps every descendant. C normally reaps its own exact B/S Popen children;
after C death, this profile does not fabricate C's reaping or a surviving Python
monitor owner. S cannot attest its own retirement.

## FD graph and close boundaries

All private channels are original anonymous `SOCK_SEQPACKET` socketpairs or
direction-checked pipes, created before their consumers start. Fixed versioned
messages bind original context/launch/intent/profile and image digests, the
same absolute monotonic deadline, sequence and exact ancillary FD count.
Reject duplicate/extra/truncated messages, `MSG_CTRUNC`, conflicting roles,
unexpected EOF, and FD aliases/collisions with images, grants, stdio or sinks.
Use `MSG_CMSG_CLOEXEC`, nonblocking finite send/receive, and explicit allowlists;
no abstract/path socket or public worker packet may supply these handles.

| Original handle | Creator and recipients | Close or retirement boundary |
| --- | --- | --- |
| Installed sealed B/S/G/R images and candidate image | Existing trusted acquisition; each native owner receives only its required original image FD | Revalidate seals/bytes, launch/profile and installed original ownership before use; never path re-exec; no candidate inherits supervisor images |
| Delegation directory | Installed original acquisition to S | C drops its transport duplicate after S accepts; S retains the original until the operation ends; never sent to B/T/G/R |
| Scope directory | S creates; one enrollment copy to B and validation copy to G | T closes inherited copy before pre-exec ready; B closes its only copy before ENROLLED; S/G retain originals through stop/observation; no reopen for another enrollment |
| S/G event and kill FDs | S opens separate descriptions under original scope; G receives its own originals | Never reach R or candidate; S/G retain until their own finite stop/observation work ends; kill return does not release them |
| Original B pidfd | C opens only against its exclusively wait-owned, unreaped original B Popen, then passes to S/G | SIGCHLD auto-reap and competing waits are excluded through handle delivery; close C's transport copies after receipt; S/G retain through enrollment and abnormal stop; no reopening from a retained PID |
| Original G/R pidfds | Atomic clone3 outputs owned by S | Close only after S's actual exact-child wait, or leave terminal result unknown if the original budget/owner is lost |
| Original T pidfd | Atomic clone3 output owned by B; original duplicate to S | B retains through its own exact wait; S closes after its observation role; transferred copy grants S no reaping right |
| C lifeline | C is sole writer; B/S/G have readers | C closes only after original cleanup, or actual death closes it; no writer copy in B/S/G/R/T |
| S lifeline | S is sole writer, G reader | S closes only on terminal retirement/death; R/B/T hold no writer that could mask S loss |
| C-S and B-S control pairs | C creates endpoints before B/S; intended endpoint only to each owner | C drops all B-S copies after spawn; trusted T/G/R close any inherited non-allowlisted copies before readiness; close enrollment transfer after its one acknowledged use; retain a separate lifecycle endpoint through completion |
| T pre-exec ready/release pipes | B creates, T gets ready writer/release reader; B gets opposite ends | T reports ready only after credential/isolation setup and private-FD closure; waits without executing candidate; B releases once only after original host gate plus S permit, then closes; T closes both before exec |
| S-G lifecycle pair | S creates, G gets one endpoint | Only S/G; G readiness binds actual scope/stop handles; S requests retirement only after its original empty observation; S consumes G status through its own wait |
| S-R event/durable-ack pair and private records | S creates channel; original private record acquisition belongs only to R | R receives no scope, pidfd, lifeline writer or gate; S never performs R's write/fsync; blocked/dying R cannot delay stop; S still owns R's exact wait |
| Explicit custody-v3 record creator descriptions (software implemented; C/Python mechanism regression passed) | R creates/retains original O_RDWR registration/terminal descriptions; actual SCM_RIGHTS duplicates go R → S → original C custody child | Only trusted S/C may receive; use pread without changing shared offsets/status or writing. Check exact original context, private chain, ACL absence, mount/name/FD identity, nlink, size and original full stat pins before gate release. Close every actual acquired right on failure; never candidate/B/G grants. See [the v3 contract and concentrated Linux evidence](whole-scope-creator-fd-v3.md). V1/v2 are unchanged; this adds no G → R event, S-death reaper, installed-profile acceptance or authority. |
| Original registration/handoff/deadline publication | Original publisher retains creator FDs/pins for C-S binding | Future WQ-05 must retain originals before publication return; a reconstructed record/DTO does not acquire this role; close only after the live operation's checks finish |
| Existing broker, output, fixed module/completion sinks and held grants | Existing original acquisitions | Preserve their exact independent roles; new handles cannot alias them; candidate receives only its reviewed existing allowlist |

The socketpair carrying enrollment and the lifecycle pair must be distinct, so
closing enrollment does not discard stop/terminal supervision. Failure at any
allocation, transfer, fork/clone, slot initialization or readiness stage cleans
up the actual original acquisitions in reverse dependency order; it must not
lose an already-created owner by constructing a wrapper outside its cleanup
region. Partial files and failed original acquisitions are retained as failed,
not reused as a fresh attempt.

## One-shot acquisition and gate ordering

1. C freezes the original inputs, installed images, profile and original absolute
   deadline. It creates original private channels, launches B without target
   execution, obtains B's pidfd from the unreaped original Popen, then launches S
   with that original handle. B waits for original S enrollment authority.
   C must exclusively own B's waits through that delivery: no SIGCHLD handler,
   `SIG_IGN`/`SA_NOCLDWAIT`, generic `waitpid(-1)` reaper, thread or other owner
   may auto-reap B between Popen and pidfd acquisition. Failure to establish
   this routing refuses before launch; a saved matching PID is insufficient.
2. S acquires and validates the exclusive domain leaf and event/kill handles;
   verifies initial empty state; starts G outside it with original stop handles,
   lifelines and deadline; receives exact original G readiness. Optional R is a
   separately parented storage child. In custody mode its registration must be
   durably acknowledged before gate eligibility; failure refuses, not downgrades.
3. S sends B the sole enrollment copy of the held scope. Single-threaded B
   validates it against the original binding and calls the real atomic T clone.
   T runs only fixed trusted pre-exec code inside the scope, closes all enclosure
   authority, installs/verifies the fixed candidate credentials and sandbox, and
   reports trusted pre-exec ready before waiting on its release reader. No
   candidate ELF instruction or Python initialization has run.
4. B closes its enrollment copy and transmits the original T pidfd plus the
   one-shot trusted enrollment/closure acknowledgement. S joins this private
   exchange to the actual scope, T handle and G readiness, rereads its original
   events FD, and observes `populated=1` while T remains paused. A bounded initial
   `cgroup.procs` comparison may reject any member other than the actual original
   cloned T; it is a foreign-member diagnostic, never isolation or empty-state
   proof. All enrollment
   copies are now closed and the fixed trusted B protocol has no second clone.
   An empty, vanished or foreign/drifted scope cannot pass this readiness.
5. Only then may B emit the new profile's bootstrap-ready frame. C publishes and
   validates the original native registration/handoff/deadline, binds their
   retained original publication to S, runs the original observer and arms any
   applicable monitor. S and C revalidate originals and remaining budget. Neither
   observer return nor a stored digest creates gate permission by itself.
6. C writes exact original host gate token plus EOF. B consumes it and obtains
   one matching live S release permit, rechecks original lifelines/deadline and
   grant/profile bindings, and releases the trusted paused T exactly once. T
   performs final deadline/lifeline checks, closes its private pre-exec FDs and
   FD-execs only the original candidate image. Any failed check stops/refuses.

There is a real pre-enrollment race to handle: G could kill an empty leaf while B
still holds its enrollment FD, then B could create T. On every abnormal path
before enrollment is irrevocably closed, S/G first stop B through the original
B pidfd (`pidfd_send_signal` flags 0), observe its actual pidfd exit, then stop
and observe the scope. That exit establishes only that B can no longer create
new children; it is not B reaping or workload emptiness. The same conservative
order is used on other abnormal paths. If B exit cannot be observed in budget,
attempt the original emergency scope kill but retain unknown. No positive empty
claim is made while an authorized late enrollment path remains live.

## Stop, recursive emptiness and independent retirement

S continuously observes original lifelines, B/G status, cancellation and the
same absolute deadline. G independently observes controller/S loss and its own
original deadline. R is not on the stop path. G early exit/pause, B/controller
death, transfer failure, scope drift, invalid framing or persistence failure
closes the candidate gate and enters abnormal refusal; no automatic retry or
new scope is created. S retains G's original handle even if R dies.

For normal completion B waits/drains its actual target children, but its report,
terminal frame and T exit do not close the scope. S must read the original
`cgroup.events` description again with offset reset and a bounded exact parse
(at most 4096 bytes through EOF; exactly one ASCII `populated 0|1` and one
`frozen 0|1` line, in either order; newline terminated; no other, duplicate,
missing or invalid fields). `frozen 1` is a valid kernel value but this profile
does not use freezing, so it causes refusal/unknown rather than an empty-state
claim. Unknown future keys require a reviewed profile update and are not
silently ignored. S checks original identity and deadline before/after every
read, until genuine recursive
`populated=0`. Poll notifications only trigger that read. A previously recorded
zero, arbitrary empty cgroup, `cgroup.procs` listing, leader exit or B's ECHILD is
not this observation. Descendant zombies are not live populated members, so the
observation proves no live execution in the closed original scope; it does not
prove every descendant status was reaped.

For abnormal completion, after closing the late-enrollment route, S/G write `1`
to the original `cgroup.kill` handle and then require the same original recursive
empty observation. The kernel kill operation covers descendants/concurrent
forks, but successful write/signal submission is not an acknowledgement of
emptiness. If a live task cannot terminate or original observation fails, retain
unknown. Do not remove/recreate the scope as an alternate emptiness test.

Only after S has consumed the genuine empty observation may it retire G through
the new S-G protocol and obtain G's actual exact-child wait status. G retirement
and scope emptiness remain separate facts even if observed close together. R's
durable acknowledgement and actual retirement are additional separate facts in
custody mode. The new S-B completion exchange occurs only after the required
original facts are joined; it is neither the old D nor a public quiescent bool.
C consumes it only through the same non-transferable original acquisition,
revalidates original registration/profile/deadline, and normally waits its exact
B/S children before releasing those owners. Lost C/S ownership leaves unknown;
durable replay cannot manufacture a live owner or end a monitor interval.

## Original budget and refused outcomes

Setup, account transition, readiness, enrollment, publication, monitor arming,
execution, stop, empty reads, capture drain, child retirement and optional durable
ACK all consume the original allowance. The implementation reserves cleanup
inside that allowance; it creates no receiver, phase, shutdown or retry budget.
Every boundary checks the same original monotonic deadline before/after. A call
that returns late cannot publish positive completion. At expiry, emergency stop
may still be attempted, but no new empty-state proof, child-retirement claim,
ACK, flush or acceptance is granted a grace interval.

R's regular-file write/fsync may block despite `O_NONBLOCK`. S uses bounded
nonblocking event submission and never waits synchronously for storage before
stop; G remains independent if S is delayed. If R cannot be killed/reaped before
the original deadline, custody/retirement remain unknown. Native syscalls and
scheduling do not provide an asserted hard real-time completion bound.

Missing delegation/credentials, unsupported kernel/profile, original handle loss,
late observations, unsealed/wrong images, conflicting copies/records, foreign
attachment, topology/inode/mount drift, incomplete messages or durability all
refuse or remain unknown. No positive fact is restored from serialized handles,
saved PIDs, a current filesystem view, HMAC receipt, receiver exit or caller
attestation. Execution quiescence grants no writer-capability completeness,
monitor coverage, build/input custody, runtime authenticity, solver/model
acceptance, publication or production admission. All those consumers remain
separate; WQ-06 cannot start from this design document.

## Implementation boundary and acceptance evidence

WQ-02 through WQ-05 must implement the real graph together: sealed native S and
original Python owner; the separate new B/G modes and reviewed FD/control ABI;
real clone3 target placement and trusted pre-exec/account transition; original
event/kill ownership; S's exact G/R child retirement; and the original native
registration consumer. The existing receiver mode stays unchanged; a separate
storage-only R mode is required for this topology. Do not first ship an unused
parser, DTO, detached receipt or accepted boolean.

Focused local tests must prove actual injected boundary faults: late enrollment
after empty-scope kill, allocation/transfer failure, parent/guardian/receiver
death and pause, leader exit with a live grandchild, fork/exec, attempted
migration/foreign attachment, credential/private-FD leakage, independent event
reader offsets, threaded/replaced scopes, deadline at every gate, and both
orders of workload-empty versus G exit. Fixed native targets suffice; no
WebAgent, remote evaluator or company platform is involved. Kernel-unavailable
skips/refusals establish no capability. Separate actual installed-profile
acceptance must establish the real delegation, credential drop and denied
candidate control routes; same-UID fixtures cannot close it.

This document delivers WQ-01 design only. It does not mark WQ-02 through WQ-08
complete, add monitor acceptance or change the current all-false admission
boundary. Parent review must precede native ABI or installed-profile changes.

## Kernel references

- [Linux cgroup v2: populated notification, core files and delegation](https://docs.kernel.org/admin-guide/cgroup-v2.html):
  `cgroup.events` populated is recursive over live tasks; `cgroup.kill` handles
  concurrent forks/migration; delegation needs destination/common-ancestor
  migration permission. A kill submission and a populated observation differ.
- [clone(2)](https://man7.org/linux/man-pages/man2/clone.2.html):
  `CLONE_INTO_CGROUP` places the actual child atomically in a held v2 scope;
  `CLONE_PIDFD` creates the original handle. Neither grants a receiver parentage.
- [wait(2)](https://man7.org/linux/man-pages/man2/wait.2.html) and
  [pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html):
  pidfd exit observation differs from a parent's exact-child wait/reap.
