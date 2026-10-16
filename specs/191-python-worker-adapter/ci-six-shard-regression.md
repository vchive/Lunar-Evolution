# Six current CI shards

Date: 2026-10-15. Scope: release regression scheduling and evidence only.

## Reason and retained failure evidence

PR100 run [38582309622](https://github.com/vchive/Lunar-Evolution/actions/runs/38582309622)
did not pass. It tested head `c73650afe3cdc9f1dc3c08ec74d8df12a7b75b01` through
merge `e0040795d03d7d3cb434e51d5ae6ab0b1e847189`, tree
`6302cd65856d36bbdc90a1edf35cfc6218f4cbb1`.

The official check annotations for Python3.11 current-0 (`115917477095`) and
Python3.12 current-0 (`115917477338`) both say:

> The job has exceeded the maximum execution time of 6h0m0s

Their current JUnit reports are absent; cancellation is incomplete regression,
not acceptance. The annotation responses were retained separately with SHA256:

- 3.11: `d069267b81382c38a3f978715c9ee6a7833e3888204c9b3399d0259955d5c3dd`.
- 3.12: `8ef0767894d0f0acfb0783b95c942f5a0ebd01e2bc90780426200f7e41d9f056`.

The original Python3.13 current-0 report has a separate failure in
`test_same_bytes_replacement_during_read_is_rejected[False]` (5123 passed,
31 skipped, one failed). Commit `9db1ffda8bc6ebfd50c50d07e20fbc703b561514`
fixes the test injection to target the opened evidence inode. Changing the CI
topology does not suppress or reclassify that original failure.

The original failed run, cancelled artifacts, successful-role raw audits and
logs remain in the ignored local evidence directory
`.lunar-evolution/reports/pr100-final-ci/1791988766669187000/`. The original
annotations remain under
`.lunar-evolution/reports/pr-current-status/1792018839115682000/pr100-original-cancellation-reason/`.
These records must not be overwritten or replaced with another source's results.

## Contract

The matrix has Python3.11/3.12/3.13 and eight independent roles: focused,
current-0 through current-5, and history, for 24 jobs. Current roles invoke
`tools/run_tests.py --suite current --shard-index INDEX --shard-count 6`.
The provenance role allowlist contains exactly those eight roles.

The existing `sha256-path-utf8-mod-v1` algorithm remains unchanged: SHA256 of
the UTF8 repository-relative test file path modulo the supplied shard count.
The runner already supports arbitrary positive counts, so no runner or product
change is needed. A file and all its class/parameter nodes stay together.
Each old shard `r` is exactly the union of new shards `r` and `r+3`.

Every current job retains the complete collected inventory, selected inventory,
their digests, actual source/tree/import pins, shard index/count and exact
JUnit evidence. The six selected inventories must be disjoint and their union
must equal the full inventory. Selected files are recollected before execution;
JUnit case keys, counts and failure/error/skip elements must still match.
No test is dropped, no empty shard is reassigned and no current retry is added.

The focused regression-runner gate grows from 116 to 124 cases. All other focused
gates, history source pins, history retry rules, failure annotations and artifact
retention remain unchanged. Native admission and product behavior are unchanged.

## Local validation

`tests/test_regression_runner_shards.py` passes all 124 cases on Python3.11,
with zero failures, errors or skips. The eight additional cases cover six-way
partition conservation, three-to-six refinement, and source/inventory/exact-JUnit
recording for each of the six current indices using local inert execution seams.
The existing actual inert pytest and historical compatibility cases also pass.
Pytest emitted cleanup warnings for unrelated pre-existing protected temporary
directories; those warnings did not change the retained JUnit counters.

Ruff, compileall and `git diff --check` pass. YAML/embedded-Python/shell checks
verify the 24 combinations, exact provenance allowlist, shard-count six, 124-case
gate and all 11 shell steps. Comparison against the preceding workflow confirms
that other steps, including the separate producer-recovery 116-case gate, remain
unchanged. No full current regression was run for this local validation.

## Required final CI audit

Before release acceptance, audit the final candidate's actual 24-job run and raw
artifacts. For each Python version, all six current roles must share the same
full inventory/source pins, satisfy the disjoint-union contract, and retain exact
JUnit evidence. Focused and history roles must pass their original contracts.
Cancelled jobs or missing evidence remain incomplete. Earlier successful jobs
cannot establish acceptance for a changed candidate.

Six shards split each old inventory into two parts but cannot guarantee balanced
runtime, a speedup or completion within six hours: a long individual file stays
intact and runner availability varies. Measure the new final-source jobs before
claiming a timing improvement. This change establishes neither sealed runtime
admission nor real solver/production acceptance; P2 remains deferred.
