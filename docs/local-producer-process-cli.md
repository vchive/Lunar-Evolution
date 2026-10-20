# Local producer-process lifecycle CLI

Feature191 exposes the existing retained process journal through a deliberately small,
provider-free command. It does not start OpenEvolve/Shinka, run an evaluator, initialize the
controller database, or publish a candidate.

Inspect an attempt without touching the process group:

```bash
lunar-evolution producer-process inspect WORKSPACE JOURNAL_ID --json
```

If a process registration exists but the terminal receipt is missing, an owner may explicitly
request the existing fail-closed cleanup path:

```bash
lunar-evolution producer-process cleanup WORKSPACE JOURNAL_ID --confirm --json
```

`--confirm` is required because cleanup may send bounded `SIGTERM`/`SIGKILL` signals to the exact
durably registered process group. Ownership, PID-reuse, recovery-lock, and registration checks
remain in `recover_producer_process`; a mismatched or uncertain owner is never signalled. Cleanup
only addresses a missing terminal receipt. It does not restart a producer or repair a journal.

The command returns the retained observation with `evidence_scope:
retained_local_process_lifecycle` and always reports `production_admission: false`. A cleanup that
still returns `recovery_required` exits nonzero, preserving the existing unknown/reconcile gate.
This is local lifecycle plumbing, not sealed Python runtime or real OpenEvolve/Shinka campaign
acceptance.

## Retained Python terminal gate

The Python adapter also exposes a detached terminal check for a caller that already retained a
canonical `PythonProducerTerminal` and its original binding digest:

```bash
lunar-evolution rsi producer-terminal TERMINAL.json \
  --binding-sha256 BINDING_SHA256 --deadline-unix 4102444800 --json
```

This command only reparses the terminal and validates its binding/deadline pins through the
existing read-only resume contract. It does not read the sidecar, inspect or signal a process,
open the RSI ledger, invoke an evaluator, or repair an unknown terminal. A valid terminal returns
`production_admission: false`; an `unknown` terminal returns `reconcile_required` and exits
nonzero so it cannot be treated as a completed producer result. This is a retained evidence gate,
not acceptance of a sealed runtime or a real OpenEvolve/Shinka campaign.

## Retained producer acceptance envelope

When the project preflight and Python terminal report are already retained, they can be composed
with the read-only acceptance-envelope command:

```bash
lunar-evolution rsi producer-acceptance PROFILE.json TERMINAL.json \
  --binding-sha256 BINDING_SHA256 [--deadline-unix 4102444800] \
  [--replay-report REPLAY.json] --json
```

The command validates the detached project profile, rechecks the retained terminal binding and
deadline, and optionally consumes a retained local replay summary. It never starts a producer,
invokes an evaluator, opens the RSI ledger, or publishes a result. Its output is always
`status: blocked` with `reason: runtime_acceptance_required`, `execution_performed: false`,
`evaluator_invoked: false`, `production_admission: false`, and `online_publication: false`.
Missing `terminal_reconcile` or `retained_replay_completed` entries remain explicit gates in
`missing_gates`; a completed replay only removes the latter evidence gate. Exit status `1`
therefore means the retained envelope is valid but still blocked, while malformed or drifted
inputs exit `2`. This is evidence composition for the next runtime-acceptance stage, not a
runtime or campaign acceptance decision.
