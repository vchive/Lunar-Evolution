# Runtime input stability and recoverable artifact cleanup

Status: scoped implementation in progress, 2026-11-03. Baseline is accepted
mainfab7458a (PR221). The user requested system stability and project space
cleanup. These locally identified robustness defects are not established causes
of PR221's arguments_invalid_json failure; its missing response cannot be rebuilt.
No model inference, retry, response repair or scoring is part of this slice.

## Fixed failure boundaries

1. CPython JSON decoding may raise RecursionError for nested input and ValueError
   for an integer exceeding its configured decimal conversion limit. The outer
   response and string tool-argument decoders currently catch JSONDecodeError only,
   so these failures bypass ModelRequestFailure and lose fixed request evidence.
   Catch ValueError (including JSONDecodeError) and RecursionError at exactly those
   existing decode boundaries. Preserve invalid_json for outer response and
   invalid_tool_calls/arguments_invalid_json for tool arguments. Reject the whole
   batch before usage or any tool effect; do not repair or accept rejected input.
   Keep causes, HTTP status, phase, fingerprint and optional fixed logs. Do not
   change process-wide recursion/integer limits, valid decoding or parser order.

2. A JSON-escaped lone surrogate in response model identity may raise
   UnicodeEncodeError during UTF-8 length validation instead of the existing
   invalid_model_identity refusal. Convert only that encoding failure to the
   same typed identity rejection. Valid identity stripping/length/NUL rules,
   response acceptance and usage ordering stay unchanged. Do not redact or alter
   provider strings to force acceptance.

3. LocalToolRegistry constructor currently accepts NaN/infinite command timeouts
   because a positivity comparison alone is insufficient. With no invocation
   deadline these values defeat finite timeout comparison. Noninteger output
   limits can likewise bypass comparisons or fail during capture slicing.
   Require a finite positive numeric timeout excluding bool, and a positive
   integer output limit excluding bool; reject unrepresentable huge timeout ints
   as ValueError too. Keep defaults and all accepted finite values, without new
   ceilings or changes to execution deadlines, argv, environment or cleanup.

No general exception catch is added, and interrupts, MemoryError or unrelated
coding failures are not converted to successful results. No new diagnostic
schema/enum, provider metadata, parser fallback or credential-bearing log is added.
Existing schemas1–8 and six category labels remain intact.

## Validation and integration

Develop these disjoint files in parallel; add focused tests before one batched
regression. Synthetic HTTP responses only for decoding/identity; command process
seams only for limit validation. Cover actual interpreter decode limits, both
direct/bounded seams, normal controls and existing syntax rejection, fixed log
privacy/default silence, batch atomicity and no usage acceptance. Test invalid
limits before process launch and preserve valid defaults/deadline behavior.

Do not modify existing tests just to weaken expectations. Ruff, compileall and
git diff --check must pass. Refresh only source pins that actually bind changed
product files, if any; independently inspect relevant producer registries rather
than assuming a refresh. Run the final software CI once after integrated review.
Keep baseline coverage/skip identities and source binding. Publish exact failures
as well as successes; cleanup must not remove verification originals.

## Space cleanup boundary

Inventory project directories before deleting. Limit deletion to untracked,
reconstructible caches/build output or pure archive-expanded copies whose original
archive is retained and whose every member matches. Do not delete owner .env,
working source, uncommitted files, original ZIP/tar, manifests/audit receipts,
original failure evidence, accepted evaluator venv, prepared attempt inputs or Git.
Frozen source snapshots that are still pinned by launchers remain intact.

Preserve a concrete cleanup manifest, exact retained reconstruction source and
allocated bytes before deletion; recheck paths, symlinks, pins and contents before
removal. Independently review that concrete manifest and audit the result. Report
observed released file allocation separately from df free-space change; APFS and
other concurrent activity prevent assuming they are equal. No broad git clean,
recursive project wipe or unrelated worktree removal.

## Tasks

- [x] Audit actual local defects and scope changes.
- [x] Implement decoder/identity and constructor bounds with focused tests.
- [ ] Review integrated source; run one focused batch and static checks.
- [ ] Inventory, review and delete only recoverable project artifacts.
- [ ] Complete final CI/source/evidence checks and integrate main.

Ordinary-model E2E P0 and native RSI P1 remain open. Passing this robustness slice
does not establish provider reliability, benchmark success or native immutable
worker acceptance. production_admission=false; online_publication=false.
