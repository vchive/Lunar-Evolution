# Live model request progress

Status: implemented, fully regressed and merged in PR211, 2026-11-02.
This document's final evidence update is a documentation-only successor;
the exact tested software tree and its merge are recorded below.

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
- [x] Complete unified regression, independent review and main integration.

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

The first complete CI attempt `41372324599` on head `e5f3e57f` exposed a missed source-pin
dependency: the fixed OpenEvolve preparer still bound the previous full HTTP
transport source. Python3.13 current-5 reported one failure and 26 setup errors;
the Shinka preparer shares this binding. Preserve that original failed attempt.
The correction updates only the exact full-source bytes/SHA256 after reviewing
that its two extracted transport constants and the generated broker bytes are
unchanged. Full-source drift rejection and the historical generated-broker
assertions stay enabled; no new accepted source set or relaxed check is added.
Independent comparison confirmed the historical generated broker remains
8,143 bytes with SHA256
`5c0474648bf173f0d24a0fcc12e6d1eedc0d9b4169c3cab4d22def2ed38d43b0`,
with all 17 extracted records unchanged. One three-complete-file supplement
passed 119 tests, zero failure/error/skip, in 0.647 seconds. The corrected
transport source pin is 28,611 bytes and SHA256
`b6e2966b622f3d9708d0c5953b1908fe9f17d19479a66d344475192ef15c6ce6`.
The original complete CI failure is not overwritten by this supplement.
The corrected final source completed CI `41376210045` as recorded below.

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

An additional 25 verified regenerable cache/build paths removed 33,550,336
allocated bytes. Total cleanup is 10,393,341,952 allocated bytes (about
9.68 GiB). The independent cleanup review confirmed 969 expanded directories
absent and all 648 unique retained original ZIP hashes unchanged; its report
SHA256 is `10be39b0897aa67ed65c36270d159a2041206f6b5aba6f6093176c62e2dcb9b0`.
The primary ignored evidence root is
`.lunar-evolution/validation/project-cleanup-20261102/`.

## Final regression and integration

Corrected run [41376210045](https://github.com/vchive/Lunar-Evolution/actions/runs/41376210045),
attempt1, completed with all 45 jobs successful. Head
`2f5eaec35e5bc7bfaf368175e49024a97534ef74` and original tested merge
`a5e28594aad4dcc8ddc87fcb6dc9cf9c7973b38c` have the identical tree
`c11aca649ffd188f3d774bc0f763266bab70114a`. The actual interpreters are
Python3.11.17, 3.12.15 and 3.13.17. Each version has:

- 28,153 exact current/heavy nodes: 28,019 passed, zero failures/errors and
  the same 134 baseline skips, with node/type/message/text equality.
- All 59 additions passed, with exact identities independently reconstructed
  from source AST and existing local XML; no baseline node was removed.
- 2,294 archived and 24 frozen exact historical keys passed, zero skips and
  no retry in this corrected run.
- All 83 derived focused groups passed, including 65 zero-skip gates; these
  receipts aggregate the original execution and are not extra test runs.

All 45 original ZIPs were checked against official size/digest, CRC, download
receipt and exact member identities. Independent evidence review also checked
job/run/head/attempt identity, source/merge binding, exact new keys and
historical pins. Its script performed no tests, collection, network or archive
extraction. Original reports are in the primary ignored directory
`.lunar-evolution/validation/live-model-progress-20261102/ci-pr211-corrected/`:

- `audit-report.json`: SHA256
  `67d684b99b4999620b8c526b76420aba520cfd73e73d4b8b00e65531f4029d41`.
- `independent-original-zip-review-v1.json`: 29,245 bytes, SHA256
  `719833aee811d701cd631fa16025b948693b8be0d0cdb0d65dcc84a864596ff9`.

The first run is separately retained under `ci-pr211/`: overall cancelled,
32 successful jobs, four failures (one execution plus three dependent gates)
and nine cancelled jobs. Its original execution XML preserves one failure,
26 setup errors and 51 skips. The superseding correction did not overwrite
those original artifacts or treat their results as corrected-run evidence.

[PR211](https://github.com/vchive/Lunar-Evolution/pull/211) merged as main
`ff32c769709e1967252abe3ffba652fb0a33fdca`, with parents
`2a6d8099dcfcfd6baf4412181f71f1883814a5ac` and
`2f5eaec35e5bc7bfaf368175e49024a97534ef74`; the merged tree equals the exact
tested tree. Root's create-only merge receipt SHA256 is
`2415c34891740ef4ef0ac627d4586af4c4f11d1da3c626ffb7bb787aec215dfe`,
under the same primary evidence root. The later documentation-only state
update is not claimed to have its own full-tree regression.

This closes this software delivery gate only. No real model, WebAgent, remote
evaluator or company platform ran for this change. Ordinary-model E2E remains
failed/unaccepted; native RSI P1 remains open. Local logging does not diagnose
the server cause. `production_admission=false` and `online_publication=false`.
