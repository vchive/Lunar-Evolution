# Reserved-wave serial implementation and acceptance tasks

Status: pure projection/prefix, whole-ledger/original-reservation readers and
preparation exchange have development implementation and focused checks. Natural
serial execution and final acceptance remain open. Governing contract:
[reserved-wave-serial.md](reserved-wave-serial.md).
Ownership/interfaces: [reserved-wave-serial-plan.md](reserved-wave-serial-plan.md).
These tasks form one complete P0 behavior; they do not reopen public native BRS,
production admission, online publication, P1 real runtime/CLI or P2.

## 0. Review the contract before coding

- [x] T00 Agree requirements RW-01..RW-12 and the natural gateway as sole claim
  creator. Confirm ordinary preclaim/running-episode gates under the held lease
  are sufficient; if a concrete gap exists, review a narrowly bounded worker-side
  adjacent-acquisition change before implementing it. Do not silently add detached
  preclaim or cross-thread `_fresh_child_dispatch` authority.
- [x] T01 Assign exclusive files for reserved projection, prefix/lineage,
  controller/serial lifecycle and terminal/policy integration. Agree pure DTO
  inputs and historical-source observations before parallel edits.
- [x] T02 Record clean baseline/source identity in the separate worktree and
  preserve frozen rejected-lifecycle source plus the primary user-owned RSI gap
  report. Do not treat predecessor implementation as final accepted source.

## 1. Parallel implementation lanes

Development checkpoint: five new foundation modules have 239 distinct focused
cases (95 projection, 65 prefix, 19 ledger, 23 reservation, 37 exchange), all pass.
The ledger reader scans all original children including claim-before-fence and
foreign-run admissions; the reservation reader derives the earliest full-budget
checkpoint from the same verified history without dropping trace fields. The
exchange transfers one original preparation/endpoint without execution authority.
These helpers do not complete C01..C09 or D01..D08. Full material observation,
original owner custody, natural provider integration and final matching-platform
acceptance are still required. Development raw/independent reviews are retained in
`rejected-lifecycle-dev-20261018/reserved-wave-a-dev/` under ignored validation.

### A. Original reservation and serial selection — RW-01, RW-02, RW-03, RW-10

- [x] A01 Add bounded immutable reserved-wave projection/selection helpers in
  `rsi_brs_reserved_wave.py`; no ledger, hook, claim or owner side effects.
- [x] A02 Validate original ordered full domain, exact request/M0/plan and complete
  N-intent reservation against original observations. Derive completion cursor
  separately; retain original counters, stage reservations and deadlines.
- [x] A03 Require a contiguous completed prefix and select only the first
  untouched intent. Refuse holes, foreign/duplicate/reordered associations,
  incomplete reservation and any earlier outstanding/unknown state.
- [x] A04 Check original max-eight/total-32 candidates and actual projection/root/
  record/material bounds; count distinct retained files even with equal digests.
- [x] A05 Keep detached successor semantics unchanged and add tests proving its
  charging/preclaim helpers are never called by the pure reserved helper path.

A01..A05 denote the pure helper only. Development covers 95 state-shaped focused
cases, including whole-domain claim-before-fence traces, actual prefix execution
bodies, strict original budget/deadline identity, capacities and no-hook traps.
Published completed episodes retain matching receipts, trace evidence and the
actual attached RSI verifier; actual runner pass/fail/unresolved outcomes stay
settled without replay or implicit memory promotion.
Ruff, compileall and whitespace checks accompany the development evidence.
Complete filesystem/source/terminal custody proof remains with B/integration;
original preparation handover and live serial behavior remain unimplemented by A.

### B. Append lineage and historical proof — RW-08, RW-09, RW-10

- [ ] B01 Implement pure bounded prefix/adjacent-append validation in
  `rsi_brs_lineage_prefix.py`, reusing strict v1/v2 format readers.
- [ ] B02 Preserve ordinal-zero wire compatibility. Use before-v2 for nonzero
  ordinals with independently correct previous-attempt and latest-published
  predecessor links. Keep actual published/rejected outcome descriptors.
- [ ] B03 Bind every historical execution/obligation/terminal/native material to
  original checkpoint heads and exact retained descriptor/snapshot/source pins.
  Require unchanged byte-for-byte completed prefix and adjacent ordinal append.
