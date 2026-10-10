# Feature191 local exact-evaluator admission handoff

Status: production admission design plus implemented provider-free handoff/composition
contracts. These contracts do not claim Python runtime admission. The production path
may be enabled only after the Feature189/190 runtime gates below are accepted.
The existing sidecar, RSI checkpoint binding, native receipt/journal, local exact
evaluator, and atomic publication code are the sources of truth.

## Purpose and boundary

Feature191 currently provides a canonical `PythonProducerBinding`, a create-only
`python-producer-binding.json` sidecar, controller durable producer proof,
read-only terminal recovery, and a pure static observation adapter. Those surfaces
are evidence contracts. A DTO, parsed stdout record, process exit code, external
producer score, SQLite row, or receipt-shaped fixture cannot by itself authorize
evaluation or publication.

This slice defines one explicit local admission handoff:

```
retained Python binding/sidecar
  -> verified runtime/process/journal evidence
  -> verified producer envelope
  -> local exact evaluator
  -> evaluation receipt
  -> existing atomic publication transaction
```

The handoff is local and single-host. It does not add a remote evaluator, service API,
multi-host ownership, distributed scheduler, external authentication, cluster launcher,
model provider, or automatic OpenEvolve/Shinka execution. OpenEvolve and Shinka remain
untrusted material producers; their scores and lineage are provenance only.

The handoff must have two deliberately separate operations:

- **prepare/reconcile**: read-only evidence inspection and durable recovery. It never
  evaluates, publishes, retries, relaunches, consumes a new request budget, or refreshes
  a deadline.
- **admit/publish**: an explicit caller-selected operation that performs the local exact
  evaluation and, only for valid results, invokes the existing atomic publication
  transaction.

No API may infer admission from a successful `PythonProducerTerminal`,
`PythonProducerRuntimeObservation`, `ProducerResultEnvelope`, or external score.

## Preconditions

Production acceptance is blocked until all of these are independently evidenced:

1. Feature189 supplies one accepted sealed/static CPython target: actual acquisition and
   signature/provenance, safe staging, configured/static closure, frozen startup inputs,
   ELF/link/size audit, and the real startup/loader-negative fixture.
2. Feature190 supplies the accepted private original executable owner and native lifecycle
   proof, including release, guardian, cleanup, deadline, and recovery behavior.
3. Feature188/177 closed-tree and sealed material are accepted for the exact target.
4. Feature160 durable RSI state and the native v2 process/broker/journal lifecycle remain
   unchanged and available.
5. The local exact evaluator and candidate output contract are configured by the caller
   with stable contract, evaluator, runner, dependency, and environment fingerprints.

Until those gates pass, only inert local fixtures may exercise this handoff. A parser,
sidecar round-trip, declared runtime manifest, C/native fixture, Shinka export, or
DTO-only test cannot set `runtime_load_protection`, `production_admission`, or
`general_code_origin_protection` to true and cannot be used as release evidence.

## Frozen handoff inputs

The implementation must accept the already existing objects and retained files; it must
not create a parallel binding or budget schema.

### Immutable authority

- canonical `PythonProducerBinding` bytes and `binding_sha256`;
- independently retained sidecar stat/digest pin and exact sidecar bytes;
- RSI run request and controller checkpoint `producer_checkpoint_binding`;
- `ProducerLaunchIntent`, one-time attestation digest, parent/task/run IDs;
- contract, evaluator, runner, dependency, and environment SHA-256 pins;
- request/output/wall-clock budgets and the original absolute deadline;
- Feature189 runtime manifest/tree and Feature190 executable-owner/target pins.

### Observed evidence

The gate must read and validate, from durable native materials rather than caller claims:

- native process registration, owner, target execution binding, ready/release/terminal state;
- original start/release/exit timestamps, exit/signal and cleanup result;
- broker request journal and complete response transcript;
- bounded stdout/stderr and producer envelope identity/bytes/stat pins;
- Python runtime observation emitted by the running sealed fixture, including version,
  cache tag, startup flags/module origins, fixed `sys.path`, broker transcript digest,
  pycache absence and fixed computation digest;
- source/material paths and SHA-256 values referenced by the envelope.

The observation adapter may validate shape and canonical bytes, but the caller must supply
independent transcript, filesystem and process evidence. The child record cannot self-attest
those facts.

