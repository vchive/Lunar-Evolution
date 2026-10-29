# Withdraw the automatic native CI traceback timer

Status: implemented; affected runner tests passed, 2026-10-29.
Baseline: `3fab9318`. Complete successor CI remains required.

## Evidence

New CI run 40898688099 passed the former pre-test output interval. Python 3.11
heavy-0/heavy-2 and Python 3.12 heavy-6 then terminated with SIGSEGV (-11) approximately
302–303 seconds into actual execution, after their five-minute native traceback
timer began printing incomplete stacks. Python 3.12 current-3 later also ended
with SIGSEGV after a partial timed dump in its three-child publication test;
its whole-shard pytest duration was 1,633.518 seconds, not the duration of that
individual test. None produced a JUnit report. Their
original summaries, raw logs, artifacts and unsuccessful statuses are retained.
Python 3.11 heavy-6 in the same run printed a complete stack and naturally
passed its original case in 372.96 seconds. The 600-second business limit was
not reached by the crashing processes.

The locked pytest 9.1.1 plugin calls native
`faulthandler.dump_traceback_later(..., exit=False)`. It does not request process
termination. Official CPython 3.11 source shows its watchdog traverses thread
frames without the GIL. This supports a race hypothesis but does not establish
the exact source of these crashes. Partial frames must not be interpreted as a
complete valid product call chain.

An isolated two-second JSON/ephemeral-function diagnostic on 5090gpu's Python
3.12.3 initially ended with SSH status 255 and a partial native dump, without
completion. A later controlled experiment separately ran no observer, the
native observer, and a Python-thread frame sampler: all three completed with
status 0. These were synthetic local CPU loops, not product/test-case replays;
the first failure remains unresolved and the controls do not prove a reliable
reproduction. No exact matching official interpreter defect has been confirmed.

## Change

Withdraw the newly introduced automatic `faulthandler_timeout` override from
`--diagnostics`. Preserve verbose progress, flushed stage events, compact
console summaries, original full artifacts, and bounded binary logging. Do not
add a replacement background thread: installed native admission checks require
the original single-thread state, and older Python versions have separate
`sys._current_frames()` limitations. Existing interpreter fault reporting is
unchanged. No test data, identities, selection, ordering, budgets, retries,
termination behavior, JUnit or aggregate rule changes.

Both original installed admission paths also require a single Linux task in
`/proc/self/task`, in addition to `threading.active_count() == 1`. A native
watchdog adds an OS thread even without registering a Python Thread object.
Removing this automatic timer therefore also restores admission compatibility;
that is not evidence that this gate caused the four observed SIGSEGV failures.

This removes an optional diagnostic risk. It is not a claim that the underlying
long-running path, interpreter crash or all CI failures are fixed. Keep the
current CI running while recording its remaining original results; do not
automatically replay consumed mixed acceptance runs. A successor complete CI
must independently pass before main integration.

## Validation

Check exact default and diagnostic pytest arguments and failure propagation.
Replace the native-dump demonstration with a naturally ending inert subprocess
that forbids arming a native timeout, while preserving exact successful JUnit
and original case inventory. Run the affected diagnostics and runner contracts
as one batch, then Ruff, compileall and diff checks. Do not rerun unaffected
streaming/logger cases after an unchanged prior pass.

## Verification

Frozen tree `94546700622f115e73bc2f2facfadeea39df6a47`: three complete affected
runner files, 315/315 pass, zero failure/error/skip, 27.781622 seconds on Darwin,
one actual test batch and zero retry. All 2737 tracked bytes and modes stayed
unchanged. Test counts are unchanged; one diagnostic identity was renamed to
describe the new no-timer contract. The prior unaffected logger result remains.

The first harness incorrectly expected 313 nodes; its collection-finish hook
refused the actual 315 before any test protocol dispatched. That internal error
and its zero-body XML remain preserved. Only the external harness count was
corrected; product/test source stayed on the same frozen tree. This is 315
passing identities, not 630 executions or an additional full-CI acceptance.
Evidence: primary ignored `validation/ci-followup-20261029/` under both
`observer-withdrawal-focused*` directories. Preserve earlier SIGSEGV results.


## Separate SQLite fixture correction

The same original CI produced one ordinary failure in Python 3.12 current-1:
3,646 cases, 3,639 passed, one failure, six skips and zero errors. The failing
mailbox inspection fixture observed an absent WAL becoming empty; database
bytes were unchanged. Preserve that original failure and all six skips.

The fixture now explicitly owns a mode=ro baseline connection, executes a real
sqlite_master read before the baseline, and holds that connection until after
inspection and exact DB/WAL byte and inode comparisons. No product/store code
changed, no absent/empty normalization, immutable connection, connection pool
or SQL-write allowance was introduced. See durable-recovery-evidence.md for
the scoped SQLite contract.

Frozen tree `1409840eb516d8c10eaa7457a362470496f3ef1e`: both complete mailbox
and ledger connection-lifetime files passed, 45/45, zero failures/errors/skips,
1.136577 seconds on Darwin, one dispatch and zero retry. All 2,737 tracked
source bytes/modes remained unchanged. This covers a separate 45 identities
from the earlier 315 runner cases; it is not a complete final-head CI result
or a Linux/root acceptance. Complete fresh CI still gates main integration.


## Verbose reporter fixture scope

The original Python 3.11 current-2 process exited nonzero without XML because
a provider-free parser test left global denial doubles active until fixture
teardown. Pytest verbose call reporting occurs earlier and reads terminal-width
environment variables. The test's denial then also blocked error formatting and
JUnit creation. The parser call itself had returned successfully; that progress
line does not constitute a complete shard result.

Only that test's instrumentation lifetime changed: all original API denials,
input pins and result assertions now live inside one monkeypatch.context(),
which restores APIs before reporting. Frozen tree
`2d1dcf7cf046e063745052ef36ec8c77ec5f473f`, 2,738 tracked files: the complete
startup-closure file passed 67/67 in verified effective verbose mode with exact
JUnit, zero errors, failures or skips, 0.789859 seconds on Darwin, one dispatch
and zero retry. An earlier ordinary-progress 67-case pass remains retained;
its harness -v was offset by default -q, so only the external harness addopts
was corrected, without software changes or double-counting identities.
Source bytes/modes were unchanged. This is a third disjoint focused domain,
not a replacement for the successor full CI. See provider-free-test-scope.md.
