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
complete request/source/material pin refusals, path-free fingerprints, and cached-result
drift rejection. Local fixture files exercise the actual replay inspector; a terminal
controller resume checks retained evidence without a second dispatch and leaves the ledger
head unchanged on refusal.

On 2026-10-12, after merging PR62 dependency `ccace97348a35eb2611662b41fe071ba535ce9db`,
the combined replay gateway/CLI, producer handoff, Shinka export, producer CLI and native
controller replay suite passed 136 tests with zero failures, errors or skips. Whole-tree
Ruff, compileall and git diff --check passed. The JUnit report was retained locally at
`/private/tmp/lunar-final-replay-20261012-02.xml`.

This is provider-free evidence. It does not claim real runtime, evaluator, worker
authenticity or production admission. Final-source Linux CI and independent raw/source/tree
audit remain required before main integration.
