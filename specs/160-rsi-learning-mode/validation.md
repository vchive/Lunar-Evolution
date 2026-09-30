# Validation: RSI learning mode

This file records the local acceptance boundary. On 2026-09-30 the RSI suite passed **478 tests**,
with no failures or skips (`/tmp/lunar-rsi-next.xml`). The run includes DRS/BRS callback
crash/reconcile, CLI inspect/reconcile/resume, frozen-transfer callback recovery and append-only
unknown receipt failure settlement. Ruff, compileall and `git diff --check` passed.
An isolated export of the staged source also passed all **478 tests**
(`/tmp/lunar-rsi-staged.xml`), Ruff, compilation and an import check of every public API
export. Unrelated, uncommitted producer changes were absent from that source snapshot.
A passing fixture matrix is not evidence that every external worker or callback recovery path has
been implemented.

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
  mutation, and fails closed on timeout, exception or untrusted evidence. It is not an official
  evaluator or a hard process kill boundary.
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
- Memory admission is a separate append-only SQLite control plane. Only a passing episode with a
  verifier receipt can reach candidate state; holdout and baseline regression evidence are required
  before approval/activation, and compatibility drift or revocation makes retrieval fail closed.
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
| Memory admission lifecycle, CAS transitions and promotion/revocation gates | `test_rsi_memory_governance.py` |
| Provider-free no/old/current transfer regression, seen/unseen split, multi-target holdout and contamination gate | `test_rsi_transfer_regression.py` |
| Unified solver adapter lifecycle, budget/deadline and terminal receipt contract | `test_rsi_adapter_contract.py` |
| Failure clustering, capability coverage, hard-negative selection and curriculum replay | `test_rsi_curriculum.py` |
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
  clean-room verifier and memory governance control plane are provider-free building blocks, not
  external authenticity or model-quality evidence.
- Solver→RSI recursive execution and nested budget propagation. Depth/cycle and unknown-retry
  budget primitives must not be described as a completed nested scheduler.
- Real request/token/CPU/GPU/cost accounting. Control-plane reservations are not measured provider
  usage, and frozen transfer fixture success does not prove learning gains.

No WebAgent, remote evaluator or company evaluation platform is required or authorized by this
local validation procedure.
