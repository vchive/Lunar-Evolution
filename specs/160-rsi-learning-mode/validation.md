# Validation: RSI learning mode

## 2026-10-01 Durable solver handoff and active HTTP cancellation

Final stable source/tests local combined regression: **1,875 passed / 4 Darwin platform skips /
0 failures / 0 errors**, 1,879 cases, exit 0, 211.727 seconds. Report:
`/tmp/lunar-worker-recovery-final-20261001.xml`. It covers all RSI, native trusted, producer,
controller transport, trusted bootstrap, process ownership and lifecycle matrix modules. This is
not a full current/archived/frozen runner or Ubuntu matrix run. The earlier 1,878-case combination
passed 1,874 with four skips while the final cancellation-observer elapsed-budget case was being
added; it is retained separately at `/tmp/lunar-worker-recovery-combined-20261001.xml`.

The new durable gateway has 54 local unit cases and three controller integrations: full result
publication interruption recovers DRS without another call/charge; BRS partial restoration blocks
the entire frozen wave before deterministic merge; started-only results never dispatch or recover
success. Scope/request/component/run callable/ledger drift, alias mutation, concurrent invocation,
all result statuses and failure-only reconciliation are covered. Local source fingerprints do not
authenticate an external worker, and the wrapper delegates budget authority to its controller.

Actual native blocked-loopback cancellation has both confirmed and acknowledgement-lost branches.
Both verify the exact HTTP worker was killed/reaped, native group exited, no formal success or
publication was written, and repeated recovery performs no launch/I/O. Lost acknowledgement keeps
the journal active/unknown. Broker cancellation/IPC/HTTP focused suites passed 69 cases on each of
Python 3.11/3.12/3.13. Full final source static Ruff, compileall, branch diff checks and eight local
runtime Python example syntax checks pass. Ubuntu CI now runs these new cases in the early stage
before the complete runner; that final-head matrix remains a separate integration gate.

Only local provider-free fixtures were run. External ownership/source authentication, controller
death recovery, complete egress, official evaluator and real campaign acceptance remain open.

Final 2026-10-01 current-tree inventory: **9,172 passed / 0 failed / 0 errors / 7 skipped**,
covering all **9,179** currently collected cases. The full current-tree run collected 9,178 cases
and passed 9,171 with seven skips in 908.410 seconds
(`/tmp/lunar-current-complete-20261001.xml`). The final added independent-publication-guard case
then passed in 2.169 seconds (`/tmp/lunar-final-publication-guard-20261001.xml`). Exact node-ID
inventory reconciliation found no missing or extra cases; aggregate JUnit is
`/tmp/lunar-current-final-inventory-20261001.xml` (910.579 seconds combined).

Six skips require Linux sealed-memfd/runner capabilities absent on this Darwin host; one requires
a distinct filesystem case alias. No modified local RSI or native scheduler cases were skipped.
The current-tree run does not rerun archived/frozen Git snapshot suites from `tools/run_tests.py`.
Final `ruff check src tests tools`, compileall over those directories and `git diff --check` pass.
After final control composition changes, six affected native suites separately passed 104 cases;
dispatch revalidation/generation/gate/parent reconciliation separately passed 88 cases. The
earlier complete RSI-only run passed 968 cases before dispatch revalidation was added.

Implemented local interfaces and release boundaries are described in `docs/rsi-local-runtime.md`,
HANDOFF and the local SDDs. No WebAgent, remote evaluator, company platform, real model or actual
OpenEvolve/Shinka project campaign was invoked; keys were neither read nor changed.

Latest 2026-10-01 priority regression: **890 passed / 0 failed / 0 skipped in 49.42s**, including
773 RSI cases and 117 producer/native cases (`/tmp/lunar-priority-regression-20261001.xml`).
After that run, three additional alias/corrupt-intent/legacy-v1 approval regression cases passed
in the final campaign/promotion focused run: **43 passed in 0.84s**
(`/tmp/lunar-rsi-campaign-final-20261001.xml`). Final Ruff over `src tests`, compileall and diff
checks pass. Source changes were covered by the combined run; only regression tests were added
after it. See HANDOFF and priority-execution.md for completed local slices and open integrations.

