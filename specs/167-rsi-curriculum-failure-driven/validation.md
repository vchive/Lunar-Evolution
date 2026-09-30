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
