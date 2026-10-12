# Validation

Focused validation is local and provider-free:

```bash
PYTHONPATH=src pytest -q tests/test_rsi_replay_gateway.py
ruff check src/lunar_evolution/rsi_replay_gateway.py \
  src/lunar_evolution/rsi_controller.py tests/test_rsi_replay_gateway.py
python -m compileall -q src tests/test_rsi_replay_gateway.py
git diff --check
```

The tests assert stable unknown handling, exact completed-result round trips,
request/source pin refusals, path-free fingerprints, and cached-result drift rejection.
They do not claim real runtime, evaluator, worker authenticity, or production admission.
