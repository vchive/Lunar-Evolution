# Tasks

## Explicit fresh child execution continuation

- [x] Specify `child-execution-flow.md`; persist the original opt-in and exact
  execution policy in the immutable run request and every run/checkpoint revision.
- [x] Select each original ready child using its historical request memory;
  bind the existing provider under the held controller lock and active DRS flow
  without replacing the controller-wide root gateway or original run proof.
- [x] Continue only adjacent successful staging with a consumed owner/CAS permit;
  claim atomically before running, then use a thread-bound one-call continuation
  to enter the original scheduler, prepared admission, publication and mapper.
- [x] Recover published evaluation receipts with the original verified journal's
  Python handoff digest; retain legacy receipt bytes and all original drift gates.
- [x] Select the original child for terminal replay and explicit failure reconcile;
  ready/started readback cannot recreate a continuation or restart a provider.
- [x] Complete unified single-child success/interruption/recovery regression:
  300 distinct cases, zero failures/errors/skips; frozen 223 product files,
  whole-source Ruff/compileall/diff checks and ten README CLI commands pass.
- [ ] Complete this slice's own full CI/raw-source audit and merge.
- [ ] Accept multiple DRS episodes with distinct child IDs, practice learning and
  changed approved memory; accept BRS separately before any production CLI claim.

## Atomic child claim and fresh preclaim continuation

- [x] Reuse the original native claim table/DTO with paired controller-lock and
  checkpoint pins checked in the same SQLite transaction as the insert.
- [x] Add an explicit held-lock child claim API; freshly resolve the original
  ready proof, reject competing claims and preserve started after interruption.
- [x] Check original parent execution control, cancellation and fixed deadlines
  at initial/final scheduler preclaim observations without extending budgets.
- [x] Invoke the explicit provider preclaim hook before fresh gateway claims;
  retain configuration/hook/ledger identities across read-only observations.
- [x] Preserve legacy unbound native calls with a call-local query-only ledger
  inode pin; retain strict bound identity and refuse binding removal or drift.
- [x] Add claim race/interruption, preclaim control and gateway/scheduler
  composition regression cases; complete independent code review.
- [ ] Complete unified final-source regression, full CI/raw-source audit and merge.
- [ ] Connect retained claims to child execution, receipt/admission/publication
  and recovery before enabling multi-episode DRS/BRS or production CLI dispatch.

## Controller-called per-episode staging continuation

- [x] Specify the staging-only boundary in `per-episode-producer-launch.md`;
  preserve the original run proof, fixed deadline and existing ledger limits.
- [x] Call pure capacity preflight before reservation and save an adjacent durable
  preparing checkpoint before create-only native inputs/launch/child sidecar effects.
- [x] Bind the single-use transient permit to the original owner/state/CAS; retain
  full identity, request/memory, plan and independently captured file pins in ready.
- [x] Preserve preparing/unknown and partial evidence on interruption; refuse
  read-only resume without restaging, renewing budget or adopting disk pins.
- [x] Refuse ready dispatch before episode/native claim and reject BRS opt-in
  before run creation. Keep ordinary unconfigured controller behavior unchanged.
- [x] Add 19 core and 8 independent controller cases; complete independent
  source review of the frozen staging/controller implementation.
- [x] Complete the integrated staging baseline's regression/static checks and
  full CI/raw-source audit at `main 82191cf`, run `38428650836`. The new child
  claim continuation has its separate final-source obligation above.
- [ ] Implement the remaining episode-scoped DRS gateway/admission/store/scheduler
  authority and exercise target failure → practice success → target retry with
  distinct child IDs and changed approved memory. Staging ready is not execution.
- [ ] Freeze and accept the separate real project runtime profile described in
  `project-runtime-profile.md`; the current candidate startup/codec module set
  does not establish an OpenEvolve/Shinka runtime closure.

## Single-episode producer composition continuation

- [x] Specify the single-context boundary in `single-episode-producer-gateway.md`;
  retain the existing native claim/receipt/recovery and prepared admission protocol.