- [ ] B04 Derive historical poststate from published after snapshots or rejected
  before snapshots. Verify next before snapshot content matches it. Apply current
  live archive/state checks only at current-tail/active gates; never refresh old
  pins from live files or fabricate a one-batch lineage.
- [ ] B05 Add explicit private serial-owner construction with original lease,
  fresh custody, actual running claim and validated prefix. Preserve legacy
  constructor's ordinal-zero strictness. Generalize before/prepared/success and
  C1/P/C2/ready consumers only through this explicit original path.
- [ ] B06 Refuse changed/replaced old material, duplicate journal/candidate
  associations, mismatched attempted/published links and aggregate overflow before
  another publication or claim can occur.

### C. One live owner at a time — RW-04, RW-05, RW-06, RW-07, RW-12

- [ ] C01 Add private serial driver and controller entry. Keep public BRS refusal
  and flags unchanged; do not enable the path solely because max_workers is one.
- [ ] C02 Separate immutable full-wave envelope from fresh selected-child scope.
  Allocate a new channel/mailbox/Future/executor/endpoint/context/handoff/nonce/
  native session for each untouched ordinal. Never reset old custody fields.
- [ ] C03 Hold the original exclusive run lease through dispatch, owner servicing,
  waits and shutdown. Revalidate original source/policy/head/control/deadline
  adjacent to selected worker start, without waits/hooks under the short mutex.
- [ ] C04 Let the natural runner/gateway alone create the selected claim; bind
  its actual plan/running episode/started claim at original mailbox preparation.
  Create no owner checkpoint in that start-to-preparation gap.
- [ ] C05 Compose genuine published success through before/staged/terminal,
  ready/ACK, mailbox, natural terminal result and exact root acceptance. Do not
  substitute the older completed-worker selected-return grant.
- [ ] C06 Compose genuine all-rejected C1/P/C2, pre-arm/ready/ACK, mailbox and
  natural failed result. Keep rejection out of population and memory publication.
- [ ] C07 Close before join, validate cleanup, call the asserted already-held
  reconcile helper, atomically settle one exact execution/fence delta and verify
  full readback. Retire original child authority only afterward. Do not reacquire
  the nonreentrant lease or adopt a latest root on ambiguity.
- [ ] C08 Allocate nothing for the next child until exact readback and live
  retirement complete. Recompute original reserved projection and append proof
  from the newly verified head; retain all earlier custody/evidence.
- [ ] C09 On complete scheduling use existing plan-ordered `_commit_flow` and
  finalization idempotence with M0; known rejected children are never promoted.

### D. Recovery, terminal proof and policy — RW-09, RW-11

- [ ] D01 Generalize private terminal messages/composer/reconcile observations to
  actual ordinal and original prefix, keeping the strict old entry compatible.
  Do not invent a shared replacement outcome wire or reconstruct owner authority.
- [ ] D02 On a fresh lease validate original run/source/policy/M0/full reservation/
  deadline and every completed execution via immutable historical proof. Read-only
  replay performs no solver, claim, result, transaction or root rewrite.
- [ ] D03 Scan the entire original domain for episode/claim/result, material/ref
  and obligation traces. A started claim before mailbox/fence registration must
  block the suffix; absence of a root fence alone cannot mean untouched.
- [ ] D04 Permit explicit locked reconciliation only from complete independent
  original terminal/delivery/callback/cleanup proof to the sole exact root delta.
  Revalidate prefix afterward; no old worker, callback, transaction or claim retry.
- [ ] D05 Fence partial C1/P/C2, ready/ACK/mailbox/native evidence, unknown,
  cancellation/timeout and root ambiguity. New custody requires no original
  durable attempt trace for that intent anywhere in the domain.
- [ ] D06 Handle root-committed/pre-retirement crash through fresh exclusive lease,
  exact root readback and existing independent cleanup proof. Add no persistent
  cursor, retired bit, reconstructed old owner or authority registry.
- [ ] D07 Pin complete new canonical dependency/alias/code graph in original
  persisted BRS policy/fingerprint/checkpoint history before reservation. Refuse
  missing/drifting original pins; do not migrate old runs or adopt later baselines.
  Stay within the unchanged serialized record and other capacity limits.

