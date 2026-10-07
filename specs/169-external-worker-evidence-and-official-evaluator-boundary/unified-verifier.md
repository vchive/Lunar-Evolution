# Unified local worker evidence verifier

`verify_trusted_worker_evidence()` checks a trusted-local record chain. Bootstrap evidence
reports a handshake/start observation: `passed` alone does **not** establish process completion,
cleanup or evaluator success. The previous bootstrap-only classification was insufficient.

A terminal classification requires all of these inputs from the same original attempt:

1. Launch, intent, attestation, consumption, formal process registration and handoff.
2. Bootstrap handshake evidence, including its exact launch/registration binding.
3. Native process-only terminal receipt, including original PID/PGID/owner identity, exit code,
   gate/start flags, previous registration digest and handoff/evidence digests.
4. Original deadline receipt with a finite increasing monotonic interval and matching
   launch/intent/attestation. The terminal and cleanup bind its exact digest; recovery never
   allocates a fresh interval.
5. Cleanup sidecar with the same intent, registration, deadline, PID/PGID, status and digest.
   Cleanup must be `cleaned` or `already_exited`, with `alive_after=false`.

Classification:

- `trusted_completed`: bootstrap handshake passed, process terminal is `exited_zero`, and
  all deadline/cleanup bindings validate.
- `trusted_failed`: verified process terminal is `exited_nonzero` or `cancelled`; cancellation
  may bind an explicitly unknown bootstrap observation when the independent terminal and
  cleanup prove the cancellation. Cancellation never establishes a successful exit.
- `unknown_recovery_required`: bootstrap, process terminal, original deadline or cleanup
  evidence is absent. A failed bootstrap handshake without process/cleanup receipts remains
  unknown rather than being promoted to a terminal failure.
- `identity_drift`: a supplied record, digest, schema, exit status or binding is inconsistent.

The result exposes the verified registration, handshake, terminal, deadline and cleanup digests.
New terminal/deadline/cleanup parameters default to `None`; old bootstrap-only calls remain
read-only but now return unknown. Invalid supplied records never produce terminal authority.

The verifier performs no filesystem/process/clock I/O, writes, signals, retries or attestation
consumption. It shares pure deadline/terminal/cleanup validation with native attempt recovery.
Filesystem recovery additionally verifies current boot identity, safe retained files, RSI
inputs and any referenced stream sidecar. A pure record classification is not a substitute
for these checks or cross-boot reconciliation. Stream/output contents, independent evaluation,
publication and learning admission remain separate authorities.

Hashes bind trusted-local observations; they do not authenticate a caller able to replace the
whole chain. This API does not provide external project/runtime authentication, multi-host
ownership, distributed leases, successful unknown reconciliation or campaign acceptance.