- [x] Compose the original Python input plan and native scheduler/gateway with
  exact producer/ledger/proof/wiring checks and a fresh-attempt preclaim controller gate.
- [x] Add explicit CLI execution selection and refuse unavailable native config
  before state I/O without fixture fallback; preserve the default fixture path.
- [x] Add 30 inert composition/recovery/CLI cases and independent boundary review.
- [x] Complete final combined regression: 195 distinct cases, including 30 new
  producer cases and the 26-case execution continuation; whole Ruff/compileall/diff
  checks pass. Repeated focused runs are not additional unique cases.
- [x] Complete the integrated single-episode baseline's full CI and independent
  raw/source/tree audit at `main 82191cf`, run `38428650836`.
- [ ] Specify and implement per-episode staging/launch and durable original proof
  association before claiming a complete multi-episode DRS/BRS production CLI.

## P0 — contract and failure semantics

- [x] Freeze the Phase A `PythonProducerBinding` wire against the existing
  runtime/launch/budget schemas and the pure terminal/runtime-observation DTO fields.
- [x] Implement pure exact-shape, bounds, digest, launch fingerprint and path
  validation with no filesystem or subprocess effects. Environment remains the
  existing digest-only intent field until the launch phase adds an allowlist.
- [x] Bind the existing RSI planned deadline and launch limits; reject deadline,
  fingerprint, intent, source/tree and evaluator drift. Controller reservation
  and episode/request consumption remain pending.
- [x] Implement and test pure terminal resume/reconcile rules: retained digest,
  identity/journal/time pins, original deadline, complete known-terminal evidence,
  callback-free exact collection shapes, unsupported publication claims, and optional retained
  admission-attempt anchor identity/fingerprint checks before replay or reconcile.
- [x] Persist one canonical binding sidecar create-only in the producer batch with
  temporary-file/hard-link publication, `0600` regular-file and single-link checks,
  an independently retained digest/stat pin, and pre-I/O retained-pin validation.
- [x] Require the sidecar for Python terminal recovery and re-read it before and after
  native recovery. Missing, replaced, touched, linked, symlinked, permission-drifted,
  or byte-drifted sidecars fail closed; recovery remains read-only and does not create
  a recovery lock or marker.
- [ ] Connect these rules to the complete durable runtime/process/journal recovery matrix
  for missing terminal, interrupted launch, journal mismatch, callback error and cleanup
  uncertainty. The current sidecar/native gate is a prerequisite, not full CPython recovery.
- [x] Bind the retained sidecar pin to the controller's durable RSI checkpoint and make
  checkpoint restore reject a missing or mismatched pin. The controller copies the
  independently retained sidecar identity into the flow checkpoint and revalidates it
  before intent preparation, cached execution reuse, native dispatch, and resume; a
  producer-bound legacy checkpoint fails closed.
- [x] Close initialization and replay recovery hardening: preflight the sidecar before durable
  run creation; retain canonical producer proof/pin in the immutable run request and its
  request digest; reconstruct a missing first checkpoint only from that retained proof with
  original budget/deadline/fingerprints and a revalidated sidecar; reject run/checkpoint proof
  mismatch symmetrically in both terminal and nonterminal states. Compare the latest run proof
  to the earliest ledger run revision, refuse retrofitting an originally unbound run and fail
  closed on pre-fix producer checkpoints without original-run proof. Revalidate checkpoint
  save/no-op, direct episode recovery, terminal settlement/replay, and callback/native-failure
  reconcile at entry and before checkpoint/journal publication, including already-reserved
  branches. Refusal adds no budget consumption or journal and preserves previous durable
  reservations. Focused regression, independent review and PR32 final-source CI are
  complete; this slice is merged in main at `6a912609d3e5e9811bc8dbae77b1df077976afe7`.
- [x] Specify local exact-evaluator admission and atomic publication handoff;
  external producer score remains provenance only.
- [x] Add the provider-free Python admission-handoff DTO, create-only batch record,
  optional journal/evaluation receipt links, and fail-closed synthetic composition tests.
  This is plumbing and evidence binding only; it does not grant runtime or production
  admission authority.
