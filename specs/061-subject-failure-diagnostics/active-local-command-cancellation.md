# Active local command cancellation

Status: software validated; final integration recorded separately, 2026-11-04. Baseline main is
`d497bafd541c1c11156c7d85242a8551044d9e28` (PR222).

## Problem and scope

AgentLoop checks its cancellation event before and after a tool call. The local
command runner already supports a guard before launch and during bounded polling,
but LocalToolRegistry does not pass an active guard. Direct runtime cancellation
can therefore wait for the original command timeout. Existing Controller and
WorkerService explicit cancellation already have owned-process cleanup; this
change does not replace that authority or establish that those paths are broken.

The existing continuation guard is a stage-boundary hook. Controller uses it to
clean a previous retained process before new work. Polling it during a legitimate
command would terminate that command. Keep this behavior separate from active
stop checks; do not weaken the previous-process cleanup gate.

## Contract

- Add an optional `set_active_continuation_guard` hook to AgentLoop and local tools.
  Legacy `set_continuation_guard` keeps its boundary behavior. Installing either
  hook must not implicitly install the other. Validate callable-or-None.
- AgentLoop composes its own cancellation event with the active hook. Its own
  cancellation must remain effective without an external hook and after the hook
  is cleared. A new invocation retains the existing cancellation reset behavior.
- Local commands pass only the active-safe hook to the existing runner. Preserve
  its original timeout, environment, argv, output bounds, observer and release
  callbacks, polling interval and exact-group cleanup. On exceptional exit before
  normal termination, invoke the existing private-group termination even if the
  leader has already exited: descendants may still hold the output pipes. Retain
  the same reaping/release proof and authority; no runner redesign.
- Active guard errors must propagate as the original exception object after
  runner cleanup. Tool dispatch must not convert them to a failed ToolResult or
  depend on the guard raising again. Preserve existing ordinary tool-error results
  and natural propagation of interrupts and other BaseException controls.
- Controller splits its existing checks: active checks retain the same run/parent
  stop conditions (and contract solve-control budget check); boundary checks call
  those checks followed by `ensure_attempt_process_released`. Install and clear
  both hooks at the existing scopes. An active check never runs stage cleanup.
- RuntimeAgentAdapter forwards the optional new hook when supported; legacy
  runtimes remain compatible. WorkerService installs its already active-safe
  owner/stop/cleanup check into both hooks and clears them at attempt completion.
  No new ownership policy, attempt status gate, callback concurrency or scheduler.
- Cancellation rejects the interrupted invocation: no remaining tools, subsequent
  model request, final result or new success publication. Unconfirmed cleanup keeps
  the existing retained registration rather than claiming release.

No model/evaluator invocation, provider retry, JSON repair, timeout increase,
distributed service or native RSI admission belongs to this slice. Real-model P0
and native RSI P1 remain open; production/publication authority remains false.

## Development and validation

Parallel ownership: AgentLoop/tools implementation; Controller/adapter/worker
implementation and wiring tests; independent local-command cancellation tests.
Only add new tests; preserve existing acceptance assertions. Review integrated
source before one combined focused regression, then Ruff, compileall and diff
checks. Use fake model turns and local subprocesses, never remote evaluation.

Verify active/boundary separation with fake runner callbacks; prelaunch refusal
starts no process; a one-shot stop/budget/callback failure retains exact exception
identity; ordinary tool errors still yield failed tool results. A real command
must confirm launch before another thread calls runtime.cancel, then prove child
reaping/group disappearance before the call returns, bounded latency below the
original timeout, and no later side effects/model requests. Verify a normal
Controller-owned command survives active polling, prior retained-process cleanup
still gates the next stage, hook clearing/reuse works, and unconfirmed cleanup
retains ownership. Preserve original failures and perform one final CI matrix
after integration. Check any source pins against the actual changed paths.

## Tasks

- [x] Inspect main, source, existing cancellation tests and previous audit.
- [x] Define split-hook contract and preserve existing cleanup boundaries.
- [x] Implement runtime/tools and Controller/worker forwarding in parallel.
- [x] Independently review source and execute combined focused/static checks.
- [x] Complete CI and independently review original results.
- [x] Verify unchanged software at document closure and record actual main integration separately.

## Initial local regression and correction

