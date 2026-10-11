# RSI remaining work by priority — 2026-10-02

This is the current execution list, extending Feature 160 and the producer lifecycle SDD.
Code and HANDOFF evidence take precedence over historical gap descriptions and design drafts.
All validation in this iteration is local and provider-free.

## Current open priorities — 2026-10-11

This section supersedes the older execution notes below. PR32 RSI producer-proof
durable recovery and PR33–39 handoff/pin/composition and static source/artifact
evidence slices are merged. Actual runtime acceptance remains separate from those
provider-free contracts.

- **P0**: require a separate late admission identity across the live controller/publication
  flow; complete the Python process/runtime/journal matrix for interrupted launch,
  missing terminal, callbacks, cleanup uncertainty and fingerprint drift. The standalone
  transaction content anchor is implemented, including both prepared-intent interruption
  windows. Independent standalone recovery now checks the same original content at entry
  and final return, then rechecks the original handoff pin/prepared association;128 focused
  and796 combined local cases pass with independent review. PR40 content/export passed
  its full matrix and independent raw/source/tree audit and merged at c0b9bbd. PR41
  independent recovery passed its full run38125047229 and root offline audit, then merged
  at3533dc5 with the tested tree. Neither is full controller admission. Do not
  retrofit post-execution evidence into the original RSI run request.
  The explicit controller register/validate API and independent create-only ledger record
  are now implemented against local fixtures, linking the original run proof and episode
  claim. PR42 passed run38129577604 and independent/root offline audits, then merged
  at d0d4c924 with the accepted tree. They do not automatically
  connect the scheduler or admit a runtime. The continuation adds explicit atomic
  checkpoint references and ordinary-resume row/file revalidation; reference history
  cannot silently delete or replace an obligation. Corrected PR43 source a83a82e has
  its own run38144340314 pending; original source3095231 failed a transport fixture
  race and is not accepted. Automatic scheduler/publication
  first-pin wiring remains open. See Feature191 `late-controller-admission.md` and
  `durable-admission-reference.md`. Each final source requires its own CI/audit/merge.
  The bounded continuation `controller-bound-publication.md` now composes
  publication/recovery with an already pinned reference and covers a real failure
  after the first candidate move, using inert local material. Its final source still
  requires full CI and independent audit. Automatic first pin and owning-thread state
  synchronization remain a separate open task; the current scheduler context has
  no Python runtime/handoff input, and the late evidence does not exist before
  the prepared publication boundary. Do not retrofit a post-execution anchor into
  the request or journal, or substitute host Python for the sealed runtime.
- **P1**: finish Feature189 G1 actual release/toolchain provenance, G2 configured static
  build/closure and G3 exact sealed runtime evidence; compose Feature190 owner/lifecycle
  observations; wire actual local OpenEvolve/Shinka lifecycle/export and production RSI CLI;
  pass dedicated Linux runtime acceptance. The shared adapter evidence envelope is implemented
  with `production_admission=false`; build/parse/verify do not launch, evaluate or admit.
- **P2 deferred**: external worker authentication, multi-host ownership, remote evaluator,
  distributed scheduler, service API and Shinka/Slurm. These are not this iteration's blockers.

The narrow contracts and task status are in Feature191
`admission-attempt-and-export.md` and `tasks.md`. Do not repeat already merged durable
resume work or turn synthetic evidence into real-runtime acceptance.

## Current open priorities — 2026-10-08

PR #6, #7 and #8 are merged. Feature170 trusted local C composition, Feature171 declared-file
runtime inventory and Feature172 Linux target-control restrictions passed their own final-head
complete Ubuntu3.11/3.12/3.13 matrix. PR7 run37660700817 used no retry and merge009691a
has the tested tree. These bounded features do not establish actual Python campaigns or complete
containment. Feature173 passed its own final-head three-version CI run37669528518, all seven
phases first attempt without retries, and merged at d3f4fbf with the tested tree. Historical
pending statements below are superseded.