- [x] Add the zero-side-effect provider-free admission composition gate. Reparse the
  binding, sidecar/checkpoint pin, handoff, terminal, runtime observation, native
  receipt, admission plan and optional publication journal from canonical DTO wires;
  bind identity, deadline/limits, brokered receipt and authority pins plus explicit
  caller-supplied detached executable-owner/envelope/material consistency projections;
  refuse drift, unknown cleanup, unsupported protection claims, unbrokered receipts and
  missing independent pins. The result is an audit projection only and always keeps
  `production_admission=false`; it does not independently observe a process/filesystem,
  start a producer, call an evaluator, consume budget or mutate archive/state.
- [x] Re-read canonical handoff bytes and authority links after callbacks and at direct
  staging/commit/terminal/recovery boundaries. Each read checks held directories and
  pre/open/post/named file metadata. Regression covers handoff loss after evaluator return
  with no archive or publication side effect.
- [x] Retain the original handoff file pin from exclusive creation and stable held-FD
  readback; compare complete file stat/raw-byte and batch-directory identity across
  standalone transaction callbacks, staging/commit/unknown boundaries and read-only
  recovery/replay. Require the unchanged complete pin in the immutable prepared journal;
  refuse digest-only adoption, latest-journal retrofit and removal of Python links.
  The frozen contract is in `retained-handoff-file-pin.md`. This is local retained
  evidence and does not protect against coherent rewriting of all trusted anchors.
- [x] Add the provider-free admission-attempt content anchor and standalone transaction
  registration/revalidation. Preserve original fractional limits, register before the
  prepared intent, replay interrupted registration without rewriting, and refuse missing
  anchors for existing prepared intents. This is content consistency, not an original
  anchor inode pin; see `admission-attempt-and-export.md`.
- [x] Require the retained admission-attempt content anchor in independent standalone
  recovery, including resume, published replay and all-rejected acknowledgement. Derive
  expected content from the independently pinned original handoff, reject missing or
  drifted anchors at entry and final return gates, and never recreate evidence during
  recovery. Preserve non-Python journal bytes and behavior; do not add an optional digest
  that permits legacy Python records to bypass this check.
  Re-read the original handoff pin and prepared association after anchor I/O. Local
  validation passes128 focused and796 combined cases without failures/errors/skips;
  independent review has no blocker. Final-source full CI/merge remain required.
- [x] Implement explicit late controller/ledger evidence registration and read-only
  validation under `late-controller-admission.md`. A separate create-only row binds the
  original run request/first record, producer proof, attributed episode/native claim,
  native plan, prepared journal, content anchor and original handoff pin. Keep original
  run/checkpoint/native-plan wires unchanged and `production_admission=false`.
- [x] Atomically pin a late admission row and its optional controller checkpoint
  reference under `durable-admission-reference.md`; require the original reference
  across checkpoint history and ordinary resume/save/direct recovery boundaries.
  Keep existing registration semantics, original request/proof/budget/plan and unpinned
  golden wires unchanged. This explicit pin is not automatic scheduler/runtime wiring.
- [x] Compose publication and read-only recovery with an already pinned controller
  admission under `controller-bound-publication.md`. Require the caller's retained
  record identity, unchanged complete references and original row/files at entry,
  after checkpoint/timeout callbacks and before successful return. Refuse a missing
  ledger without recreating it; preserve prior commit/unknown effects. This explicit
  facade does not create the first pin or adopt in-memory controller state.
- [x] Add an actual first-candidate-move interruption regression: perform the move,
  then inject failure, retain the unknown marker and partial material, and require
  unchanged read-only recovery with no producer/evaluator/retry/repair.
- [x] Add owning-thread DRS first-pin composition under `owning-thread-first-pin.md`.
  Scope the exact active state/head during fresh controller dispatch; after durable
  prepared evidence, pin with the original CAS and acknowledge only the precise
  reference increment. Pin/ack interruption preserves the durable obligation without
  adopting a newer checkpoint. Cover real transaction-to-evaluator boundaries and
  inert provider return through native-result/episode/controller settlement.