The current provider-free helper, `verify_python_producer_admission_gate`, is intentionally
smaller than this production boundary. It reparses the retained DTO wires and checks digest,
identity, deadline, authority, terminal and journal coherence in memory. Its executable-owner,
envelope-evidence and material inputs are caller-supplied detached consistency projections; it
does not read their source files, inspect a process, invoke an evaluator, or mutate a journal.
Passing this helper therefore records only local evidence consistency and cannot satisfy the
independent Feature189/190 observations required for production admission.

The generic envelope's canonical `envelope_sha256` is distinct from the SHA-256 of raw
output-file bytes (`envelope_evidence_sha256`). Material descriptors are canonically hashed
from the envelope. The broker's `wall_deadline_ns` uses monotonic time; callers retain it
separately as `broker_deadline_monotonic_ns`. The helper compares the original pin exactly
and never derives it from `deadline_unix` or samples a clock during resume.

### Plan/contract authority

The admission plan is reconstructed from the frozen local contract and the verified material.
The local evaluator is the only score/validity authority. External `score`, `correct`,
`generation`, `rank`, feedback and SQLite fields are copied only as bounded provenance.

## Required durable output and digest associations

The handoff must persist one canonical, create-only handoff record in the existing
producer batch before evaluation. The exact wire is a future implementation detail, but
it must contain these associations and no credentials:

```
protocol/schema
run_id, journal_id, parent_task_id, task_id
binding_sha256
sidecar raw_sha256 + retained stat pin digest
launch intent/attestation digest
runtime manifest/tree and executable-owner digests
native execution-receipt digest
terminal digest and runtime-observation digest
broker transcript, envelope and material digests
contract/evaluator/runner/dependency/environment pins
admission-plan digest
request/wall budget and original deadline
state: prepared | evaluating | staged | unknown | published | rejected
handoff_sha256
```

The handoff digest is a digest of canonical bytes excluding its own digest. Every later
journal/receipt must carry or immutably reference it:

- the producer-bundle publication journal records `python_handoff_sha256` when this
  Feature191 path is used;
- the evaluation receipt binds handoff, admission-plan, candidate source, execution and
  local evaluator receipt digests;
- the publication manifest/terminal marker binds the same journal and state-after digests.

Legacy non-Python journals remain byte-compatible and omit the optional field. Omitting
the handoff field is permitted only for legacy/non-Python callers; a Python admission
attempt must fail closed if the field is absent or mismatched.

## Admission call chain

The implementation should compose existing code rather than duplicate evaluator or
publication logic:

1. Revalidate the RSI run/checkpoint producer proof and live sidecar before any new
   material read.
2. Reconcile the native process/receipt/journal and Python runtime observation
   read-only under the original deadline. Reject unknown, missing, drifted, or cleanup
   uncertain evidence.
3. Parse and revalidate the producer envelope and all referenced source/material bytes.
4. Persist the immutable `prepared` handoff and verify its digest/read-back.
5. Call the existing `admit_producer_envelope` or equivalent local exact-evaluator
   path with the frozen evaluator/contract authority. Do not use the producer score.
6. Bind the resulting authoritative evaluation receipt to the handoff and candidate
   source/execution digests.
7. If candidates are valid, call
   `run_native_producer_bundle_publication_transaction` with the existing population
   window, `native_execution_receipt_sha256`, and a continuation guard. The transaction
   must perform its existing preflight, non-publishing evaluation/read-back, stage,
   marker, commit, and archive/state read-back.
8. Persist the terminal handoff projection and return the existing publication result.
   Re-read all handoff/receipt/journal bytes before acknowledging success.

The Python entry point must require a formal native execution receipt and a verified
runtime observation. It may not obtain publication authority by passing
`native_execution_receipt_sha256=None`, by calling a generic DTO projection, or by
directly writing archive/state files.

## Check boundaries and budget rules

The same retained evidence must be checked at each boundary:

- before handoff creation;
- before local evaluator invocation;
- after every evaluator callback;
- before staging;
- while entering the publication lock;
- after stage verification and before the first commit move;
- after archive/state read-back;
- before terminal acknowledgement and during replay.

Checks compare canonical bytes, all digest/stat/inode pins, authority fields, journal
identity, candidate mapping and the original absolute deadline. Any refusal preserves the
primary fixed error and does not replace it with provider text.

The controller owns the request and total-wall budgets. The handoff cannot replenish,
split, or refresh either budget. A shorter caller deadline may narrow the same monotonic
deadline; a new deadline on restart is invalid. Reconcile is budget-free and cannot
consume a new solver/evaluator request.

## Unknown critical region and recovery

