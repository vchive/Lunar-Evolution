# RSI learning mode quickstart

Feature 160 now has a provider-free controller, gateway, verifier, memory gate and SQLite episode
ledger. The runnable fixture in `quickstart.py` demonstrates one deterministic DRS
target-gap-practice cycle without an OpenAI-compatible runtime or external producer.

Run it from the repository root:

```bash
PYTHONPATH=src .venv/bin/python specs/160-rsi-learning-mode/quickstart.py
```

The local fixture can be run directly through the CLI:

```bash
lunar-evolution rsi run ./rsi-contract.json \
  --mode drs \
  --solver mock \
  --max-practice-rounds 3 \
  --max-target-attempts 2 \
  --home .lunar-evolution
```

The command must create one durable RSI run, an initial target episode, and a bounded episode ledger.
It must print JSON containing `run_id`, `status`, `memory_snapshot_sha256`, the latest target outcome,
and `recovery_eligibility`. It must not call WebAgent, a remote evaluator, or a company evaluation
service.

A later solver selection may use the same gateway boundary, but the current CLI keeps these IDs on
the provider-free fixture and does not launch external processes:

```bash
lunar-evolution rsi run ./rsi-contract.json --mode brs --solver openevolve \
  --home .lunar-evolution
```

The `--solver` value selects fixture provenance only; the current CLI has no external command
option and does not launch OpenEvolve or Shinka.

OpenEvolve/Shinka are still candidate search backends. Their population, island and iteration data
remain solver provenance and are not copied into approved RSI memory. Every practice must retain the
normal Lunar candidate, execution and evaluator receipts before the independent verifier can run.

Inspect and reconcile a durable local record with:

```bash
lunar-evolution rsi inspect RUN_ID --home .lunar-evolution --json
lunar-evolution rsi reconcile EPISODE_ID --worker-state failed \
  --expected-record-sha256 RECORD_SHA256 --home .lunar-evolution --json
```

The current fixture covers the DRS cycle, BRS frozen-parent merge, transfer write guard, terminal
state fixtures, and these local diagnostics. Durable controller resume, real OpenEvolve/Shinka
adapters, and LLM-assisted curriculum remain follow-up work; no provider credentials are read.
