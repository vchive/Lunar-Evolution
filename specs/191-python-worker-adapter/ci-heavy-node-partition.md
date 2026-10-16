# Explicit heavy-node regression partition

This continuation changes only CI scheduling. Product behavior, original mixed
flows, test assertions, historical pins and job limits remain unchanged.

## Problem and scope

The preceding six-shard schedule hashes complete test-file paths. PR103's official
terminal run retained 21 successful jobs and three cancelled `current-5` jobs.
All three mixed rejection cases belong to the same file and therefore the same
shard. The retained logs place the cancelled jobs inside that file; they do not
by themselves establish the cancellation reason or a final case duration.
The old run is still incomplete evidence and cannot authorize a merge.

Increasing the number of file shards cannot separate these three cases. The
approved change introduces a small explicit exception while preserving whole-file
assignment everywhere else. It does not introduce general node hashing or weaken
the acceptance gate.

## Schedule contract

The new algorithm is `sha256-path-utf8-mod-six-explicit-heavy-v2`:

1. Collect and validate the complete current inventory on every current job.
2. Require `tests/test_rsi_multi_episode_rejection_flow.py` to contain exactly:
   - `test_original_three_attempt_mixed_drs_and_terminal_readonly_replay[V2-T1-RPP]`
   - `test_original_three_attempt_mixed_drs_and_terminal_readonly_replay[V2-T2-PRP]`
   - `test_original_three_attempt_mixed_drs_and_terminal_readonly_replay[V2-T3-RRR]`
3. Assign all other files to the existing six SHA256-path shards. Exclude the
   heavy file entirely from their file selections.
4. Run each explicit heavy node in its own `heavy-0`, `heavy-1` or `heavy-2` job.
5. Require the nine selected inventories to be pairwise disjoint and their union
   to equal the complete current inventory. Missing, renamed, duplicated or added
   nodes in the exception file refuse execution until the schedule is reviewed.

The exception file uses function-scoped `tmp_path`, `monkeypatch`, and the
function-scoped autouse process/network prohibition fixture. Each case constructs
its own controller, ledger and workspace. No module/session fixture is split by
this exception. Future fixture or inventory changes require reviewing this claim.

The old `partition_current_nodes` API, old algorithm identifier, and default
`--suite current` behavior remain available. The complete new CI schedule uses:

```bash
python tools/run_tests.py --suite current --shard-index 0 --shard-count 6 --isolate-heavy --junit-dir .lunar-evolution/test-results
python tools/run_tests.py --suite current-heavy --heavy-index 0 --junit-dir .lunar-evolution/test-results
```

Repeat the first command for ordinary indices 0 through 5 and the second for
heavy indices 0 through 2, each in its separate job/report directory. Running only
the six isolated ordinary shards is not a complete regression. CI also retains
the independent focused and history roles: 11 roles on each of Python 3.11, 3.12
and 3.13, for 33 jobs. `fail-fast: false`, existing job limits and history retry
rules are unchanged.

## Evidence binding

Each job validates selected regular files and recollects its exact execution
selection before running. Ordinary shards recollect and execute complete files;
heavy jobs recollect and execute one complete parametrized node ID. JUnit must
match the selected exact case identities and all counters. No test deselection,
retry or skip is introduced.

Current summaries retain complete and selected node inventories, their SHA256
digests, checkout commit/tree, Python/import provenance and selected files. The
new schedule additionally records the algorithm, full heavy-node allowlist and
digest, and `selection_mode` (`files` or `node`). Ordinary jobs retain
`shard_index`/`shard_count`; heavy jobs record `heavy_index`/`heavy_count` and use
`current-heavy-N.xml` plus `current-heavy-N.summary.json`. Workflow source
provenance, annotations and retained artifacts cover all roles.

## Validation and limits

The runner gate adds local mock/inert coverage for all nine roles, inventory
conservation, deterministic ordinary assignment, strict CLI bounds and mixed-flag
refusal, changed heavy inventories, fresh report preservation, recollection drift,
exact JUnit identities and counters, and real inert pytest node selections. It
preserves the original historical pin/retry contracts. Ruff, compileall and
`git diff --check` accompany the focused gate. A collection-only audit checks the
full candidate inventory without executing any original mixed case.

Local validation on the `ed66333` development base with this change collected
204 runner cases: 204 passed, zero failures/errors/skips. Full collection contained
16,790 nodes; ordinary shard sizes were 3,190 / 2,474 / 3,072 / 2,249 / 3,206 /
2,596 and heavy shard sizes were 1 / 1 / 1. The complete inventory SHA256 was
`3fd8592d867184f693fc3346b3faee5b201eb86ce1f93bab55b88cc12c60e0f2`.
The collection audit verified exact union and pairwise disjointness. These counts
belong to that development base; integration onto another base requires its own
collection audit. Ruff over `src tests tools`, compileall over the same paths, and
`git diff --check` passed. No long-flow execution was performed.

This scheduling fix is not a performance or production acceptance claim. A heavy
case may itself remain slow; only a new complete official run can establish the
candidate's CI outcome. The old cancelled run and the separately frozen server
run remain immutable evidence. No WebAgent, remote evaluator, model, real solver,
producer, toolchain or runtime campaign is invoked by this development validation.
`production_admission` remains false.
