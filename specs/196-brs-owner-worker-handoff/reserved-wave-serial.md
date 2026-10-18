# Reserved-wave serial original-owner continuation

Status: reviewed contract; implementation is in progress. Pure comparison, ledger,
preparation transport, native provider/completion, serial-driver and finalization
components have focused development coverage. Natural serial execution and
final-source acceptance remain open. The current two-child rejected fixture has
not completed owner admission and mailbox handoff in the latest local run; the
root cause remains under investigation. This is a development failure, not a
passed acceptance scenario.
The earlier recorded failure
`rsi_brs_reserved_prefix_material_path_invalid` from
`read_reserved_brs_prefix -> validate_brs_reserved_prefix` is fixed by strict
rejection-evidence path/pin mapping. The latest integrated run advances to
`rsi_brs_reserved_serial_settled_transport_missing`; the settled-transport
contract remains open and must be repaired without weakening the validator.
This is the next coherent Feature 196 P0 behavior after the original selected-owner
[known-rejection lifecycle](rejected-owner-lifecycle.md). It is not evidence that
the preceding lifecycle has completed its separate platform/CI acceptance.
The implementation plan is [reserved-wave-serial-plan.md](reserved-wave-serial-plan.md)
and the executable task inventory is
[reserved-wave-serial-tasks.md](reserved-wave-serial-tasks.md).

## Behavior and boundary

A private controller composition executes the original, already reserved BRS wave
one child at a time. Each untouched child receives fresh transport custody and a
new original live owner. Its genuine published or known all-rejected lifecycle
settles exactly one root execution before the next child can begin. A fresh
controller can resume the untouched suffix after independently validating the
completed prefix; it cannot recreate an old owner or retry a started child.

This extends the ordinal-zero/fresh-lineage-only restriction only for the new
private serial path. The existing constructor and entry points remain strict
unless explicitly routed through that path. Public native BRS, production admission
and online publication remain closed. There is no new CLI mode, SQL schema,
distributed ownership, external authentication, remote evaluator or P2 work.
Validation uses local provider-free/inert fixtures, including genuine local
transaction, storage, mailbox and channel kernels. It runs no real model, solver
campaign, WebAgent, remote evaluator or company evaluator. The 5090gpu host may run
CPU regression fixtures on the same frozen source.

## Original wave invariants

**RW-01 — immutable original domain.** The original run, wave, ordered plan,
episode IDs, exact request bytes, M0/root-memory snapshot, solver/source policy,
workspace and ledger identity remain bound to original durable history. Every
child uses M0, even when an earlier child has published a candidate. A later
approved memory snapshot does not rewrite any request in the wave.

**RW-02 — reserve once.** Existing `_prepare_intent` reserves all N original
intents before the first dispatch, including launch/solver/practice and
evaluator/verifier stages. The private entry requires that complete durable
reservation. Neither child selection, terminal settlement, continuation nor resume
charges any of it again. Attempts remains N; a distinct completion cursor is
derived from settled executions. Original absolute wall-clock/stage deadlines and
remaining parent budget are never restarted or enlarged. Cancellation/expiry may
stop the suffix, but cannot refund a prior attempt or turn it into a fresh one.
An interrupted initial reservation must first be resolved by the existing exact
intent-reuse path; missing intents cannot be fabricated by this serial driver.

The detached `advance_brs_ordinal` / `dispatch_brs_successor` contract remains
unchanged. Its counter increments and preclaim are incompatible with an already
reserved live wave and are not called by this composition.

The A-line pure helper now compares detached original full-reservation/current
controller checkpoints, requires whole-domain attempt observations and preserves
original budget/deadline bytes. Its development tests do not prove original-record
custody, current control permission, preparation handover or complete serial
execution; these remain required live integration and acceptance work.

**RW-03 — contiguous settlement.** With original ordinals `0..N-1`, the root
executions must be exactly a completed prefix `0..k-1`. The next selection is k,
or wave-complete if k=N. Holes, duplicate/foreign IDs, reordered associations,
unsettled earlier obligations or execution/terminal mismatches refuse before
creating transport or an attempt. A descriptive projection is not launch or
publication authority and contains no callback, owner, claim or reusable permit.

## One continuous live child

