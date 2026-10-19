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
