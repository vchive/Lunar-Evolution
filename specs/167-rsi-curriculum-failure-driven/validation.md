# Validation

The provider-free narrow policy is covered by `tests/test_rsi_curriculum.py`:

- idempotent failure clustering and capability/prerequisite coverage;
- repeated-failure hard-negative and boundary-task suppression;
- same seed and ledger replay;
- budget exhaustion and tampered-ledger rejection;
- canonical ledger digest stability.

Run the focused suite with:

```bash
PYTHONPATH=src pytest tests/test_rsi_curriculum.py -q -o addopts=
```

The implementation is also exercised by the existing RSI suite; no remote evaluator or external
producer is required.

Controller-level coverage in `tests/test_rsi_curriculum_resume.py` verifies that the optional
failure-driven ledger is checkpointed before callback completion, restored on resume, and does not
charge a second selection when the decision checkpoint is lost. Legacy deterministic curriculum
checkpoints retain their previous shape.