- [x] Compose local BRS worker prepared ready/ack under `brs-owner-ready-ack.md`.
  Workers submit canonical original evidence outside controller/observation lock waits;
  the owner pins with captured CAS, acknowledges exact references and saves results
  ordinally. Support one Python child alongside ordinary siblings; refuse nested/recovered
  authority and multiple independent Python children. Preserve durable obligations on
  cancellation or ack failure. The active-wave save refuses unrelated checkpoint drift
  instead of synchronizing or adopting its latest state.
- [x] Connect the separate admission identity at the opt-in local scheduler boundary
  under `late-prepared-scheduler-join.md`. Fingerprint the explicit immutable supplier,
  call it only after retained receipt/output validation, pass the original handoff pin
  to the transaction and pin DRS/BRS authority at its durable prepared notification.
  Revalidate the first record/reference throughout publication and before scheduler
  return. Ordinary native dispatch remains unchanged. This closes local plumbing;
  independently observed sealed-runtime/lifecycle and production acceptance remain below.
- [x] Consume the actual DRS owner's canonical `RSIPythonAdmissionRecord` in the bridge,
  checking its shape, digest and complete descriptor identity before returning its SHA.
  Preserve historical string-hook and BRS digest behavior. Real local controller/CAS,
  prepared transaction and BRS ready/ack tests use inert native/evaluator boundaries.
  Final integrated local evidence is 348 distinct cases, zero failures/errors/skips,
  with whole-source static checks; see `local-wiring-validation.md`. Final-source
  Linux CI and independent audit remain pending.
- [ ] Connect accepted Feature189 sealed CPython and Feature190 owner/lifecycle/runtime
  observations to the handoff, then enable runtime-gated local exact evaluation and atomic
  publication. Until those gates pass, `production_admission` remains false.

## P1 — inert Python process and local adapters

- [ ] Prepare a pinned runtime launch from Feature188/177 sealed/closed-tree material;
  never discover or substitute a host interpreter.
- [ ] Build the local inert Python fixture and bounded broker exchange with real
  runtime observations and fixed negative loader/codec/import cases.
- [x] Connect completed local OpenEvolve wrapper files and Shinka SQLite/source snapshots
  to the existing common adapter under `local-python-producer-export.md`. Require original
  binding/terminal/observation/result and independent pins before source I/O; reuse the
  existing bounded readers and full verifier without launch, evaluation or export writes.
  Actual project lifecycle/campaign acceptance remains a separate runtime task.
- [x] Add the bounded OpenEvolve/Shinka result preflight from
  `bounded-result-preflight.md`: before external-root I/O, reparse the exact
  binding and compare producer id, evaluator fingerprint, producer fingerprint,
  contract digest and optional run-id. Keep the complete final result binding
  verifier after result/material reads. Shinka also requires the fixed `shinka`
  identity and matching caller producer ID before root/SQLite I/O, retaining bound
  run-id normalization. PR82 is merged as `d530f9f`; its local three-suite
  evidence has 60 passes and its final source `6d4fdc2` passed all 15 checks in
  run `38329866982`. The old main run `38331781593` was cancelled, not passed.
  Current main/PR87 acceptance and unresolved independent raw/source/tree audit
  are tracked separately in `../../docs/current-release-backlog.md`.
- [x] Add a pure shared OpenEvolve/Shinka evidence envelope with build/parse/verify,
  retained digest and complete original-binding comparisons. It performs no I/O or
  evaluator call and always keeps `production_admission=false`; actual project
  lifecycle/export wiring remains the preceding open task.
- [x] Add a controller-backed Python admission bridge adapter over the existing DRS and
  BRS pin facades. It reparses the canonical descriptor on every call, requires the BRS
  continuation check, exposes an owner-scope `pin_live` selector, and preserves
  fail-closed identity/digest errors. The adapter is explicit plumbing; automatic native
  scheduler invocation remains the open integration task above.
- [x] Reject callback-bearing nested bridge input, DTO serializer shadows, foreign
  hook scalar types and oversized shapes before serialization or owner-hook access,
  under `admission-bridge-input-shape.md`. Preserve canonical wires and explicit
  DRS/BRS behavior; this does not grant live runtime admission.
