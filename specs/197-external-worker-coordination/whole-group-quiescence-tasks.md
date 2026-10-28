# P2 whole-workload quiescence: prerequisite and implementation tasks

Status: design and acceptance backlog, with WQ-02 through WQ-05 software now
implemented and partially regression-tested as recorded below. This document
itself grants no cleanup authority. Continue the single-controller local
architecture. No service, remote scheduler, new evaluator or account provisioning
is introduced.

Read this with [the account/guardian follow-up](account-guardian-followup.md),
[the installed guardian sidecar](installed-guardian-sidecar.md),
[the original receiver custody contract](guardian-receiver-custody.md),
[Feature 196's owner boundary](../196-brs-owner-worker-handoff/spec.md), and
[the original producer lifecycle](../193-static-python-rsi-launch/original-producer-lifecycle.md).

## Confirmed implementation boundary

The existing independent native guardian retains the original process/group
handle, lifeline, finish/ack endpoints and absolute deadline. Its abnormal group
stop is an attempted action; its return and watcher exit do not acknowledge that
all execution descendants have terminated. The native receiver can `waitpid` its
own exact nested watcher and retain its original custody/event records. If that
receiver dies, reaping the receiver alone cannot establish retirement of the
nested watcher. Python cleanup therefore conservatively retains unknown in this
case.

These facts defined two distinct software gaps in the former default backend;
the explicit installed-profile implementation below addresses them in source,
while actual deployment acceptance remains open:

1. There is no original kernel-backed execution enclosure, established before
   target execution, whose complete membership cannot escape and whose empty
   state can be observed by an independently surviving owner.
2. There is no original nested-watcher handle retained by a surviving independent
   retirement owner across receiver/controller death and joined back to the
   original registration, deadline and installed artifacts.

A numeric PGID scan, `kill` return, leader pidfd readiness, `waitpid` of one
process, target completion bytes, pipe EOF, D/exit0, an empty inotify queue or a
caller-supplied DTO/boolean closes neither gap. A new parser, getter, public
`quiescent=True` parameter or registry keyed by PID would leave the missing
original execution path unchanged and must not be added as an implementation.

## Required contract before native ABI changes

An accepted backend must establish all of the following together:

- **Original scope:** one create-only, held kernel object belongs to this exact
  native launch/registration, original executable owner, installed backend and
  original absolute deadline. Paths and matching metadata alone cannot recreate
  this ownership after restart.
- **Pre-gate inclusion:** the target joins the original scope before any target
  instruction or Python initialization. Descendants and threads remain included
  across fork, exec, leader exit, process-group changes and `setsid`. No target
  capability permits migration, unrelated attachment or release of that scope.
- **Surviving observation:** a trusted owner outside the execution scope retains
  original live handles before gate release and survives the controller and
  optional persistence receiver. Its readiness is an original handshake, not a
  reconstructed current-record lookup.
- **Complete empty state:** a documented kernel observation on the original
  scope covers every enclosed execution member, rather than only the initial
  leader or a one-time membership listing. Once observed empty, no authorized
  late join or previously escaped descendant can repopulate it.
- **Original retirement:** any supervising watcher/receiver whose original
  handles are to be released has an independently owned exact-child retirement
  observation. Execution-scope emptiness and watcher retirement are separate
  facts. Neither can be substituted for the other.
- **Original budget:** setup, readiness, stop, empty-state observation, capture
  drain and retirement use only the original remaining budget. Reserve cleanup
  time within that budget. Emergency stop may still be attempted at expiry, but
  an expiry creates no observation/fsync grace period or positive completion.
- **Conservative recovery:** lost ownership, unsupported kernel/profile,
  incomplete transfer, conflicting records, partial writes, unavailable
  persistence or late observations remain unknown. Recovery cannot reconstruct
  a live scope or grant a retry from an authenticated report alone.

The explicit Linux cgroup v2 backend is now frozen in
[the reviewed WQ-01 design](whole-group-quiescence-backend.md); it is not an
automatic fallback or a claimed capability of the present host. It requires original held
kernel/filesystem identity, a dedicated non-threaded domain, atomic pre-execution
placement, denied migration/attachment authority, an original recursive
`populated` observation and independently retained stop/observation handles.
`cgroup.kill` submission alone is not the empty-state observation. A writable
directory resembling cgroupfs, copied `cgroup.events` bytes or delegation metadata
does not satisfy this contract. A private PID namespace/reaper is a different
backend and must not be silently substituted when cgroup prerequisites fail.

The backend selection, exact supported kernel semantics and original descriptor
delivery must be reviewed before modifying bootstrap framing, the installed
receiver or the target FD allowlist. Existing native profiles and defaults remain
unchanged until that review and implementation exist.

## 2026-10-28 implementation batch, before consolidated regression

The explicit installed-profile implementation now has source for original
Python ownership, the native create-only grant publisher, pre-exec clone3 target
enrollment, supervisor S, independent guardian G, storage-only receiver R and
original publication-FD transfer. `native_trusted_attempt(..., whole_scope=...)`
is default-off and consumes the same acquisition at registration, both release
gates and completion. This is implementation progress on WQ-02 through WQ-05;
the unchecked tasks below still require consolidated regression and actual
installed-profile acceptance. No source review, harness, default-profile test or
TCG prerequisite probe closes a root-profile deployment task.

The original deadline includes a 250 ms cleanup reserve. A leader-done frame
does not release this reserve while original-scope descendants remain alive.
EOF, helper exit and failed/abnormal cleanup retain unknown. The first profile
requires root A, a fixed nonzero U and preinstalled readonly-root ACLs; acquisition
does not install privileges or alter shared parents. Default frozen RSI inputs
remain exact 0400/0500. The explicit distinct-account
[fixed-U ACL profile](fixed-u-input-acl.md) now has software integration through
prepare, bind, validate, original grants and the whole-scope B entry. Its
consolidated regression and installed-account acceptance remain pending; generic
validators do not silently admit ACL mask changes. WQ-06 writable-view enclosure, original monitor completion,
accepted build/input custody and production CLI remain open.

## Ordered software tasks

- [x] **WQ-01 — Freeze one backend and original ownership graph (design only).** Specify the
  accepted kernel primitive, supported platform/profile, creation and placement
  order, exclusive membership rules, escape prevention, stop/empty semantics,
  exact identities and surviving owner. Map every owned FD to its creator,
  recipient and close/retirement boundary. Record unsupported/refusal outcomes.
  Do not implement an unused DTO or parser while these decisions remain open.
- [ ] **WQ-02 — Create and enroll under the original pre-gate owner.** Implement
  actual kernel-object acquisition and original held-handle retention, then
  enroll the genuine native target before target execution. Revalidate the
  original registration, executable/artifact, scope and deadline at gate release.
  Fail before release on unavailable delegation, identity drift, unexpected
  membership or missing containment; never select a host-Python fallback.
- [ ] **WQ-03 — Retain independent nested-watcher retirement.** Deliver an actual
  original exact-child handle to a surviving trusted owner before readiness.
  Review the descriptor ABI and private transport as part of the same slice.
  Do not recover this handle from a PID, saved DTO, receiver exit, EOF or a current
  `/proc` lookup. Keep abnormal receiver death unknown until that original owner
  has observed exact-child retirement within the applicable budget.
- [ ] **WQ-04 — Stop and observe complete emptiness.** Implement the genuine
  backend stop followed by its original complete-membership empty observation.
  Keep the independent stop owner live if the receiver is paused, blocked or
  killed. Losing the scope, observation stream or deadline refuses quiescence;
  successful signal submission alone remains a diagnostic fact.
- [ ] **WQ-05 — Join the actual native lifecycle.** Bind the original acquisition
  to the same launch/registration, execution image, absolute deadline, original
  custody reference and watcher-retirement handles. Exclude acquisition from
  public constructors, serialization, copies and durable replay. Recheck actual
  helper identities and original objects at consumption boundaries. Release live
  handles only after the original operation reaches its finite terminal state.
- [ ] **WQ-06 — Join the original pycache monitor.** Only after WQ-01 through
  WQ-05, allow that same original native owner to end the independently started
  kernel-monitor coverage interval and drain its original event stream. Keep the
  separate finite writable-view/capability enclosure requirements. Workload
  emptiness does not prove that unrelated processes cannot write monitored roots.
  No target completion, monitor snapshot or detached quiescence receipt may close
  `original_quiescence_unavailable`.
- [ ] **WQ-07 — Preserve abnormal diagnostics and read-only recovery.** Reuse the
  installed independent custody boundary where possible. Optional persistence
  must not delay the guardian's stop, and regular-file writes/fsync must not be
  advertised as hard bounded by `O_NONBLOCK`. Missing durable acknowledgement
  stays unknown. Replay validates retained bytes and references without creating
  a new scope, owner, execution or cleanup allowance.
- [ ] **WQ-08 — Consolidate focused and actual Linux acceptance.** Freeze all
  affected software/test sources first and execute one consolidated regression
  selection. Preserve first failures, unsupported results and original budgets.
  Run actual enclosure/account/backend acceptance separately under the selected
  installed profile; synthetic and same-UID fixtures cannot replace it.

WQ-02 through WQ-05 form the minimum complete software implementation: real
pre-gate scope acquisition, an independently retained observer/retirement owner,
an actual empty-state observation and its native consumer. Splitting out only a
boolean, schema or final scan does not close a task. WQ-01 design has been reviewed;
WQ-02 through WQ-05 native software exists, and the first consolidated focused
batch is recorded in HANDOFF.md. These checkboxes remain open for actual
installed-profile acceptance, not because that software is wholly absent.
WQ-06 still contains implementation work. WQ-07 now has a default-off original
private-directory acquisition, actual S-to-R FD delivery, live registration and
terminal record consumption, and bounded read-only prefix inspection; see
[the custody slice](whole-scope-private-custody.md). It does not add R's creator
file descriptions or a complete abnormal durable-ACK protocol. Those remain
implementation/design gaps, separate from focused and installed acceptance.
Required delegation,
distinct-account deployment and actual Linux acceptance remain separate work.

## Required focused cases and preserved boundaries

Use inert local targets and local kernel fixtures only. Cover a grandchild alive
after leader exit; descendant `setsid`/PGID changes; fork/exec and attempted scope
migration; an unexpected attached member; owner/controller/receiver death;
guardian pause or early exit; unavailable original handle transfer; changed
scope or directory inode; copied/replayed acquisitions; watcher retirement before
execution-scope emptiness and the reverse order; deadline/cancellation at every
transfer/observation; and interrupted/blocked persistence. Prove that each fault
was actually injected and that no later gate or target execution occurs after
refusal. Do not rely on sleep alone to locate a fault boundary.

For monitor integration, inject cache events after target-level completion but
before genuine scope emptiness and require their retention. Unsupported/mock
cases retain missing quiescence. A true original quiescence fact still grants no
accepted build custody, runtime authenticity, model/solver acceptance, publication
or production admission. Existing default native behavior, deadlines, unknown
recovery and all-false authority projections remain in force.