Before the first publication target move, cancellation or a failed evidence check stops
the operation and leaves a recoverable prepared/staged record. Once the existing commit
routine writes its durable `unknown` marker and begins the first target move, the
critical region is terminal: cancellation, owner loss, or a late budget signal cannot
claim failure or start a retry. The marker and journal remain the only recovery authority.

Recovery must:

- inspect the exact handoff, journal, manifest, marker, receipts, source bytes and
  archive/state prefix;
- fail closed on any missing, changed, replaced, symlinked, or mismatched material;
- return a published/failed/unknown decision without launching a producer or evaluator;
- never create a new recovery lock/marker, consume attestation, refresh a deadline, or
  publish a second time.

An unknown Python handoff is not publication eligible. Only complete durable publication
evidence may resolve it to published; otherwise it remains an explicit recovery refusal.

## Replay semantics

A published handoff replay is read-only. It revalidates the handoff digest, sidecar,
runtime/terminal observation, native receipt, envelope, evaluation receipt, publication
journal, terminal marker, archive and state digests, and candidate/source identity.
It returns the retained result without re-running the evaluator, producer, or publication
transaction.

A prepared/evaluating/staged handoff is not replay success. It is either resumed by the
existing exact recovery path when all stage evidence is complete, or returned as an
explicit recovery-required/unknown refusal. A missing first controller checkpoint uses
the already retained RSI run request proof; it never infers a provider-free run from a
missing checkpoint.

## Minimal inert validation matrix

This SDD requires tests before production claims. Tests use local fixtures only and must
not invoke WebAgent, remote evaluators, credentials, host Python substitution or real
OpenEvolve/Shinka campaigns.

### Admission refusal tests

- DTO/receipt/runtime observation with completed/exit-0 claims but no independent runtime
  timestamps, transcript, owner, cleanup or evaluator receipt remains ineligible.
- Missing, replaced, touched, linked, symlinked or byte-drifted sidecar fails before any
  evaluation, publication, callback or budget consumption.
- Run/checkpoint/handoff binding, contract, evaluator, runner, source, envelope, budget,
  deadline or runtime pin drift fails closed.
- Producer external score differs from local evaluator result: local result remains
  authoritative.
- Python path with omitted formal native receipt or omitted handoff digest is rejected.
- Existing evolved population, seed admission, duplicate journal, or non-zero iteration
  refuses before evaluator/publication.

### Successful inert composition

- A synthetic, fully pinned handoff reaches the existing local evaluator and records its
  authoritative receipt, with no producer execution.
- One valid and one invalid candidate use the existing transaction; only the valid local
  result is staged and published, with archive/state read-back matching the expected digests.
- All candidates rejected writes the terminal rejected journal and leaves archive/state
  unchanged.
- Cancellation before stage leaves no visible publication; cancellation after stage
  is handled by the existing marker/unknown rules.
- A forced failure after the first target move preserves the unknown marker and recovery
  refuses to retry or re-evaluate.
- Exact retry/replay reuses retained evidence and performs zero producer/evaluator calls.
- Mutation of any handoff, sidecar, receipt, runtime observation, envelope, journal,
  marker, archive or state file is rejected before returning success.

Each test must assert call counts and durable file snapshots. Passing these tests proves
only
local composition and fail-closed semantics with inert evidence; it does not satisfy
Feature189/190 runtime acceptance.

## Explicit non-goals

This handoff does not:

- run or authenticate external workers;
- add remote or network evaluators;
- distribute ownership across hosts;
- provide a service or scheduler API;
- infer Python code origin from filenames or producer metadata;
- enable generic arbitrary Python;
- turn OpenEvolve/Shinka scores into Lunar scores;
- assert sandboxing, runtime load protection, production admission or general code-origin
  protection without the independent sealed-runtime evidence.

## Proposed implementation slice

After this SDD is accepted, the smallest implementation should be:

1. Add a Python-specific handoff DTO/parser and create-only persistence helper.
2. Add a gate that joins existing sidecar/checkpoint, native receipt/runtime observation,
   envelope and authority digests before evaluator invocation.
3. Add an explicit composition function that delegates to
   `admit_producer_envelope` and `run_native_producer_bundle_publication_transaction`.
4. Add terminal/replay projection and focused inert tests for the matrix above.
5. Extend the publication journal with one optional Python handoff digest while retaining
   legacy canonical bytes.
6. Run focused tests, ruff, compileall and diff check. Do not update production/runtime
   acceptance status until Feature189/190 gates and exact Linux evidence are independently
   complete.
