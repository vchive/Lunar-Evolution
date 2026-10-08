# Feature191 — Pinned Python producer adapter

Status: Phase A pure binding implemented, 2026-10-09. Priority P1. The
`PythonProducerBinding` DTO/parser now joins already prepared runtime/tree and
launch evidence without I/O. The lifecycle, process launch, runtime observation
and adapter phases remain specification-only; this feature still does not start
a real producer, model, evaluator service or campaign.

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

The implemented Phase A surface is `build_python_producer_binding` and
`parse_python_producer_binding`. It validates canonical nested
`PythonRuntimeManifest`, `PythonRuntimeTreeManifest`, `ProducerLaunchIntent` and
`ProducerLaunchAttestation` DTOs, matches interpreter bytes/stat pins, binds the
existing RSI planned deadline and launch limits, and computes a digest-without-
self-field. It performs no filesystem reads, subprocess calls, budget
consumption, journal creation, or publication. The remaining launch/observe/
settle/resume behavior below is not implemented by this change.

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

1. **Prepare.** Validate exact DTO scalar types and bounded collections. Persist
   a create-only binding containing the external runtime/tree digests, launch
   intent, one-time attestation digest, producer/evaluator identities, request
   and total-wall budgets, and original deadline.
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
5. **Resume.** A completed acknowledged run is read-only and does not relaunch.
   An unknown run first reconciles the retained terminal/journal/runtime evidence
   under the original deadline. Reconcile cannot publish, evaluate again or
   consume a new request budget.

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

This feature is complete only after a dedicated Linux fixture proves the entire
binding and recovery matrix with the accepted 189 image and 190 owner. A passing
descriptor parser, a C producer, a declared runtime manifest, or a Shinka export
alone is not Python adapter acceptance.
