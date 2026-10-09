# Tasks

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
  callback-free exact collection shapes and unsupported publication claims.
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
  reservations. Focused regression and independent review are complete; exact-final-source
  CI remains required for merge acceptance.
- [x] Specify local exact-evaluator admission and atomic publication handoff;
  external producer score remains provenance only.

## P1 — inert Python process and local adapters

- [ ] Prepare a pinned runtime launch from Feature177/177 closed-tree material;
  never discover or substitute a host interpreter.
- [ ] Build the local inert Python fixture and bounded broker exchange with real
  runtime observations and fixed negative loader/codec/import cases.
- [ ] Connect OpenEvolve's Python wrapper and Shinka's explicit SQLite/result
  export to the common binding without launching either project automatically.
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
