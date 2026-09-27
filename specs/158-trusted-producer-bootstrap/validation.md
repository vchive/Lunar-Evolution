# Validation

The native artifact increment is provider-free. On the current Darwin host:

- `tests/test_native_bootstrap.py`: 3 passed. A compiled native bootstrap emits canonical frames,
  waits for release before target work, rejects duplicate gate tokens, and rejects changed
  installation bytes during allowlist loading.
- `tests/test_trusted_bootstrap_binding.py` and `tests/test_trusted_bootstrap_runtime.py`:
  47 passed, 1 skipped (Linux-only binding case).
- `tests/test_producer_isolation.py`: 4 passed. The dedicated Darwin sandbox fixture verifies
  allowed workspace writes and denied outside writes/network access.
- Ruff and Python compilation passed for the new Python build/control layer and tests.

The native child is not yet a Feature 156 production lifecycle entry point. The tests do not
consume user attestations, launch external producers or provider calls, establish a Linux runtime
result on this Darwin machine, or close T158-04.