The previous 2026-10-01 RSI baseline passed **584 tests**,
with no failures or skips in 6.17 seconds (`/tmp/lunar-rsi-release-20261001-v2.xml`). It includes
DRS/BRS callback crash/reconcile, CLI inspect/reconcile/resume, frozen-transfer callback recovery,
unknown receipt failure settlement, clean-room admission, policy-bound curriculum replay, transfer
quarantine and controller promotion identity gates. Ruff over `src tests`, compileall and
`git diff --check` passed. The previous 2026-09-30 baseline was 523 tests.
The process-level clean-room fixtures use only local module-level evaluators. This local regression
does not establish an official evaluator, external worker authenticity, real producer campaign or
model end-to-end acceptance, nor prove that every external recovery path has been implemented.

New local composition covers shared parent learning/holdout/unknown accounting, immutable external
reservation replay and terminal history corruption gates; automatic configured generation admission,
explicit inherited lineage and independent authority checkpoints; optional per-episode revalidation,
unknown recovery and quarantine; full Actor clean-room evidence sidecars and claims; explicit
cross-solver unresolved translations and repeated-pass marginal confidence analysis. A real local
native producer now exercises bootstrap, broker, formal receipt, strict output, independent
candidate evaluation, publication, archive/population/delivery and read-only recovery. These local
interfaces are exported from `lunar_evolution` and documented in `docs/rsi-local-runtime.md`.

The final current-tree regression below supersedes older counts above. Official evaluator and
real project campaign acceptance, external worker authenticity/ownership, historical database
delete/rollback protection, remote atomic leases and cross-platform production coverage remain
separate. The optional revalidation policy is a local dispatch gate, not a background scheduler.
Confidence analysis does not establish a real campaign's observation provenance or grant memory
activation.

## Data and authority

- Canonical digests reject duplicate JSON keys, non-finite numbers, unknown fields and changed bytes.
- Contract, evaluator, environment and memory snapshot pins are present in every episode and cannot
  change during resume.
- A solver result with a score but without an intact official evaluator receipt is not authoritative.
- A `fail`, `unresolved`, `timed_out`, `abandoned`, `cancelled` or `unknown` episode cannot create an
  approved memory entry.
- Concurrent commits against one parent snapshot use compare-and-swap; one loses without merging.

## Verifier and transfer

- The local verifier checks request identity, worker outcome and required receipt bindings. The
  provider-free clean-room verifier additionally reopens candidate source/dependencies in an
  isolated temporary workspace, recomputes source/task/evaluator identities, detects workspace
  mutation, and fails closed on timeout, exception or untrusted evidence. The
  `CleanRoomProcessVerifier` fixture adds a daemon `spawn` process with bounded JSON IPC and
  terminate/kill cleanup; this is a local process lifetime boundary, not an OS sandbox, network
  isolation mechanism, official evaluator or external authenticity proof.
- `CleanRoomAdmissionGate` accepts only a `pass` verdict whose episode, source, dependency, task
  input and evaluator digests match caller-owned pins. It appends at most `observed -> verified`,
  replays an identical admission idempotently, rejects identity/provenance conflicts, and does not
  mutate the read-only memory store.
- Actor traces expose bounded public observations rather than private reasoning. Isolation and
  artifact validation by a real verifier remain separate acceptance work.
- Frozen transfer runs with `curriculum_enabled=false` and `memory_write_enabled=false`; an attempted
  write fails closed and leaves the snapshot unchanged.
- Transfer evidence is retained as a receipt and cannot retroactively promote memory. Transfer
  recovery must preserve the original request, snapshot, component fingerprints and budget; a
  published receipt is replayed without a second gateway/verifier/judge invocation.
- DRS/BRS verifier/judge/curriculum and frozen-transfer verifier/judge persist started gates.
  Unknown callbacks stop recovery; dedicated `reconcile_callback` APIs bind observed results to
  original inputs, current components and explicit local evidence, without invoking the callback.
- A published unknown transfer receipt remains in history after worker failure settlement.
  `reconcile_receipt` atomically appends a failed revision and updated checkpoint; original worker
  results are unchanged. No unknown-to-passed promotion is inferred from a caller declaration.
- Controller callback evidence identifies an independent observation receipt. Transfer callback
  evidence instead binds the verifier receipt (or canonical judgment digest). Both are trusted
  local evidence admission, not authentication of an external system; see `callback-recovery.md`.

## Recovery and scheduling

- The v2 journal persists the DRS/BRS plan and launch intents. DRS reconstructs its completed
  target/practice, verifier and memory steps, then may launch the next previously unstarted episode
  from that original plan. A running episode whose result is unknown is never dispatched again.
- Legacy checkpoints without the complete plan recover existing evidence only; they do not infer
  a missing wave or silently start new episodes.
- BRS launches all practices from one frozen wave snapshot and merges pass decisions in deterministic
  ordinal order only after the wave is complete.