**RW-04 — fresh custody.** The owner thread holds one exclusive nonreentrant run
lease across the wave, waits and shutdown. Before each child it validates the
original policy/source/budget, completed prefix and exact current tail head. It
creates a fresh selected context, handoff/nonce, admission channel, mailbox,
worker endpoint, Future/executor and native session. The original full-wave
domain remains immutable; the selected transport domain is only that child.
The child's publication owner is constructed by the original owner thread only
after the worker naturally establishes its running episode and started claim.

Old request/ACK/nonce/guard/mailbox contents are retained. Never clear, reset or
rebind an old channel or owner for a sibling. Closing old transport is allowed;
erasing its evidence or using a closed channel as a fresh one is not. No worker
receives root-checkpoint mutation, owner or publication authority.

**RW-05 — one natural claim creator.** The selected worker invokes ordinary
`NativeRSISolverGateway.run(request, M0)` through the existing natural runner.
That invocation alone creates the native claim. The driver neither preclaims via
the detached successor nor transfers `_fresh_child_dispatch` across threads.
Immediately before starting the worker, the owner checks the exact untouched
ordinal and captured head under its lease. No owner root mutation occurs between
this gate and the worker's natural preparation/mailbox handover. The owner then
binds the actual native plan, running episode and started claim to this original
session before any publication transaction. Drift or a pre-existing claim stops
the path; terminal gateway replay is not permission for a second live owner.

**RW-06 — preserve each outcome protocol.** A published child uses genuine
before/prepared/staged/terminal publication evidence, actual completed native
result, ready/ACK and mailbox lifecycle. Native publication and the subsequent
RSI verifier decision are separate layers: a completed episode must carry its
actual matching verifier attachment, whose outcome may be pass, fail or
unresolved. Each is already settled for scheduling and cannot be dispatched
again; a failed or unresolved RSI verifier never grants memory promotion.
Episode/result receipts, trace/source/dependency/events and actor evidence must
match. An all-rejected child uses genuine C1,
writer-returned provenance P, C2, pre-arm capture, original staged ready/ACK,
mailbox delivery and actual failed native result. No synthetic publication,
successful manifest, shared replacement success/rejection wire or DRS owner is
introduced. Rejection changes neither population nor memory and is a known
settled scheduling outcome, not unknown.

**RW-07 — settle, read back, retire, then continue.** The actual terminal
episode/claim/result and original delivery/callback/worker-cleanup evidence are
validated before root settlement. The owner uses the existing asserted
`_reconcile_brs_terminal_locked` under its already-held lease; it does not call
the public facade and acquire a second lease. One captured-head CAS atomically
appends that ordinal's exact execution and removes only its exact recovery fence.
Complete readback must equal the proposed root delta. Only then may captures
advance and the original owner/handoff retire. Close transport before executor
join; do not hold the short observation mutex across source hooks or waits.
No next-child transport, Future, claim, callback or transaction is created before
verified settlement and successful live retirement. A write/readback ambiguity
keeps the old capture and blocks continuation; never adopt a latest head to repair
the live owner.

## Append lineage and retained history

**RW-08 — prove both predecessor axes.** Each adjacent ordinal appends to the
exact retained lineage prefix; all earlier descriptor bytes and file pins remain
unchanged. Ordinal zero preserves its existing initial format. Nonzero before
records use existing `ProducerLineageBeforeIntentV2` fields: previous attempted
journal/outcome/terminal/lineage and latest published journal/terminal/lineage.
The immediately previous attempt may be rejected while the latest published
predecessor is older or absent. Published staged/terminal and rejected-v2 terminal
records retain their genuine ordinal and original associations. Shared descriptor
parsing validates format only; the private BRS prefix proof establishes custody
and original history. Do not fabricate a one-batch lineage to invoke an old owner
validator, nor use the success-only lineage reader for mixed-outcome authority.

**RW-09 — validate history after population changes.** A later legitimate
publication changes live archive/state files. Historical validation binds each
settled root entry, obligation, terminal and native material to its original
recorded heads and immutable before/after snapshots. For a published child its
poststate is the original after snapshot; for a rejected child it equals before.
The next before-v2 snapshot content must equal that predecessor poststate, with
the exact attempted and published links. Prefix observations cannot refresh old
pins from live files or accept a caller-selected prefix as original authority.

