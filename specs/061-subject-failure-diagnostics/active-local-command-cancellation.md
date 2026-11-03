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
- [ ] Implement runtime/tools and Controller/worker forwarding in parallel.
- [ ] Independently review source and execute combined focused/static checks.
- [ ] Complete CI, review original results, and integrate main.