- A `running` episode without a result requires recovery; `unknown` requires evidence-bound
  reconciliation. A blocked child prevents the entire wave from merging. Explicit terminal
  reconciliation must be consumable without rewriting the original result envelope.
- Fresh runs and resume share one controller lock. A live run excludes a competing run or resume,
  and repeated terminal resume does not change run history or increase side-effect counts.
- A crash between terminal checkpoint publication and run-head update retains the recorded terminal
  outcome even when the deadline has expired by the time recovery begins.
- Resume recomputes the current solver/actor/verifier/curriculum/judge identities. Supplying the old
  fingerprint from the ledger cannot hide changed component code/configuration.
- Persisted planned/consumed/remaining budgets and the absolute `deadline_unix` survive restart.
  Atomic launch reservations cover solver/evaluator/verifier stages; exhausted budgets stop before
  new work, and replay does not charge the same reservation again.
- Callback reconciliation reserves unknown-retry budget once before publishing the result. A crash
  between reservation and result publication reuses that reservation; invalid schema/evidence/CAS
  cannot charge budget. Evidence may be recorded after deadline without authorizing new work.
- New runs fix `callback_protocol_version=1`. Older uncertain runs lacking started-call evidence
  require migration; old terminal records remain replayable without re-executing callbacks.

## Integration regression

- Compatibility requirement: existing Population, OpenEvolve, Shinka handoff, ordinary
  `MemoryStore`, Feature 044 experiment memory, candidate receipts and recovery tests must remain
  green. This is the compatibility regression requirement, not a claim that those broader suites
  were rerun in this RSI-focused round.
- Mock, Native Population, OpenEvolve fixture and Shinka export fixture can each be invoked through
  `SolverGateway` without gaining direct RSI memory access.
- The adapter contract exposes one lifecycle and receipt vocabulary for those fixtures. Adapter
  capabilities cannot enable direct memory writes; timeout, cancellation and unknown outcomes stay
  terminal and recovery is explicit.
- Failure-driven curriculum accepts a bounded immutable `FailureBoundaryPolicy` for coverage
  preference, hard-negative threshold, cluster budget and novelty. New selection events bind the
  public diagnosis and policy digest; replay repeats cluster choice and all derived selection
  fields rather than trusting recorded reason/coverage/budget. The ledger digest binds policy even
  before any selection. Checkpoint policy drift stops resume; legacy checkpoints without policy
  mean the default v1 configuration and use the historical digest formula only for validation.
  This remains caller-selected local policy, with no real evaluator or automatic scheduler.
- Memory admission is a separate append-only SQLite control plane. Only a passing episode with a
  verifier receipt can reach candidate state; holdout and baseline regression evidence are required
  before approval/activation, and compatibility drift or revocation makes retrieval fail closed.
- `RSILearningController.promote_transfer_regression()` is an explicit provider-free composition
  entry point. It freezes the controller snapshot and parent snapshot, runs the local transfer
  suite once, checks component fingerprints and CAS, then delegates to the promotion adapter for
  `shadow -> approved` and optional `approved -> active`. Replaying a completed promotion on the
  same controller does not rerun the suite or append another governance revision. It is not a
  default scheduler, official evaluator integration, or external producer acceptance.
- Caller fingerprints cannot overwrite observed component identities. The controller checks
  component/snapshot identity at each trial boundary and binds observed pins to the approved
  record's reason in the same CAS append as regression evidence. Changed components or external
  pins stop approved/active replay, including a fresh controller with empty compatibility. Legacy
  unbound approved records require explicit identity migration and cannot be auto-activated.
- Failed-report quarantine binds the report digest in the revocation reason. Passing, tampered,
  snapshot-drifted or stale-CAS reports cannot revoke a record; a manual or different-report
  revocation cannot be mistaken for idempotent replay of this operation.
- Ruff, compileall and focused Feature 160 tests pass without provider credentials or WebAgent.

## Local regression entry points

The provider-free regression command is:

```bash
PYTHONPATH=src:. pytest -q tests/test_rsi_*.py --basetemp /tmp/lunar-rsi-validation
ruff check src/lunar_evolution/rsi_*.py tests/test_rsi_*.py
python -m compileall -q src/lunar_evolution
git diff --check
```

Use a separate temporary directory for each test run. The result above covers the local RSI suite,
including DRS/BRS CLI replay and transfer recovery; it is not a full repository or real-provider run.