- **P0 current**: Feature174 and Feature175 are merged through PR9/PR10 after their own
  final-head three-version raw CI audits. Feature175 known failed/cancelled process-only
  settlement does not infer outcomes from missing evidence. Feature176 input mutation gates
  and Feature177 closed-layout preflight are implemented in PR11; its final-head CI/merge
  must be confirmed independently. Feature178 adds a bounded Linux child inherited-FD handoff
  in a separate branch, with original broker/control/deadline semantics. Full grant-object/path
  identity, writable/read overlap, allowed-FD/ioctl/egress closure and independent stop supervision
  after bootstrap death/pause remain open P0 work. Abandoned is an explicit disposition.
- **P1 next**: immutable runtime/load protection, archive/loader/import completeness, versioned
  delivery, local Python inherited-pipe broker fixture, real OpenEvolve/Shinka project adapters
  and production RSI CLI solvers. Feature177 inventories complete finite filesystem membership
  but runtime_load_protection/archive_contents_complete/loader_dependencies_complete remain
  explicitly false; it does not supply read grants or launch authority. Feature171 wire is unchanged.
- **P2**: multi-host ownership, services and distributed scheduling stay deferred.

## Historical execution note — 2026-10-07

Feature170 local implementation now composes the existing OpenEvolve strategy with frozen config,
formal native lifecycle/broker, one local exact seed admission, the established atomic commit and
strict read-only completed replay. Started/unknown never repeats effects. See Feature170 spec,
plan and validation; its final-head CI/merge is pending. This does not close Python runtime
inventories, real project launch trust, production RSI CLI solvers or actual campaigns.

- **P0**: PR #4 merged at `2b8d05e`; its Ubuntu Python 3.11/3.12/3.13 full CI and
  post-merge main CI passed. The next branch must pass its own full matrix. Current work fixes
  the bootstrap-only worker classification: terminal success requires process exit, the original
  deadline and owner-checked cleanup. Native recovery shares the pure checks and retains current
  boot/file/stream checks. Missing terminal stays unknown; complete containment/egress,
  post-bootstrap descendant supervision and trusted unknown-to-success reconciliation remain open.
- **P1**: native RSI scheduler/provider/controller composition has local fixture coverage on main.
  Real OpenEvolve/Shinka project launch trust/runtime manifests and production adapter wiring
  remain open: the current OpenEvolve launcher uses `Popen`, Shinka imports retained source, and
  RSI CLI solver choices are fixtures. Next scope is an explicit trusted launch path in the
  existing adapter with create-only admission and exact replay, proved first using a local C
  producer. Python project interpreter/package/import provenance requires its own manifest.
  CI regression retries are being narrowed to one exact immutable historical flake, preserving
  both reports; no current-product full-phase retry is allowed.
- **P2**: multi-host ownership, distributed scheduling, remote evaluators, real campaigns and
  model adaptation are deferred. They do not block this local P0/P1 corrective delivery.

The sections below record implemented local progress and the limits of each contract.

## P0 — correctness and interruption safety

- Feature179 continues Feature178 with an explicit Linux target fcntl/fcntl64/ioctl gate.
  Private anonymous-pipe SIGIO baseline, filtered refusal and ordinary descriptor/lock/native
  broker checks are local fixtures; Linux final-head CI and dependent merge remain required.
  Grant path/inode/overlap, complete egress and independent stop after bootstrap death/pause
  remain separate open P0 work. P2 multi-host services and scheduling stay deferred.
- Preserve caller cancellation and parent deadline across native attempt, receipt, output and
  publication boundaries; preserve the existing commit critical region and native-attempt-only
  intent deadline scope.
- Require policy-bound unseen pass and pass-rate regression evidence for transfer promotion;
  bind receipts to inputs, policy, memory and trial evidence. Legacy score-only approvals cannot
  establish the new controller approval identity.
- Persist holdout trial intent/result and budget before evaluation. Completed trials replay
  without another call or charge; uncertain calls require evidence-bound reconciliation.
  Runner/component/manifest/policy drift and budget refresh fail closed.