Current live archive/state identity is checked only at the current tail/active
transaction gate; old immutable snapshot/descriptor, candidate-source, receipt,
provenance and native material pins remain strict. A legitimate suffix must not
invalidate a completed prefix, while any changed/replaced historical material
still refuses. In-flight/unknown archive changes do not prove a known terminal.
Existing cached validators that require old live files to remain current are not
used unchanged for the serial prefix.

**RW-10 — retain all bounds.** N is at most eight, total candidate count at most
32, projection at most 112 KiB/depth 32, each descriptor at most 32 KiB, each
snapshot at most 16 MiB and retained aggregate material at most 64 MiB. Keep the
128 KiB SQLite-record ceiling and existing root/lineage/preflight ceilings.
Account for every original retained material across all ordinals, including
separate pinned files with equal content digests; digest equality does not waive
capacity charges. Refuse before new work if the next append cannot fit. Do not
raise a ceiling or discard earlier evidence to make the wave pass.

## Fresh-controller recovery

**RW-11 — derive progress, never reconstruct live authority.** A new controller
acquires the existing run lease once, verifies original policy/M0/requests/full
reservation/deadlines and independently validates the contiguous completed prefix.
The cursor is derived from existing plan, intents, execution checkpoints and
terminal/lineage history; no durable cursor, authority flag or owner registry is
added. A fully settled child creates no new solver call, claim, result or root
write during replay.

The recovery decision covers the whole original domain, including native episode,
claim, result, material/reference and obligation records. A crash between claim
creation and mailbox/fence registration must not make a started child appear
untouched merely because its root fence is absent.

| Durable observation | Permitted action under the new lease |
| --- | --- |
| Exact completed prefix with independent terminal/native/cleanup proof | Reuse settled prefix read-only; consider the first untouched suffix child. |
| Complete independent terminal proof, but exact root settlement missing | Explicit locked reconcile may settle that one execution/fence delta; no transaction, callback or worker retry. Revalidate the resulting prefix before selection. |
| Started/running/unknown claim, partial C1/P/C2 or ready/mailbox/native evidence, ambiguous root, unmatched material | Preserve evidence and stop all later children. Explicit reconciliation is required; no automatic conversion to rejection or retry. |
| No durable attempt trace for the next original intent anywhere in the domain | Create fresh custody for that untouched intent, subject to original budget/deadline and all current gates. |
| Root committed before ephemeral retirement | Require a newly acquired exclusive lease, exact root readback and existing independent worker/native cleanup proof. Do not recreate the old owner or invent a durable retired bit. |

Timeout, abandonment or cancellation is not known all-rejected completion.
Unknown preserves the recovery fence and old observations. A still-running old
owner prevents acquisition of the new lease. Missing original evidence refuses;
resume cannot migrate an old run lacking the new original policy pins.

**RW-12 — finish the original wave contract.** After all N children settle,
perform existing `_commit_flow` processing in original plan order using M0 and
normal governed memory/holdout admission. Rejections are never promoted. Scheduling
completion and successful publication remain separate facts; an all-rejected
wave may finish scheduling without a published candidate. Preserve existing
finalization recovery/idempotence rather than adding a second finalization path.

## Acceptance evidence

The behavior gate is one integration slice, not independent guard PRs. Natural
two-child fixtures must cover published→published, published→rejected,
rejected→published and rejected→rejected. A three-child mixed wave must distinguish
the previous-attempt chain from the latest-published chain. Run with exactly N
reserved attempts/stages and also the eight-child bound; verify counters, M0 and
absolute deadlines through live continuation and fresh-controller resume.

Record fresh object/nonce/session identities, one natural claim/result/root entry
per child, exact prefix preservation and historical evidence after later real
local population updates. Inject interruptions at worker start/claim, before,
prepared, C1/P/C2, ready/ACK, delivery/callback, native result, root CAS/readback,
retirement and next claim. Assert the boundary was reached and no later child
started. Include stale/foreign/duplicate handoffs, reordered/holed prefixes,
material/policy/head drift and all capacity limits.

Keep ordinal-zero, detached successor, DRS/provider-free and public-refusal
regressions. Focused tests, Ruff, compileall and `git diff --check` precede source
freeze. Matching macOS/Linux case inventories on the same source, independent
source/import/raw/XML/exit review and the full required 33-job GitHub CI precede
main integration. Earlier snapshot passes do not satisfy this new behavior gate.
