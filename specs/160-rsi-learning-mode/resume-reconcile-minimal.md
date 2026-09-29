# Controller resume 最小闭环（阶段 1）

`RSILearningController.resume(run_id)` 的第一版只负责恢复已持久化副作用，不启动新的 solver。
它读取 run checkpoint、episode head 和 `RSILedger.episode_result()`，并在同一个
`controller_lock(run_id)` 中执行 evidence-bound reconcile。

## 行为

1. `completed`、`failed`、`cancelled`、`budget_exhausted` 的 run 只读返回既有 terminal 结果；不得重新执行或创建 episode。
2. `paused`/`running` 的 run 查询 `episode_ids_for_run(run_id)`。若当前 episode 已有完整 request/result wire：
   - `result.status == completed` 时调用 `reconcile_episode(..., worker_state="completed", result=result, evidence=...)`；
   - `result.status in {failed, timed_out, abandoned, cancelled}` 时调用对应终态 reconcile，保留独立 evidence journal；
   - reconcile 成功后只返回既有 terminal evidence，不调用 gateway。
3. episode 为 `unknown` 且没有完整 result 时，抛出 `rsi_unknown_reconcile_required`；不得猜测失败、创建新 episode 或启动新 solver。
4. episode 为 `running` 且没有 result 时，resume 只能返回 `recovery_required`/`paused`，等待外部 reconcile；第一版不自动重启 side effect。
5. `observed_fingerprints`、绝对 deadline 和 persisted budget 必须在任何 reconcile 或 replay 前校验；不匹配抛固定 drift/budget 错误。
6. 所有动作在 per-run nonblocking controller lock 内完成；锁冲突返回 `rsi_controller_busy`。

## 幂等和不变量

- 相同 episode/request/result 的第二次 resume 只读返回相同 record/receipt digest。
- unknown 没有 evidence 时不能变成 completed，也不能变成 failed 以绕过 gate。
- terminal receipt 和 reconciliation journal 必须先持久化，再推进 run checkpoint；任一步失败都回滚。
- resume 不消耗新的 solver/evaluator invocation，不扩大预算，不重置 deadline，不创建新的 target/practice identity。