- Shared parent learning/holdout accounting is implemented: original counters/deadline and
  immutable external reservation receipts survive crash, replay and terminal resume. Both
  uncertain child trial and outer generation reconciliation consume parent unknown budget.
- Controller completed generation markers bind the actual independent admission checkpoint;
  hash-valid controller appends cannot turn pending memory into terminal successful learning.

## P1 — controlled runtime composition

- Bridge AgentLoop candidate artifacts into the process clean-room verifier using bounded,
  no-follow reads, separate Actor manifest and raw-byte digest checks, and immutable public input.
- Add an explicit governance gate before a new episode uses a memory snapshot, so revocation
  stops subsequent retrieval without rewriting the immutable snapshot or its digest.
- Complete Actor evidence now has a durable create-only sidecar and first-call claim. Unknown
  claims never restart the evaluator; exact completed replay is read-only. DRS composition passes.
- A provider-free unified worker evidence verifier now rebinds launch attestation, trusted
  process registration, bootstrap handoff, native process terminal, original deadline and cleanup into a read-only
  classification. Handshake-only pass/fail never establishes process terminal authority.
  It reports trusted completed/failed, unknown recovery required, or identity drift; it does not
  provide external source authentication or multi-host ownership.
- A configured generation coordinator automatically admits post-practice candidates using the
  frozen manifest, durable child trials and shared parent budget. Same-run inherited generations
  have explicit lineage; rejected memory keeps the parent and unknown blocks the whole run.
- `generation_revalidate_before_dispatch=True` enables one deterministic revalidation per new
  episode, using the same parent budget. Failure quarantines the generation and blocks the solver;
  unknown requires explicit reconciliation. Completed before-run checks replay without evaluation.
- A real local native producer fixture now covers bootstrap/broker/formal receipt/strict output/
  independent candidate evaluation/publication/archive/population/delivery/read-only recovery.
- Still open: external worker source/ownership and trusted
  unknown completion, complete producer recovery/transport coverage and real campaign acceptance.
  These must not be closed by fixture evidence.
- The opt-in local `DurableSolverGateway` now claims an episode before execution and persists
  full results before controller handoff. Completed application records replay without another
  call; `restore_result` repairs a missing controller wire. Pending claims never retry and only
  failure settlements are accepted. This local delegate/SQLite boundary does not authenticate
  external workers or implement unknown-to-success reconciliation.
- Active native broker cancellation now stops real blocked loopback HTTP I/O and reaps its
  exact worker; lost acknowledgement remains unknown. Original request deadlines/counts and
  publication gates are preserved. The existing HTTP lifeline now has a real controller-only
  hard-death/broker journal combination regression: local I/O stops but durable admission remains
  active/unknown, and recovery neither retries nor signals. Full native crash ownership and
  complete egress remain open.
- `read_native_retained_candidate` exposes immutable portable materials from exactly one
  caller-selected published native candidate, with original launch pins, expected journal/formal
  receipt digests and before/after integrity checks. It is supporting evidence only: existing
  native launch records cannot establish an RSI request/memory attribution. A future real gateway
  now has a create-only full request/memory launch binding available, but still requires the
  original episode admission, result mapping and independent verification.

## P2 — local diagnostics and later composition

- Add strictly read-only usage CLI diagnostics with nullable totals, unknown receipt counts,
  stage breakdown and explicitly estimated costs.
- Explicit controlled cross-solver memory translation and repeated-pass confidence policy are
  implemented as bounded local APIs. Translation only creates unresolved target drafts; Wilson
  marginal confidence evidence never replaces source/holdout/admission authority. Provider billing
  and model weight training remain separate acceptance/research work.

The named local slices have validation recorded in tasks.md, validation.md and
HANDOFF.md. Official evaluators, external project launch trust/default project registration and
real campaigns remain open. Revalidation is a configured local policy/API, not a distributed or
background scheduler. The governance gates read trusted local latest heads and do not establish
historical database deletion/rollback protection or remote atomic leases. Confidence integration
with actual official campaign raw receipts remains separate from the explicit analysis API.
