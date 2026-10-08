# Validation boundary

Source is implemented locally and independently reviewed before submission; no
Linux execution or main acceptance is claimed. Root focused composition in
/tmp/lunar185-root-composition.xml:195 cases=70 passed/125 Darwin skips/0 failure/error.
The new mq module now collects 44 cases: 4 cleanup mocks pass locally and 40
Linux-only cases skip. The cleanup review found the first fstat outside finally;
it now enters cleanup on error, supplements missing identity only from the held
original FD, never refreshes recorded identity, rejects foreign-name unlink and
preserves the primary exception. Independent review passed at test SHA
1e506657a390232314fbddf972fb4f88dba703e4475477615428c26874b9aa9f.
Ruff over src/tests/tools, compileall, git diff --check, workflow YAML and strict
Darwin bootstrap C compilation passed. Author C literal syntax checks used numeric
shims only and are not Linux execution evidence.

Tests cover exclusive parent-owned mode0600 queue send/receive/unlink baseline
and filtered/formal refusal, fixed EPERM for all six native entries and the two
i386 time64 entries, omitted-header compilation, ordinary pipe/file/fork/thread
and v2 guardian/broker/FD closure composition. On x64/ARM the four parameterized
i386 time64 cases explicitly skip; native i386 acceptance remains separate.

Raw author first XML/log and evidence:
/tmp/lunar185-posix-mq-author-first.xml,
/tmp/lunar185-posix-mq-author-first.log,
/tmp/lunar185-posix-mq-author-final-evidence.json.
Root's incorrect system Python 3.9 invocation failed collection and is retained
as /tmp/lunar185-root-composition-tooling-failure.xml; Python 3.11 had no pytest.
Neither is runtime enforcement evidence. Final local composition uses Python 3.13
with the checkout src explicitly on PYTHONPATH.
Final root composition /tmp/lunar185-root-composition-final.xml has 199 cases:
74 passed, 125 Darwin skips, zero failure/error. Ruff, compileall and diff checks
pass. Existing Darwin immutable snapshot pytest cleanup warnings remain; they
are not queue execution or failed test cases.
After including Feature183 final 5561c30 as 9269745, focused composition plus the
original-owner cancellation fixture passed in /tmp/lunar185-root-postsync.xml:
200 cases, 75 passed, 125 Darwin skips, zero failure/error. The preserved log is
/tmp/lunar185-root-postsync.log. Ruff, compileall and diff checks passed again.
The workflow adds dedicated posix-mq.xml pytest/annotation/upload while keeping all
existing phases. Exact-head three-version Linux raw XML/log/ZIP, source inventory
and tested parents/tree remain required. PR18 must independently pass before
this slice is eligible for main merge; no earlier CI or Darwin skip is borrowed.