## 2. Integrated behavior evidence

Each fault fixture must prove the targeted boundary was reached. For every stopped
path record unchanged reservation/M0/deadline, old material and absence of later
child effects, rather than checking an exception alone.

| Test group | Required witnesses | Requirements |
| --- | --- | --- |
| V01 natural outcome pairs | published→published, published→rejected, rejected→published, rejected→rejected, each with genuine local kernels | RW-04..RW-09 |
| V02 three-child mixed history | rejected→published→rejected and/or published→rejected→published; both predecessor axes and historical population validation | RW-08, RW-09 |
| V03 exact budget | Exactly N launch/solver/practice/evaluator/verifier reservations; unchanged through live/resume; max eight and no ninth; original deadline expiry | RW-01, RW-02, RW-10 |
| V04 fresh custody | Distinct objects/nonces/sessions, one claim/result/root per child; old ACK/request/nonce/receipts retained; stale/foreign/duplicate calls refuse | RW-04..RW-07 |
| V05 ordering | No next custody/Future/claim/transaction before exact root readback and live retirement; frozen M0 for all requests | RW-01, RW-03, RW-07 |
| V06 interruption matrix | Start/claim, before/prepared, C1/P/C2, ready/ACK, generated/delivered response, callback, native result, root CAS/readback, retirement, next claim | RW-06, RW-07, RW-11 |
| V07 fresh-controller resume | Settled prefix read-only, untouched suffix fresh, terminal-only explicit reconciliation, claim-before-fence refusal, root-committed/pre-retirement recovery | RW-02, RW-09, RW-11 |
| V08 unknown/drift | Partial/unknown/cancelled/expired evidence blocks suffix; policy/head/source/material drift refuses without retry or latest adoption | RW-03, RW-07, RW-09, RW-11 |
| V09 prefix/capacity negatives | Holes/reorder, duplicate journals/candidates, changed/replaced old pins, bad predecessor links, projection/depth/record/descriptor/snapshot/aggregate limits | RW-03, RW-08..RW-10 |
| V10 finalization and compatibility | All-rejected scheduling complete, no rejection promotion, existing governed plan-order memory flow; ordinal-zero/detached/DRS/provider-free/public refusals | RW-06, RW-12 |

- [ ] V11 Implement and run all V01..V10 integrated witnesses; retain first
  failure logs and boundary-specific durable-state assertions. Fixtures install
  inert hooks before original policy/source capture and do not expose a new
  arbitrary production handler.
- [ ] V12 Run affected focused tests after coherent edits, Ruff over `src tests
  tools`, compileall over the same scope and `git diff --check`. Review imports,
  live versus historical pin use, lock ordering and complete dependency policy.
- [ ] V13 Obtain independent integrated code review; resolve findings before
  freeze. Do not claim isolated helper tests as the whole behavior acceptance.

## 3. Final-source acceptance and delivery

- [ ] F01 Freeze one reviewed source commit/tree after all lane integration.
  Record tracked/source/import identities, installed origin, exact collection
  inventory and regression group/driver commands without PYTHONPATH substitution.
- [ ] F02 Run matching provider-free/inert case inventories on macOS and Linux
  against that exact source; 5090gpu may run CPU tests. Retain raw stdout/stderr,
  XML, setup/driver/leaf exits and tracked-source checks before/after.
- [ ] F03 Obtain independent source/import and raw/XML/exit review, including
  complete case identity/order, no missing/duplicate/skipped cases and unchanged
  source. Earlier snapshots or predecessor evidence do not complete this gate.
- [ ] F04 Run the full required 33-job GitHub CI on the final integration head;
  resolve failures without widening limits, loosening refusal or hiding skips.
- [ ] F05 Root updates implementation/validation/HANDOFF status from actual
  evidence, creates one coherent integration PR, verifies its exact head and
  merges only after required checks pass. Commit/push/PR/main actions are outside
  this design-only drafting assignment.

Completion means V01..V10 behavior plus final-source acceptance and main
integration, while public native BRS/production admission/online publication stay
closed for the later P1 runtime/project/CLI gate. P2 stays deferred.
