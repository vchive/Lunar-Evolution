# Runtime input stability and recoverable artifact cleanup

Status: implemented; local checks, cleanup and complete CI passed, 2026-11-03.
Baseline is accepted
mainfab7458a (PR221). The user requested system stability and project space
cleanup. These locally identified robustness defects are not established causes
of PR221's arguments_invalid_json failure; its missing response cannot be rebuilt.
No model inference, retry, response repair or scoring is part of this slice.

## Fixed failure boundaries

1. CPython JSON decoding may raise RecursionError for nested input and ValueError
   for an integer exceeding its configured decimal conversion limit. The outer
   response and string tool-argument decoders previously caught JSONDecodeError only,
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

3. LocalToolRegistry constructor previously accepted NaN/infinite command timeouts
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
seams only for limit validation. Cover the real default integer conversion limit
and the isolated standard-library Python decoder's recursion guard through its
existing loads seam; do not infer the C decoder's stack limit from Python's
getrecursionlimit or probe dangerously deep native stacks. Cover both
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
- [x] Review integrated source; run one focused batch and static checks.
- [x] Inventory, review and delete only recoverable project artifacts.
- [x] Complete final CI and original source/evidence checks.
- [x] Pass independent final original-evidence review; retain actual merge receipts separately.

Ordinary-model E2E P0 and native RSI P1 remain open. Passing this robustness slice
does not establish provider reliability, benchmark success or native immutable
worker acceptance. production_admission=false; online_publication=false.

## Local verification record

Frozen6c43f15a ran one14-file batch:538 tests,532pass/6fail/0error/0skip in
20.19634808320552 seconds. The six failures are new recursion-fixture assumptions:
Python3.13.12's C JSON decoder accepted the chosen nesting depth, so later shape
checks rejected it correctly. This does not establish a product regression.
The original batch remains failed and all originals are retained. Only the new
fixture was corrected to exercise the standard-library Python decoder's
real recursion guard safely; product code and existing tests remained unchanged.
The affected new test file was then run once, as recorded below. Final CI provides
whole-suite acceptance without repeating the prior14-file local batch.

The fixture-only correction at18834a89 passed the affected30-case new file once,
in0.8841384998522699 seconds, zero failure/error/skip, rc0/reaped and no signals.
Product source is byte-identical to6c43f15a; the original31 tool-limit additions
and477 prior tests passed in the first batch. Do not sum these into a claim of
a passing538-case execution. Actual product module origins240/235 respectively
match frozen source/Git blobs; the smaller second set is an identical subset.
Ruff across src/tests/tools, compileall and diff checks pass; temporary compile
cache removed. Producer pins bind broker/transport/fixed launch assets, not these
two changed files, so no generated producer/pin refresh is required.
Independent local original reviewv2 SHA256:
`58872c8239a3c6b3fd5b5c69ca0ed7b53b0843702898dbd8f10e42900ff92e15`.
Originalv1 is retained; v2 corrects only its30-file/30-case wording.
Evidence: primary ignored validation/runtime-stability-20261103/.

## Actual cache cleanup

Inventory338 exact cache roots across44 related project worktrees; every candidate
is Gitignored and has no tracked/uncommitted member. No worktree is removed.
Retain13 editable egg-info directories,2 unknown-origin pycache directories and
all frozen product/evaluator/venv/raw ZIP/evidence/configuration/Git paths.
The archive audit found no additional exact recoverable expansion;7 name/size
matches had different SHA256 content and remain intact.

The reviewed create-only manifest SHA256 is
`dbaefeac572bb25a9fcc360e31f8d3b944bad5b453a674d93df8c7f80201c9aa`.
Executor SHA256:
`c48eb06fcca6edfa37ccb6eb345c3ce83fbc12f174339a9ac8f046845e13498c`.
Before removal it rechecks each member/root stat, Git status and open paths. It
unlinks only fixed listed files through no-follow directory descriptors and
removes only empty pinned directories. New files cannot be recursively consumed.
Every root's start/result journal is flushed; partial removals are accounted.

One execution removed337 unchanged cache roots, skipped the changed current
Ruff cache, and had0 partial removals/stop failures. Removed allocation is
1,061,830,656 bytes (0.9889068603515625GiB). Filesystem available bytes observed
at execution rose from64,130,441,216 to65,185,705,984; these observations are
reported separately and not equated with removed allocation. Earlier df changes
include unrelated concurrent/APFS activity and are not claimed as cleanup gains.
Original manifests, actions, receipts and review are under primary ignored
validation/project-stability-cleanup-20261103/.

Independent cleanup-result review passed, SHA256:
`5bb0500b06496a0d6209195fb478bcd41e548a845179e969e81bb1f9aecb8dee`.
It checks337 removed roots,33,904 members and457 directories against the exact
inventory; the changed Ruff root has zero removals and remains intact.

## Complete CI record

PR222 head `77eaee75800c5b96836b15c42603e88ad57777b7` ran CI41628454974,
attempt1, with45 successful jobs. The actual checkout is merge
`a13590af596235179701c8044740bb1d5a474fb3`, tree
`2d652f244143ca318e9ddd194241763996b9c98f`, parents
fab7458a521590fce29ec024855df504a072aece and the tested head above.
Python3.11.17/3.12.15/3.13.17 each recorded28,503 current tests:
28,369pass,134 unchanged baseline skips,0 failures/errors. All61 additions and
the156 PR219 additions passed; no prior node was removed. Historical2294+24
passed with zero skips or retries;83 focused groups/65 zero-skip groups passed.

All45 original ZIPs,21,874,772 bytes, remain unexpanded. The original-ZIP audit
SHA256 is `1952a7a2bec38b3b912c5b0e1d0e080be765c95ef0ade9b77fd212f9924ce7c8`.
Independent original-ZIP reviewv2 passed, SHA256
`d6045f3c392958832158bc46a97f13a21826cd46818fddb78fb1e34fefa71eec`.
That review and final merge/source-equivalence receipts are retained in the
same ignored CI directory. Closing updates affect only HANDOFF.md, the
release backlog and this SDD; every other path/mode/blob must match the tested
head. Record closing and actual merge trees separately from the CI tree.
This evidence reuse does not rerun tests or change the original CI identities.