Frozen `1f0e05d3e0eee8311418008726483a102bbea53c` ran one22-file batch:
430 tests,421 passed,9 failed,0 errors/skips,31.772470499854535 seconds. Originals
remain under ignored validation/active-local-command-cancellation-20261104/local/.
Eight failures concern new/previous active cleanup and the existing deterministic
reap-wait assertion. A single instrumented local runner probe showed two group
kill attempts; the second returned false even though subsequent group-exit proof
was true, preventing release. Do not infer an OS errno from that boolean trace.

The correction captures whether the leader still needs reaping before signalling,
terminates a previously unterminated private group once even after leader exit,
and retains the existing bounded wait and release conditions. No test assertion
or cleanup proof is weakened. The ninth failure is the test harness: its child
script ran pytest at import time, so multiprocessing spawn reentered the suite.
A separate create-only childv2 puts execution behind `if __name__ == "__main__"`.
The failed original remains failed; the corrected source/harness need a fresh
combined run, not a relabelling of the first result.

Frozen `c33b7aad3e479e723b032e2529e5188f396c248f` then ran the same22 files
once using the corrected entrypoint:430 passed,0 failures/errors/skips,
23.92281537503004 seconds,rc0,reaped,no watchdog signals. All52 new cases passed;
existing tests and all test source bytes remained unchanged by the correction.
The whole original failed batch and successful corrected batch are separate.
Ruff over src/tests/tools, compileall and git diff --check passed; the newly
generated compile cache was removed (31,571,862 file bytes).

Fixed producer/build registry inputs are unchanged: the26 unique fixed assets
retain original size/SHA and baseline bytes, with no overlap with the six changed
application modules. No generator, source pin or old attempt registration was
refreshed. A future real acceptance must register the new source separately.
No new model or evaluator call ran; complete software CI and integration remain.

## CI compatibility correction

The first CI run41684789946/attempt1 on head88f1c4b6 exposed nine existing
`test_command_argv_diagnostic` parameter failures: an unconfigured tools registry
passed the extra `continuation_guard=None` keyword to the process seam. Original
JUnit and ZIP remain in the separate ignored `ci/` directory. This is a confirmed
compatibility defect, not a flaky process result; the failed run is not acceptance.

The correction omits the optional keyword entirely when no active hook is
installed, and keeps forwarding the wrapper when one exists. The existing exact
kwargs assertions remain unchanged. Only the new clear-hook fake reads the
optional key with `get`; its assertions and all52 new cases are unchanged.
Independent static review confirms AgentLoop still always installs its internal
active check, preserving cancellation after clearing an external hook. Targeted
compatibility checks and a fresh final matrix remain required.

## Final validation and integration

Frozen `d807cc617eeb5d435a902c52a24425ac9688dbdd` passed 123 cases in five
complete compatibility files, with 0 failures/errors/skips, in 2.220900374930352
seconds. All 52 new cases passed; 234 loaded modules match frozen source/Git blobs.
Ruff, compileall and diff checks passed; temporary compilation output was removed.
The first local batch and canceled CI remain separate failed evidence.

CI `41692008154`/attempt 1 completed with all 45 jobs successful. Python 3.11.17,
3.12.15 and 3.13.17 each ran 28,555 cases: 28,421 passed and the original 134 skipped,
with exact previous skip identities/reasons. All 52 additions and the previous 61
PR222 additions passed; no old node disappeared. History 2,294 + 24 passed with zero
skips or retries; 83 focused groups, including 65 zero-skip gates, passed.
The 45 original ZIPs total 21,898,389 bytes and remain unexpanded in `ci-corrected/`.
Original audit `ccd8665dee532faf23cd6c5b9c3e37127d677a81172324048f2a7d730ab24b24`
and independent review
`05e8b76208ca089b505298cacf2085c5562a94a951e23a2998d62acf606b7641` passed.
Exact tested merge `5a29e77716ad4089203f4c537f0a83204aeb268d` has tree
`a82ef0b0e36ab2321b8579042e76ad0d74e7a155`.

Closure changes only this SDD, HANDOFF.md and docs/current-release-backlog.md.
Compare every other tracked path/mode/type/blob with the tested head before merge;
record the actual PR/main/parents/tree in a separate integration receipt. Reuse
this matrix for byte-identical software rather than repeating tests for Markdown.
Real-model E2E P0 and native RSI P1 remain open; no model/evaluator ran and
production_admission/online_publication remain false.
