# Validation

## Native attempt control propagation (provider-free fixture verified; integration open)

The cooperative Feature 156 runner already verifies active cancellation and composition of a
caller-owned monotonic parent deadline. The native trusted attempt must provide the same control
boundary before T158-04 can close: the effective deadline is `min(intent_deadline,
parent_deadline)` in one monotonic clock domain, and every control/frame write, frame read, broker
wait, process wait, cleanup phase, and terminal evidence write consumes that remaining budget.
Cancellation is a process-local callback, checked before spawn, after durable registration, while
waiting for bootstrap/target frames, and while waiting for the leader. A boolean cancellation
observation followed by verified owner-checked cleanup may produce a `cancelled` process receipt;
callback exceptions, non-boolean values, deadline expiry, or cleanup uncertainty remain
`unknown`/`recovery_required`. The callback and parent deadline are control inputs rather than
identity fields and cannot authorize a retry or publication.

The native fixture suite now covers active cancellation after target start, cleanup uncertainty, a
parent deadline that narrows the intent budget, and invalid callback/deadline inputs. The focused
native attempt suite passes 26 tests on the local Darwin host. This is supporting evidence for the
control boundary only; the acceptance matrix keeps the row `supporting-only` until T158-04 connects
the attempt to the formal Feature 156 registration, broker, terminal receipt, and recovery runner.

The same suite now verifies the durable cancellation variant: a verified post-gate cancellation
writes `native-trusted-process-terminal.json` with `process_status=cancelled` and `exit_code=null`,
recovery returns the exact receipt without signaling, and tampering, callback errors, deadline
expiry, or cleanup uncertainty do not create that terminal. This remains process-only evidence;
it does not authorize bundle publication or replace the formal execution receipt.

Terminal receipts now bind the retained deadline sidecar digest. A focused regression replaces the
sidecar with a different self-digested budget and confirms recovery rejects the terminal chain.

The read-only native lifecycle audit now composes the process terminal with optional output capture
and broker evidence. Focused fixtures cover process-only completion without capture, valid capture
digest and request coverage, capture receipt tampering, and broker journal tampering. Recovery or
unknown records are classified as `recovery_required` before any output read. The audit remains
provider-free and publication-ineligible until Feature 156's formal execution receipt and
recovery path consume the same records.

The verified audit can also be persisted once as a digest-only
`native-trusted-execution-audit.json` sidecar. Focused coverage checks its terminal/capture/deadline
chain, create-only behavior, and refusal to write when output capture is absent. The sidecar is
publication-ineligible and deliberately remains separate from Feature 156's formal execution
receipt until trusted stream, envelope, broker, and recovery evidence are integrated.

## 2026-10-01 formal receipt to publication journal

The strict native projection now has a create-only formal receipt and a provider-free downstream
check in Feature 153. A valid receipt digest is preserved in the publication journal; missing,
invalid, self-digest-tampered, unsuccessful, or wrong-task receipts are rejected before staging.
This proves the durable handoff boundary only. The native fixture still does not satisfy the full
Feature 156 runner contract, scheduler integration, post-crash transport recovery, or external
campaign acceptance required to close T158-04.

The recovery verifier also rejects a missing or rehashed sidecar and a capture digest changed only
inside a self-rehashed sidecar. This keeps the audit projection diagnostic until formal Feature 156
receipt consumption is implemented.

The native stream slice now drains both output pipes concurrently under the per-stream byte limit,
persists `stream_capture_sha256` in the terminal, and rejects incomplete or rebound stream records
on recovery. Envelope capture records stable before/after identity digests; broker capture binds
the canonical host journal and requires complete admitted-count coverage. Cleanup is persisted as
`native-trusted-cleanup.json` and bound into the terminal. Focused native stream, output, attempt,
cleanup, and projection suites pass locally with provider-free fixtures. The new
`build_native_trusted_execution_receipt` function builds an in-memory formal DTO only after these
checks. The companion persistence test must create exactly one `execution-receipt.json`, fsync
the canonical payload, reread it through the bounded no-follow path, and recover the same receipt
self-digest. Repeating the call against unchanged bytes is a read-only idempotent success. The
negative fixtures must reject an existing different receipt, a self-rehashed/tampered receipt, a
symlink or non-regular destination, and every missing or changed terminal, stream, envelope,
broker, target-binding, deadline, or cleanup sidecar. No fixture may treat the formal receipt as
publication or population authority; it remains `publication_eligible=false` until the separate
Feature 153 admission transaction consumes it.

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
