# Validation

Source implementation and independent review are complete; final-head Ubuntu CI and
main merge remain pending at this source commit. This feature does not close all P0/P1.
Only inert local filesystem/C/pipe/socket and provider-free fixtures were used.

## Local evidence

- Root final composition: `/tmp/lunar181-root-final-composition.xml`,545cases=
  415passed/130macOS platform skips/0failures/errors. Includes original host owner,
  new wire/input/C tests, historical gates/drain, native bootstrap/attempt and both
  input contracts. Linux-only code was source-reviewed, not executed by these skips.
- Final grant/gate focus: `/tmp/lunar181-final-grant-focus.xml`,238cases=
  137passed/101skips/0failures/errors. Final Popen fixture source repair is separately
  reviewed and `/tmp/lunar181-control-final-fixture.xml` retains its local rerun.
- Independent host review: `/tmp/lunar181-independent-host-review.md`; reports the
  Unicode fixed-code defect, now repaired and covered by15passed independent probes.
- Independent C/caller review: `/tmp/lunar181-independent-boundary-review.md` and
  machine evidence JSON;88cases=78passed/10skips/0failures/errors. Static protocol-role
  type/direction validation was a spec gap, now repaired before control read/close,
  covered by18new Linux-only anonymous-pipe/FIFO/file/async negatives. Source review
  also corrected the Popen observer to preserve registration's isinstance contract.
- Host141tests and extractor66tests independently passed. C module98cases all
  platform-skip on Darwin; its broader250case suite has11passed/239skips. These
  suites overlap the root composition and are not summed into a unique test total.
- Ruff acrosssrc/tests/tools, compileall, git diff --check,698unique importable exports,
  YAML parse and three grant-objects XML preservation/annotation bindings passed.
  Strict actual Darwin clang compilation passed; it is not Linux branch compilation.

## Initial failures retained

`/tmp/lunar181-control-first.xml` retains the first fixture failure/error: a nonexistent
owner.close API and a substituted path left in place at owner context exit. The tests now
use an actually expired context and restore the inert replacement after asserting refusal.
C initial compile diagnostics and first pytest XML remain at `/tmp/lunar181-c-first-compile.log`
and `/tmp/lunar181-c-first-tests.xml`. Initial evidence is not rewritten as success.
First Linux CI head e48ac34/run37707855913 exposed one fixture setup error: the pre-persist
drift negative used `monkeypatch.setattr(module, "subprocess.Popen", ...)`, which is not a
module attribute. Its dotted import path is now patched correctly. The first196case grant
XML/logs are preserved; the98C cases and other Python cases executed, but the failed job
does not prove the downstream phases. The fix uses a new source head/run, not a retry.
The next head4974538/run37708266284 passed the preceding ten native phases but retained
two trusted-adapter fixture failures: observers still intercepted the v1 path-policy
builder/encoder, while Linux now uses original grants/controlv2. The native target itself
exited zero and produced its verified marker. Observers now inspect the actual platform
control's read grants and argv, preserving all least-read, no-directory, no-argument-change
and host-file refusal assertions. All three first XML/logs remain separate; downstream
native cleanup/current/archive/frozen phases were not executed in that failed run.
Existing immutable-runtime fixture garbage can emit macOS cleanup warnings; they do not
change XML outcomes. No historical test retry is used to erase a first failure.

## Required Linux CI

The workflow retains grant-objects(196), grant-anchors(141), historical native phases,
and full current(11319), archived(2294), frozen123(24) XML/logs for Python3.11/3.12/3.13.
Expected Linux current platform skips are82; descendants74/1skip, other old phase counts
remain unchanged. Raw case/skip inventories, failures/errors, logs and ZIP digests must be
audited against the actual tested checkout/parents/tree and final source head. A newer
synthetic merge or prior PR passing is not evidence for this final head.

New Linux cases verify independent malformed graph/role/count/path/identity refusals,
original ready/release/ancestor substitutions, static/dynamic reserved aliases, primary
channel/broker types, original-FD Landlock and held CWD, protected READ_FILE without EXECUTE,
two closure phases with O_PATH/O_RDONLY leaves, ordinary output and broker positives, and
formal pre-persist/through-cleanup/claimed-unknown lifetime. No actual models, solvers,
WebAgent, remote evaluator, company platform or campaign are executed.
