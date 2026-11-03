# Active local command cancellation

Status: implementation in progress, 2026-11-04. Baseline main is
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
- [ ] Complete CI, review original results, and integrate main.

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
