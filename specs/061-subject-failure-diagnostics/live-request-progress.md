# Live model request progress

Status: specified before implementation, 2026-11-02.

## Problem

The independently audited 50-minute attempt failed on its fifth HTTP request.
The worker flushed local transport milestones, but the parent waited for the
entire exchange before exposing them. The missing capability is bounded live
diagnostic output; neither a client defect nor a server-side cause is known.

## Contract

- Add opt-in structured model-request logs. The existing Python logger is
  configurable by library callers; `effect-subject --model-request-log` enables
  fixed JSON lines on stderr for that command only. stdout remains the existing
  protocol. Do not configure the root logger or retain an unbounded log file.
- Each local request has one opaque correlation ID, a start event, periodic
  waiting observations and a terminal success/failure event when locally known.
  The ID is never sent in HTTP headers/body. Log fixed enums, bounded numbers
  and the existing failure-only request fingerprint. Never log endpoint, model
  text, credentials, arbitrary headers, response/error bodies or exception prose.
- A bounded request may wake its original parent every 30 seconds to report
  safe progress. Reuse the existing strict `_Progress` parser for complete small
  frames only; never forward raw IPC or terminal frames. Keep one Popen, send
  input once, preserve the original absolute deadline and reject late success.
  A polling interval is not a retry, request timeout or extra HTTP exchange.
- The default path stays silent and retains its existing single communicate
  behavior. Invalid optional clocks, snapshots, IDs, loggers or observers cannot
  change an outcome or its original exception/cause. No background polling
  thread is introduced. Direct/unbounded calls have start/terminal logs but
  cannot claim live transport milestones.
- Success still does not compute a request fingerprint. Failure logging reuses
  the fingerprint already attached by the existing failure path. Schemas1–7,
  receipts, accepted partial usage, budgets, request wire, scoring and resume
  behavior remain unchanged. Historical attempts receive no backfilled logs.
- These observations describe local process/transport state only. They do not
  prove server receipt, queue/inference time, cancellation, billing or complete
  process-group cleanup. Production/publication authority remains false.

## Verification and delivery

Implement transport progress and runtime/CLI logging in parallel. Test with
deterministic transports and loopback fixtures: accumulated/partial IPC, invalid
frames, observer errors, input-once, absolute deadline and cleanup; correlate
start/wait/terminal, protect distinct secret sentinels, preserve failure-only
hashing and command stdout. Complete development before a combined regression.
Run the full supported regression through the existing runner/CI, preserving
actual XML, failures and platform skips; do not call real model services,
WebAgent, remote evaluators or company platforms. Ruff, compileall and diff
checks apply. Do not weaken historical inventories or skip gates for speed.

Clean only verified regenerable project caches or exact archive-backed expanded
copies; keep original archives, reports, configuration, worktrees and unrelated
uncommitted changes. Record paths and bytes recovered separately from test
evidence. User-space quota and local free disk must be checked before regression.

## Tasks

- [x] Audit current live-observation gap and register the finite contract.
- [x] Implement bounded transport observations and deterministic tests.
- [x] Implement safe runtime/CLI JSON logs and integration tests.
- [x] Clean verified regenerable intermediates and retain the cleanup inventory.
- [ ] Complete unified regression, independent review and main integration.

## Local verification and cleanup

One combined thirteen-file Python3.13.12 batch passed 555 tests with zero
failure/error/skip in 22.558 seconds. It covers the new progress/logger/CLI
files plus existing deadlines, IPC, milestones, TLS, failure fingerprint,
timing, subject diagnostics and adapter behavior. No real model or evaluator
ran. Pytest emitted cleanup warnings for pre-existing immutable fixture
directories in its shared macOS temporary root; the original XML remains
under primary ignored `validation/live-model-progress-20261102/local/affected.xml`.
Final static review then tightened native-string dictionary keys for optional
wait snapshots and added a boundary assertion for the 2,880-wait-record cap.
A separate two-test supplement passed; the original 555-case batch was not
repeated. Ruff, compileall and diff checks passed. Full three-version CI remains a
separate final-source gate, not implied by this local batch.

The reviewed cleanup removed 969 flat CI expansion directories only after
rechecking their complete bytes against retained original ZIP members. It
removed 10,359,791,616 allocated bytes (about 9.65 GiB); no original archive,
source, configuration or audit report was removed. The create-only inventory
and deletion journal are under primary ignored
`validation/project-cleanup-20261102/`. Inventory SHA256:
`cb7be0af36c7ebc7aba72828822ef5e2060025f7ad0b256cf0acbe2b2691e5eb`.
Every deleted member's original path, size and SHA256 and its retained ZIP are
recorded there, so the expanded bytes can be restored. Local free space rose
from about 6.6 GiB to about 16 GiB. Historical audit claims stay scoped to their
original observation time; absent expanded paths must be restored from ZIP
before reusing readers that expect them.