| Evidence area | Focused tests |
| --- | --- |
| DRS/BRS result, verified-result, memory publication and paused-run recovery | `test_rsi_durable_flow.py` |
| Immutable result replay, failed/cancelled reconciliation, concurrent resume | `test_rsi_resume_matrix.py`, `test_rsi_resume_reconcile_contract.py` |
| Controller locks, journal hash-chain/CAS and canonical episode boundaries | `test_rsi_checkpoint.py`, `test_rsi_store.py` |
| Fingerprint/config drift and supplied-old-fingerprint rejection | `test_rsi_identity_drift.py`, `test_rsi_fingerprint.py`, `test_rsi_durable_flow.py` |
| Planned/consumed/remaining, deadline, atomic reservation and depth/cycle primitives | `test_rsi_budget.py`, `test_rsi_durable_flow.py` |
| Frozen transfer publication/replay and side-effect recovery gates | `test_rsi_transfer_recovery.py` |
| Callback journal, result admission, CAS/hash-chain and concurrent execution | `test_rsi_callbacks.py` |
| DRS/BRS callback crash, reconcile, budget reservation and old-version migration | `test_rsi_controller_callbacks.py` |
| CLI callback inspection, strict input admission and explicit continuation | `test_rsi_callback_cli.py` |
| Transfer callback/receipt reconciliation and atomic failure settlement | `test_rsi_transfer_reconcile.py` |
| Clean-room source/dependency reopen, evaluator identity and contamination gates | `test_rsi_cleanroom.py` |
| Process clean-room timeout/exception/IPC/child mutation gates | `test_rsi_cleanroom_process.py` |
| Clean-room verdict provenance and idempotent observed-to-verified admission | `test_rsi_cleanroom_admission.py` |
| Memory admission lifecycle, CAS transitions and promotion/revocation gates | `test_rsi_memory_governance.py` |
| Provider-free no/old/current transfer regression, seen/unseen split, multi-target holdout and contamination gate | `test_rsi_transfer_regression.py` |
| Unified solver adapter lifecycle, budget/deadline and terminal receipt contract | `test_rsi_adapter_contract.py` |
| Provider-free usage receipts, unknown fail-closed summaries, CAS/hash-chain and durable reopen | `test_rsi_usage.py` |
| Optional controller/episode solver sidecar, monotonic wall time, concurrent append and replay idempotency | `test_rsi_usage_controller.py` |
| Failure clustering, prerequisite diversity, threshold/cluster budget, policy-bound digest and tamper-resistant deterministic replay | `test_rsi_curriculum.py` |
| Controller custom-policy checkpoint/resume, drift refusal and default-only legacy recovery | `test_rsi_curriculum_resume.py` |
| Transfer report to memory-governance promotion and two-step activation gate | `test_rsi_memory_promotion.py`, `test_rsi_controller_promotion.py` |
| Existing local protocol, actor, CLI and backend fixtures | Remaining `test_rsi_*.py` tests |

The CLI diagnostics only use local fixture solver IDs and persist to `rsi.sqlite3`; they do not
constitute evidence for real OpenEvolve, Shinka, OSWorld, or remote evaluator performance.

## Still outside this acceptance claim

- External authenticity and ownership for callback observations, distributed idempotency and
  evidence-based migration of old uncertain calls without started logs. The local admission APIs
  preserve evidence bindings; they do not establish external exactly-once semantics.
- Admission of independently trusted successful completion after an unknown transfer result.
  This round implements explicit failure settlement only, not unknown-to-passed publication.
- Real producer launch/ownership/heartbeat, cancellation/cleanup and unknown-worker inspection;
  real OpenEvolve/Shinka/native campaigns and provider performance.
- A real Actor environment runner and independently trusted official evaluator; the local
  clean-room verifier, clean-room admission bridge and memory governance control plane are
  provider-free building blocks, not external authenticity or model-quality evidence.
- The controller promotion composition is explicit and caller-driven. Default automatic holdout
  scheduling, real evaluator execution, rollback/quarantine automation and production campaign
  wiring remain outside this acceptance claim.
- Solver→RSI recursive execution and nested budget propagation. Depth/cycle and unknown-retry
  budget primitives must not be described as a completed nested scheduler.
- Real provider billing, GPU measurement and external cost truth. The provider-free usage ledger
  records local receipts and configurable estimates; control-plane reservations are not measured
  provider usage, and frozen transfer fixture success does not prove learning gains. A crash after
  a solver side effect but before its optional usage append can leave a missing receipt; replay
  remains side-effect safe but cannot claim distributed exactly-once accounting or reconstruct the
  missing monotonic duration.

No WebAgent, remote evaluator or company evaluation platform is required or authorized by this
local validation procedure.