- [ ] Reuse Feature190 private owner/native lifecycle, cancellation, reap, FD
  census and terminal evidence. Keep v2 wire/FD schema unchanged.
- [ ] Add focused tests for startup, decoys, output bounds, cancellation,
  deadline, parent loss, restart refusal, resume and source/runtime drift.
- [x] Add focused sidecar tests for round-trip, create-only collision, malformed retained
  pins before workspace I/O, missing/replaced/touched/mode/link drift, binding mutation,
  batch-started refusal and temporary-file cleanup.

## P1 acceptance

- [ ] Run Linux 3.11/3.12/3.13 project regression plus the dedicated pinned
  Python fixture matrix with zero hidden host-runtime substitution.
- [ ] Independently audit runtime inventory, source/resource/native-library
  closure, interpreter identity, ELF/static profile, broker journal and final
  descriptor. Preserve first failure evidence.

## Explicitly P2 / out of scope

- [ ] Remote evaluator and external worker authentication.
- [ ] Multi-host ownership, distributed scheduler, service API and remote
  Shinka/Slurm backend.
- [ ] Model credentials, real OpenEvolve/Shinka campaigns or WebAgent comparison.

## Python scheduler pre-staged input join

- [x] Add immutable cross-domain input context and read-only validator for one retained
  Python sidecar/checkpoint plus native request/memory/launch inputs.
- [x] Add a pure stable plan factory reusing `NativeRSIInputDescriptor` and
  `NativeRSIExecutionPlan`; keep gateway/controller/provider APIs unchanged.
- [x] Cover cross-episode/request/memory/runtime/intent/attestation/deadline drift,
  file replacement/touch/mode/link/symlink/missing and two-read races without writes,
  claims, budget charges, subprocesses or evaluator calls.
- [x] Preserve legacy non-Python native plan behavior and document this as preflight only.

## Bounded local interruption recovery

- [x] Add24 actual local controller/process/publication retained-file interruption
  cases under `python-interruption-matrix.md`, including the final publication window
  after material moves and before terminal persistence.
- [x] Preserve original proof, deadline/budget, uncertain effects and exact durable
  rows/file identities across repeated reopened read-only refusal; prohibit retry/repair.
- [x] Normalize demonstrated durable/staged publication journal parser failures inside
  the existing fixed-code recovery contract; cover missing and malformed journals.
- [x] Retain first failure evidence and add a dedicated24-case CI inventory. This bounded
  fixture matrix does not close the full live scheduler/runtime interruption task.

## P0 — independently pinned runtime observation policy

- [x] Adopt `runtime-observation-contract.md`: separate OS argv, named observed flags
  and the original descriptor's PyConfig argv/orig_argv; preserve existing wires.
- [x] Add one pure comparison using the existing installation parser, independent
  descriptor/version/initialization pins and original binding artifact SHA/size/mode.
- [x] Require that comparison in gate and adapter build/verify; missing pins and
  old argv-token observations refuse, while historical pure parsing stays compatible.
- [x] Migrate composition fixtures to the reviewed static profile and add actual
  frozen-main encoder-to-observation-to-gate/adapter inert compatibility tests.
- [x] Verify wrong/missing/replaced pins, target, mode, flags, argv and callback-free
  zero-effect boundaries with focused tests and independent review.
  Python3.11 focused309 plus disjoint compatibility195 pass; independent Python3.13
  policy74 pass without reviewed source/test drift. Earlier303 replay remains
  evidence of its earlier source. No actual static runtime ran.
- [x] Normalize malformed independent installation-version labels before descriptor
  parsing; six cases verify the fixed refusal across helper/gate/build/verify.
- [x] Verify PR49 final source `87e579a` against completed/success run
  `38198657810` on the original three-version 3-job matrix; merged at `e2537f1`.
- [ ] Verify and retain the independent raw/source/tree audit for that final
  observation-policy source. CI/merge alone do not establish runtime acceptance.
- [ ] Separately define and accept an RSI-capable static installation asset/profile;
  the current argc-one/fixed-main fixture cannot consume native RSI marker inputs.
