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
- [ ] Connect these rules to durable runtime/process/journal recovery for missing
  terminal, interrupted launch, journal mismatch, callback error and cleanup uncertainty.
- [ ] Specify local exact-evaluator admission and atomic publication handoff;
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
