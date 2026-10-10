# Feature191 — Pinned Python producer adapter

Status: Phase A binding, durable binding sidecar, controller checkpoint binding, and read-only
recovery gate implemented; initialization/replay recovery hardening is complete against local
provider-free fixtures and under final-source CI validation,
2026-10-10. Priority P1. The `PythonProducerBinding` DTO/parser joins already prepared
runtime/tree and launch evidence without I/O. The binding can now be persisted once in the
batch as `python-producer-binding.json`; recovery requires the independently retained sidecar
pin and rechecks it before and after native process recovery. The immutable RSI run request is
the earliest durable producer-proof anchor, and controller checkpoints must retain the same
proof and fail closed on missing or drifted producer evidence. Pure terminal/runtime-observation
DTOs and terminal resume/reconcile rules remain provider-free contracts. This slice does not
start a real producer or CPython runtime, authenticate child observations, run an evaluator
service, or launch an OpenEvolve/Shinka campaign.

## Problem and outcome

The repository already has two useful but separate boundaries. The OpenEvolve
path can compose a native local process and pass one candidate through the local
exact evaluator. The Shinka path can read a quiescent SQLite result directory and
export explicitly selected programs. The Python runtime inventory and closed-tree
checks describe declared files, but they do not prove that a later process uses
the pinned interpreter, loader, standard library, packages, project sources and
resources. A Python adapter must join these contracts without treating an
external score, generation, database row, or completed process claim as Lunar
authority.

The result is one explicit, local, bounded `PythonProducerBinding` that names a
caller-selected interpreter and closed runtime material, an original launch
intent/attestation, a host-only broker and one absolute deadline. Running it
produces a durable process terminal record and a bounded `ProducerResultEnvelope`.
The envelope still goes through `admit_producer_result` and the local exact
evaluator before it can become a candidate or a published seed.

## Scope

- Accept an already prepared `PythonRuntimeManifest` and
  `ClosedPythonRuntimeTree` with independently retained digests and target
  identity. Do not scan a host installation, follow a symlinked interpreter,
  infer imports, run `pip`, run `ldd`, or replace missing files with the current
  Python.
- Bind one exact interpreter path, argv, environment allowlist, working/output
  directories, producer fingerprint, contract/evaluator fingerprints, request
  limits and original absolute wall-clock deadline.
- Reuse the existing native lifecycle, guardian, broker pipes, request journal,
  cancellation, process terminal and cleanup evidence. No new inherited FD,
  control protocol, bundle selector or public numeric-FD authority is added.
- Persist one create-only canonical binding sidecar in the existing producer batch. The sidecar
  is a regular `0600` single-link file with a bounded size synchronized to the binding parser
  (2 MiB), and carries an independently retained digest/stat pin for recovery.
- Treat the sidecar as a durable precondition for Python terminal recovery. Read-only recovery
  checks the sidecar before native inspection and again afterwards; missing, replaced, touched,
  hard-linked, symlinked, permission-drifted, or byte-drifted evidence is refused.
- Validate the sidecar before creating a durable RSI run. Include the canonical producer proof
  and retained pin in the immutable run request and its request digest, then copy that exact
  proof into every controller checkpoint. A crash before the first checkpoint cannot erase the
  run's producer-bound identity or downgrade it to a provider-free run.
- Record real interpreter version/cache tag, startup flags, module origins,
  broker exchange and output material from the running process. C or parent code
  must not fabricate Python observations.
- Keep OpenEvolve and Shinka data untrusted. Their score, `correct`, `generation`,
  rank, feedback and SQLite metadata remain bounded provenance only.

## Non-goals

There is no remote evaluator, distributed scheduler, multi-host ownership,
service API, Slurm/cluster launcher, model provider, Python sandbox claim,
general code-origin guarantee, arbitrary Python admission, or automatic real
OpenEvolve/Shinka campaign. P2 service/ownership/distributed work remains a
separate feature. This adapter does not make `runtime_load_protection`,
`production_admission`, or `general_code_origin_protection` true.

## Current implementation boundary

The implemented Phase A surface includes `build_python_producer_binding` and
`parse_python_producer_binding`, `persist_python_producer_binding`,
`read_python_producer_binding_sidecar`, and the sidecar-aware
`recover_python_producer_terminal` facade. Binding construction still performs no filesystem
reads, subprocess calls, budget consumption, journal creation, or publication. Persistence
validates and reparses the canonical binding before opening the batch, serializes one create-only
sidecar under the existing recovery lock, publishes it through a temporary file and hard-link,
then retains the post-publication single-link stat pin. Reads validate the caller-retained pin
before workspace I/O, check the sidecar identity before/during/after reading, reparse the exact
canonical bytes, and reject any digest or stat drift. The native recovery facade remains
read-only, does not create a recovery lock/marker, and performs the sidecar check on both sides
of native inspection. The launch-input not-started gate allows this sidecar to remain only during
the final binding validation; a fresh prepare/bind pass still treats it as started. The current
Feature191 addition is provider-free handoff plumbing: a canonical create-only handoff DTO,
receipt/journal digest links, and synthetic transaction/recovery checks. It does not itself
establish runtime/process observation or publication authority. Actual launch/observe/settle,
sealed CPython evidence, and runtime-gated publication admission remain open.

