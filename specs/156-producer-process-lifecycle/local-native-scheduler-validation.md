# Real local native scheduler regression

Use a fixed, locally compiled C producer and the checked-in Lunar native bootstrap artifact.
The target is byte-bound to an explicitly created fixture launch intent/attestation; the latter
does not certify OpenEvolve, ShinkaEvolve or any external producer. Provider traffic goes only to
an ephemeral loopback fixture, with credentials retained in the controller-owned broker.

The successful chain runs the public native scheduler, registration-before-gate, isolated target,
broker request, contemporaneous two-file envelope capture, complete formal receipt, strict output
preparation, local native candidate execution/evaluation, publication, archive/population and
delivery read-back, followed by read-only receipt/output recovery. No scheduler stages are stubbed.

Additional real-process fixtures cancel after the target marker proves gate release, verify
owner-checked cleanup and retained cancellation evidence with no publication, and simulate a
controller interruption immediately after formal receipt fsync. Recovery reuses the same retained
receipt/output without spawning the producer or issuing another request; explicit normal
publication can then evaluate/admit the recovered drafts.

The extended matrix verifies a tighter parent deadline during real target execution, retained
deadline bytes and owner cleanup, and interruption after the durable publication unknown marker
and first candidate move. The latter keeps archive/state bytes unchanged, blocks normal archive
reads, and never auto-retries the commit. Complete producer receipt/output recovery remains
independently read-only, but cannot turn uncertain publication into success. Exact completed
publication recovery runs twice with launch, evaluation, staging and commit forbidden and verifies
all retained file bytes/inodes are unchanged.

This closes a local formal integration evidence gap. Remaining real project campaigns are
separate acceptance work forbidden by this session's local-only scope. External project adapter
bootstrap trust, runtime/dependency allowlists, project credentials and cross-platform production
coverage must be established independently; local fixture success does not substitute for them.
Complete crash/unknown and bypass matrices remain assessed against their own task requirements.

## Active candidate control amendment

Candidate execution and the independent evaluator must observe the existing caller/retained
control while their process is running, at the bounded runner's polling interval. A cancellation
raises the original typed cancellation after the runner's existing process-group cleanup; it
must not return a successful execution/evaluation receipt or stage/population publication.
An uncertain cleanup retains process ownership. Polling reuses the existing remaining-time
callback and cannot allocate or refresh a budget. Callback failures fail closed through the
same cleanup path. This amendment leaves the publication commit's durable unknown boundary
unchanged: no new cancellation checkpoint is added after that boundary.

Cancellation-only transactions install and restore a temporary native pipeline check without
declaring a new wall allowance. Existing pipeline/context parent hooks still constrain work.
Both cancellation-only and shared-wall controls are exercised for candidate execution and
independent evaluation. Marker monotonic timestamps come from inside each actual process, so
the fixture measures response from process start rather than from the delayed caller observation.
Invalid or raising cancellation callbacks are also checked during real candidate execution;
cleanup runs and neither candidate completion nor publication is fabricated. An independent
runner fixture retains ownership when cleanup confirmation is deliberately withheld.
The shared-wall path also binds an independently supplied publication continuation guard into
the active runner's same check. Cancellation cannot be bypassed by providing a wall control.
Cancelled drafts retain incomplete execution/evaluation evidence; explicit retry inspects and
fails with recovery required rather than automatically executing or scoring them again.

Local validation adds parent deadline, interruption after the unknown marker, exact published
recovery without evaluation/commit, and actual candidate/evaluator cancellation after their
markers prove execution started. These fixtures do not certify external project launch trust.

## Remaining task classification

| Tasks | Current code and remaining work |
| --- | --- |
| T153-06/06b | Native transaction, active candidate/evaluator cancellation, retained deadline and publication recovery exist. This regression joins real producer publication, post-receipt interruption, partial-commit unknown blocking and exact read-only published replay. The complete crash/unknown matrix remains separate; these explicit cells are confirmed locally. |
| T156-05/06/09/11/12, T158-04 | Native byte-bound artifact/target, gate registration, deadline, capture, owner cleanup and retained recovery exist. The new regression confirms their local scheduler composition; production and cross-platform lifecycle acceptance remain separate. |
| T156-14, T157-05/06 | Host pipe broker, host-only credentials, append/fsync journal and read-only recovery exist. The target cannot write the host journal or connect directly in this fixture. Complete bypass surfaces and post-crash active transport ownership/recovery still need the declared matrix. |
| T159-05 | Same-attempt capture, formal receipt, broker evidence and publication are now exercised together through the actual scheduler. This local proof does not establish unrestricted complete egress coverage. |
| T153-07 project integration | Existing result adapters and native scheduler do not establish a production OpenEvolve/Shinka launch trust chain, runtime/dependency allowlists, or default project scheduler registration. These project-specific integration requirements must be verified or implemented before launch. |
| T153-07 real campaigns | Running actual OpenEvolve/Shinka campaigns is pending acceptance and outside this session's local-only permission. It is not classified as missing code or as completed by the fixture. |

Validation on the current Darwin host: the extended regression passes 411 tests across 18 focused
suites in 59.325 seconds, with no failures, errors or skips. After the final independent-guard
binding and retained-cancel retry assertions, six affected suites pass 104 tests in 39.113 seconds,
also with no failures, errors or skips. The final matrix contains 13 actual scheduler cases and
six active runner/parent-hook cases; existing suites cover retained transaction/recovery,
execution/evaluation, lifecycle and automatic cancellation. Ruff, compileall and `git diff --check`
pass. The successful
chains use real native bootstrap/target execution and actual native candidate evaluation. The
deliberately injected post-receipt/partial-commit interruptions and missing cleanup confirmation
are fixed local controller/cleanup failures, not evidence of an actual machine crash.
