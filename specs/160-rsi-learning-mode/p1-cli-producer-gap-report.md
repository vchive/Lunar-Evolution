# P1 CLI / local producer composition gap report

Date: 2026-10-12
Baseline: PR59 `a6a8eb262a9ef79a6468e02f4d5c158afaf718a3`
Scope: provider-free local inspection only; no model, WebAgent, remote evaluator, or real
OpenEvolve/Shinka campaign was run.

Current correction, 2026-10-13: the retained `rsi replay` inspector, replay gateway
and durable `rsi resume` CLI are implemented and merged. PR64's integrated source
passed 15 checks; later replay-context changes from PR73 keep their original failed
CI evidence and must not borrow that older acceptance. The latest integration and
raw/source/tree obligations are tracked in
[`../../docs/current-release-backlog.md`](../../docs/current-release-backlog.md).
The open P1 development is the local retained result/exporter join and subsequent
runtime-gated producer CLI acceptance, not another replay/result DTO.
`production_admission=false`.

## Finding

The RSI CLI accepts `--solver openevolve` and `--solver shinka`, but those values currently
select the deterministic `fixture_solver_gateway` in `cli._rsi_run_payload`. They preserve the
solver ID as provenance and exercise controller/ledger/recovery contracts, but they do not launch
or inspect a local producer. A successful command therefore proves only the provider-free RSI
controller fixture, not a producer-backed RSI episode.

The existing local producer paths are separate:

- `evolve --strategy openevolve` can run an explicitly supplied local command and evaluator.
- `export-shinka-result` reads a completed Shinka SQLite result and writes a verified
  `ProducerResultEnvelope` for population warm start.
- `rsi_native_gateway` / `rsi_native_scheduler` compose a programmatic local native gateway,
  but there is no production CLI entry that stages the request and invokes that composition.
- `rsi inspect` and `rsi reconcile` inspect the RSI ledger, while candidate-bundle inspection
  commands inspect candidate evidence; neither provides one read-only replay from a retained
  producer result into a `SolverResult` bound to an RSI episode.

This is a real P1 wiring gap. It is not a missing DTO or a reason to add another solver-result
schema.

## Reproduction evidence

From a clean PR59 worktree, the following local commands both returned `status: completed`:

```bash
PYTHONPATH=src python -m lunar_evolution rsi run contract.json \
  --solver openevolve --run-id audit-openevolve --home home-openevolve --json
PYTHONPATH=src python -m lunar_evolution rsi run contract.json \
  --solver shinka --run-id audit-shinka --home home-shinka --json
```

Both runs created the RSI SQLite ledger and controller state. Neither run created a producer
launch directory, producer input/config, native lifecycle receipt, candidate receipt, evaluator
receipt, publication receipt, or producer export. The implementation path resolves to:

```text
_rsi_run_payload
  -> fixture_solver_gateway(args.solver, ...)
  -> RSILearningController(...)
  -> controller.run_drs/run_brs
```

The command's success is therefore intentionally provider-free fixture evidence and must not be
reported as local OpenEvolve/Shinka runtime acceptance.

## Implemented retained replay slice

The following explicit **read-only producer replay / dry-run inspection** composition
is implemented using existing contracts; it is not a new development request:

1. Accept a retained `ProducerResultEnvelope` directory plus the original RSI run/episode pins.
2. Reuse `prepare_producer_seed_manifest`, existing producer admission, and the existing
   `SolverRequest`/`SolverResult` mapper (or `NativeRSISolverGateway` receipt mapper) rather than
   defining a second result DTO.
3. Verify contract/evaluator/environment/memory/producer fingerprints and all retained candidate,
   execution, evaluation, and publication receipts before producing a result.
4. Persist nothing and launch nothing in dry-run/replay mode; emit a bounded report stating
   `completed`, `unknown`, `drifted`, or `recovery_required` and the exact reason code.
5. Add a separate opt-in local execution path only after this read-only path is accepted. That
   path should call the existing native scheduler and retain its durable claim/receipt semantics;
   it must not call the fixture gateway when a producer-backed mode is selected.

Suggested CLI shape (names are provisional and should be fixed in an SDD before coding):