The standalone admission path additionally retains an original write-derived handoff file
pin as specified in [retained-handoff-file-pin.md](retained-handoff-file-pin.md). Protected
transactions require that pin, carry it unchanged in the immutable prepared journal and
later projections, and revalidate file identity across callbacks and recovery. Digest-only
legacy Python journals remain inspection records; they cannot silently adopt current
filesystem metadata. Non-Python journal bytes stay compatible. A future controller
admission flow needs its own original admission-attempt anchor; this slice does not
retroactively change the earlier producer binding/run proof.

## Preconditions and safety gates

Feature189's accepted Linux static CPython fixture and Feature190's accepted
private original executable owner are prerequisites for a production sealed
target run. Until both are accepted, this feature may use only inert local
process fixtures to validate protocol and recovery; it must not call a host
Python executable as a substitute. Feature188 sealed material, Feature177
closed-tree evidence, Feature160 durable RSI state, the native v2 lifecycle and
the local exact evaluator remain unchanged prerequisites.

Admission fails before spawn, budget consumption, nonce use, broker journal
creation or output writes when any original source/manifest/tree/artifact,
interpreter, argv, environment, contract, evaluator, producer, task, deadline
or runtime fingerprint differs. A missing terminal or interrupted child is
`unknown` and requires read-only reconcile. It is never converted to success,
retried, or given a refreshed budget from absence of evidence.

## Required behavior

1. **Prepare.** Validate exact DTO scalar types and bounded collections. Persist a create-only
   binding sidecar containing the external runtime/tree digests, launch intent, one-time
   attestation digest, producer/evaluator identities, request and total-wall budgets, and
   original deadline. The sidecar is limited to the binding parser's 2 MiB bound and its
   retained file pin is held independently by the controller. Before creating the durable RSI
   run, preflight that retained proof against the live sidecar. Store the canonical proof/pin
   in the immutable run request and include it in `request_sha256`; constructing the first
   flow checkpoint is not the first durable binding boundary.
2. **Launch.** Recheck all pins and no-follow runtime identities immediately
   before native release. Pass only an allowlisted environment and the fixed
   broker FD variables. The Python process receives a fixed fixture/protocol
   case, never a caller-selected module, path, `-c`, `-m`, source or code string.
3. **Observe.** Require actual CPython version/ABI/cache tag, `-I -S -B` policy,
   empty or fixed `sys.path`, no pycache, bounded stdout/stderr, one broker
   request/response and one result envelope. Verify readable decoys are refused
   by patched loader routes, not merely by filesystem denial.
4. **Settle.** Record exit, signal/cancellation, deadline, cleanup and request
   journal identities. Only a verified exit-0 terminal plus a valid envelope can
   enter local exact evaluation. Nonzero, cancellation, deadline, drift and
   cleanup uncertainty remain failed/unknown according to the existing lifecycle.
5. **Resume.** A completed acknowledged run is read-only and does not relaunch. An unknown run
   first validates the retained sidecar, then reconciles the retained terminal/journal/runtime
   evidence under the original deadline, and finally validates the sidecar again. Reconcile
   cannot publish, evaluate again, create a recovery lock/marker, or consume a new request budget.
   A missing sidecar or any sidecar binding/stat drift remains a refusal.
6. **Controller recovery.** Validate the immutable run proof and live sidecar before restoring
   or reconstructing a flow. Read the earliest ledger run revision and require the latest run
   proof to equal that original proof; adding, removing or replacing a proof is drift. If the
   first checkpoint is absent, reconstruct only from the
   retained run request, preserving its original budget/deadline, fingerprints and producer
   proof. A valid independently retained sidecar is still required; omission cannot turn the
   run into a provider-free run. An originally unbound run cannot acquire a producer sidecar
   during missing-checkpoint reconstruction. A present checkpoint must carry exactly the
   run's producer proof, with symmetric equality for terminal and nonterminal states. A
   pre-fix producer checkpoint lacking proof in the original run request fails closed; there
   is no inferred migration from a checkpoint or current sidecar. Revalidate before intent
   preparation, cached execution reuse, native
   dispatch, direct episode recovery, checkpoint save (including an identical/no-op save), and
   terminal settlement or replay. Callback reconcile and native failure reconcile also validate
   on entry and immediately before publishing reconciliation checkpoint/journal state, including
   branches with a previously reserved budget. Refusal cannot add budget consumption or append
   a checkpoint/journal, invoke callbacks, dispatch, or mutate terminal state. A reservation
   already durable before the failed check is preserved; refusal does not roll it back.

## OpenEvolve and Shinka boundary

OpenEvolve's Python wrapper is one producer implementation of this binding. Its
config and result files are pinned by bytes and identity, and its external score
is copied only as digest-only provenance. Shinka's adapter reads an explicit,
quiescent SQLite export or a prepared result directory; program IDs are caller
selected and source bytes are rehashed. No adapter starts Shinka, interprets its
generation as a Lunar iteration, or promotes `correct`/`combined_score` without
the local exact evaluator. Both adapters share the same binding, terminal,
unknown-reconcile and result-envelope contracts.

## Acceptance boundary

The durable sidecar, immutable run-request anchor, controller recovery boundaries, and
provider-free handoff/receipt plumbing are complete as local slices. Focused regression and
independent boundary review pass locally; exact-final-source CI remains required before merge
acceptance. Runtime-gated Python admission is still open.
Feature acceptance still requires a dedicated Linux fixture proving the entire binding and
recovery matrix with the accepted 189 image and 190 owner, including real CPython observations,
loader-negative behavior, broker evidence, lifecycle timestamps and evaluator admission. A
passing descriptor parser, sidecar round-trip, C producer, declared runtime manifest, or a
Shinka export alone is not Python adapter acceptance.
