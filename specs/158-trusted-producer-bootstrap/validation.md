# Validation

## Native pre-gate handoff reread (2026-09-28)

The native attempt now uses the formal read-only observer under its existing deadline before
releasing the gate. The observer requires a stable no-follow handoff file and verifies it
against the byte-identical nonce claim, launch, descriptor, attestation, and formal
registration. Provider-free native subprocess tests prove that removing or altering the
handoff after publication leaves the target marker absent. Terminal execution receipts,
brokered requests, and post-crash cleanup remain outside this increment.

## Native bootstrap and isolation checkpoint (`15b8113`, 2026-09-27)

The checked-in C bootstrap now has a real Darwin bootstrap-to-isolated-target integration test.
After the exact one-byte gate closes, the compiled target starts and exits zero, writes its
declared workspace, and receives an OS permission denial for an outside write, controller-secret
read and direct network connection. A live loopback listener with an unsandboxed positive control
ensures the network denial is not merely a closed port. The C path executes the verified
`target_path` independently of `argv[0]`. Darwin's policy grants dyld access to the root directory
itself while retaining the deny-by-default subtree boundary.

At this checkpoint the five acceptance/native-isolation suites pass **82 tests**, with zero
failures/errors/skips. The retained JUnit report is
`.lunar-evolution/test-results/checkpoint-15b8113-focused/focused.xml`. This is a local,
provider-free controlled executable test, not an external producer or real campaign acceptance.

The same report contains **6 native-bootstrap tests** and **4 producer-isolation tests**. Their
coverage includes canonical frames, target-marker absence before release, duplicate gate token
rejection, installation-byte replacement, target argv binding and actual pre-exec isolation.

## Earlier native artifact checkpoint

The earlier native artifact increment was provider-free. On the Darwin host:

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
result on this Darwin machine, or close T158-04. Formal registration-before-release, target FD/
snapshot handoff, one shared deadline, cleanup/recovery receipts, brokered egress and scheduler
integration remain open.