```text
lunar-evolution rsi replay <producer-export-dir> \
  --contract <contract.json> --request <request.json> \
  --memory-snapshot <snapshot.json> --receipts <native-receipts.json> \
  --solver openevolve --producer-fingerprint <digest> \
  --contract-sha256 <digest> --request-sha256 <digest> \
  --memory-sha256 <digest> --receipts-sha256 <digest> \
  --envelope-sha256 <digest> --materials-sha256 <digest> --json
```

The provider-free slice now exposes `rsi replay` with this retained evidence shape. The command
requires byte pins for the contract, request, memory snapshot, producer envelope, producer
material descriptors, and native receipt bundle. The material pin is the canonical digest of the
generic envelope's material records, exposed by `producer_materials_sha256`; it is independent of
the raw envelope-byte pin and catches descriptor drift before receipt mapping. The receipt bundle is a plain wire projection of existing
`NativeCandidateRecord`, `NativeExecutionReceipt`, `NativeEvaluationReceipt`,
`NativePublicationReceipt`, and `OfficialEvaluationReceipt` records; no parallel result DTO is
introduced. It reads all files with no-follow bounded descriptors, rechecks their identities, and
does not initialize the controller home or SQLite ledger. Missing `worker_terminal_status` is
reported as `unknown`; incomplete or drifted receipts cannot become `completed`.

Known receipt records may be omitted or explicitly `null`; both mean missing evidence and return
`unknown`. Unexpected bundle keys or malformed present records remain `drifted`, even when another
record is missing. A valid identity-bound envelope with `status: unknown`, or a missing material
file, also returns `unknown`; failed/cancelled envelope claims and identity drift remain refused.
Before returning either a complete or incomplete comparison, the command re-opens observed files
and candidate sources through the no-follow boundary and checks retained bytes/digests and inode
metadata. This catches replacement of the producer root by a symlink and source byte/inode drift;
it is a bounded sequence of observations, not a multi-file atomic snapshot.

Top-level `request_sha256` always retains the caller's original request-file byte pin.
`solver_request_sha256` separately exposes the canonical `SolverRequest.digest()` when the
request is parsed. Pretty-printed JSON can therefore have different byte and canonical digests
without losing the original evidence pin. The result's existing request binding stays canonical.

The existing `rsi run --solver openevolve|shinka` remains the provider-free controller fixture,
but its JSON now states `solver_execution: provider_free_fixture`,
`production_admission: false`, and `warning: rsi_producer_replay_required`. It is therefore not
silently reported as a producer campaign. A later `rsi producer-run` command can own the real
local native lifecycle, but that is a separate acceptance slice.

## Acceptance tests for the slice

- Matching retained Shinka/OpenEvolve fixture material maps to one bound `SolverResult` without
  spawning a process, evaluator, or producer.
- Replaying the same retained export is byte/read-only and has no ledger or filesystem writes.
- Contract, evaluator, environment, memory, producer identity, candidate, execution, evaluation,
  publication, source bytes, or inode drift returns a fixed `drifted`/`recovery_required` result
  before any side effect.
- Missing terminal/evaluation/publication evidence is `unknown`; a producer score alone never
  becomes `completed`.
- CLI output distinguishes fixture controller runs from producer-backed replay and reports the
  retained evidence digests.
- Existing `rsi run --solver openevolve|shinka`, `evolve`, `export-shinka-result`, native gateway
  tests, and read-only usage diagnostics remain unchanged.

Final local review-fix validation: 117 focused cases across producer replay, generic handoff,
Shinka exporter and producer CLI passed with zero failures/errors/skips. New replay cases cover
omitted/null records, malformed incomplete bundles, raw/canonical request digests, unknown envelope
identity, missing source, actual source byte/same-byte inode replacement and a producer root
symlink installed after final manifest preparation. Whole-source Ruff, compileall and diff checks
pass. These are local fixture checks; final-source CI/audit remains separate.

## Out of scope

This gap report does not authorize real OpenEvolve/Shinka campaigns, remote evaluators, external
worker authentication, multi-host ownership, distributed scheduling, or sealed CPython/toolchain
acceptance. Those remain P2 or separate P1 runtime work as recorded in
`priority-execution.md` and `stage-gap-report.md`.
