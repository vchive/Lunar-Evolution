# P1 provider-free CLI / producer audit

Date: 2026-10-14
Baseline: `origin/main` at `3c197ca`
Scope: local/provider-free inspection only. No model, WebAgent, remote evaluator, real
CPython/toolchain, or OpenEvolve/Shinka campaign was run.

## Finding

The current implementation does not silently turn producer labels into producer execution:

- `rsi run --solver openevolve|shinka` constructs the deterministic fixture gateway. Its JSON
  says `solver_execution=provider_free_fixture`, `production_admission=false`, and
  `producer_replay_required=true` with a warning for those solver IDs.
- `rsi resume` reconstructs the persisted fixture identity and emits the same explicit marker.
- `rsi run|resume --solver-execution native-producer` fails before contract reads, home/ledger
  initialization, fixture gateway construction, or any worker launch with the fixed code
  `rsi_python_producer_gateway_cli_accepted_runtime_required`.
- `rsi replay` is a read-only retained-evidence comparison. It requires independent contract,
  request, memory, producer, envelope, material and receipt pins, reports
  `evidence_scope=retained_local_comparison`, and always keeps `production_admission=false`.
  Missing or non-terminal evidence is `unknown`; producer-declared scores are not Lunar
  evaluation authority.
- The OpenEvolve and Shinka Python adapters perform bounded, no-follow source/SQLite reads only
  after binding, terminal, observation, result, installation and initialization pins validate.
  They neither launch a producer nor write an export directory. Their exported adapter envelope
  requires `production_admission=false`.
- The `export-shinka-result` CLI is a read-only result-material exporter and does not initialize
  normal controller state or start a process. OpenEvolve result inspection is available through
  the shared retained replay/export APIs; neither path constitutes runtime admission.

No safe provider-free code change was identified in this audit. Adding a process-backed
`rsi producer-run` entry now would violate the existing boundary because accepted runtime,
per-episode context staging, native claim/receipt mapping, and sealed runtime acceptance are
not complete. The correct next P1 slice is runtime-gated single-episode composition, followed
by production CLI acceptance, while retaining this explicit refusal and all provenance markers.

## Verification

Focused provider-free regression (159 tests) passed:

```text
.venv/bin/python -m pytest -q \
  tests/test_rsi_producer_gateway.py \
  tests/test_rsi_producer_replay_cli.py \
  tests/test_python_producer_export.py \
  tests/test_producer_cli.py
```

The suite covers refusal-before-I/O for native opt-in, explicit fixture output markers,
read-only replay and exporter behavior, source/SQLite/inode drift, missing/unknown terminal
states, pin mismatch, and producer score drift. `production_admission=false` remains asserted.

This report intentionally changes no runtime code. It records the P1 audit boundary so a future
runtime-backed CLI cannot be mistaken for the provider-free fixture or retained replay path.
