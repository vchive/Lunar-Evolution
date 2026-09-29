# Feature 160 阶段 1：可恢复 RSI 契约

**状态：规格与契约测试**

本文把 `RSILearningController` 从“可以把一次 DRS/BRS 跑完”推进到“中断后可以安全继续”的最小行为写成可审计契约。它不是对当前代码状态的描述；当前代码已有 append-only ledger、CAS 状态迁移和 episode record，但还没有完整的 controller-level `resume()`、unknown reconcile gate、统一预算持久化和 fingerprint drift gate。

本阶段只使用本地 fixture、SQLite ledger 和 loopback/subprocess 证据。它不要求 WebAgent、远程 evaluator、真实 OpenEvolve/Shinka campaign 或新的模型请求。

## 1. 范围和非目标

阶段 1 必须覆盖：

- run-level checkpoint 与 controller-level `resume(run_id)`；
- target、practice、verify、memory commit、transfer 各阶段的可恢复边界；
- `unknown` quarantine 与显式 reconcile gate；
- contract、evaluator、environment、memory、solver、actor 和 budget fingerprint 的漂移拒绝；
- 递归深度、episode 数、solver/evaluator/verifier/transfer 调用数和总墙钟预算的持久化；
- 已知 terminal receipt、memory commit 和 transfer receipt 的幂等复用。

本阶段不实现 clean-room evaluator、完整 producer 生命周期、分布式 scheduler、Web UI、复杂 curriculum 或模型权重更新。这些能力必须在恢复契约之上单独验收。

## 2. Durable run checkpoint

每次控制面边界都追加一个不可变 checkpoint；旧记录永远不原位修改。checkpoint 至少包含下面的逻辑字段：

```json
{
  "schema_version": "1",
  "kind": "rsi_run_checkpoint",
  "run_id": "rsi-...",
  "mode": "drs|brs",
  "status": "created|running|paused|completed|failed|cancelled|unknown",
  "phase": "target|practice|verify|commit|transfer|finished",
  "current_episode_id": "episode-...",
  "current_wave": 0,
  "current_ordinal": 0,
  "contract_sha256": "<sha256>",
  "evaluator_sha256": "<sha256>",
  "environment_sha256": "<sha256>",
  "memory_snapshot_sha256": "<sha256>",
  "solver_id": "mock",
  "solver_fingerprint": "<sha256>",
  "actor_fingerprint": "<sha256>|null",
  "budget": {
    "max_depth": 3,
    "max_practice_episodes": 8,
    "max_target_attempts": 4,
    "max_solver_invocations": 16,
    "max_evaluator_invocations": 16,
    "max_verifier_invocations": 16,
    "max_transfer_invocations": 4,
    "deadline_at": "2026-09-30T00:00:00Z",
    "unknown_retries": 0,
    "unknown_retry_limit": 1
  },
  "consumed": {
    "depth": 0,
    "practice_episodes": 0,
    "target_attempts": 0,
    "solver_invocations": 0,
    "evaluator_invocations": 0,
    "verifier_invocations": 0,
    "transfer_invocations": 0
  },
  "last_side_effect_key": "run/episode/request|memory/parent/episode/receipt|transfer/run/target/snapshot/solver",
  "previous_record_sha256": "<sha256>|null",
  "record_sha256": "<sha256>"
}
```

`budget` 是 run contract 的一部分，创建 run 后不可扩大。`consumed` 只能单调增加；重启或重试不得把计数归零。`deadline_at` 是绝对时间，resume 不能重新计算一个新的完整墙钟。若旧实现需要额外字段，应通过 schema 版本升级并保持未知字段 fail-closed。

checkpoint 的 `phase` 表示下一个需要处理的控制面边界，而不是“模型可能正在做什么”的猜测。外部 side effect 开始前必须先写入含有 request digest 的 checkpoint；side effect 完成后必须先持久化 receipt，再推进 checkpoint。进程在两者之间退出时，run 进入 `unknown`，不能直接跳到下一个 episode。

## 3. Resume API 和恢复顺序

控制器提供等价于下列语义的入口（参数名称可以因实现而不同，但行为不能改变）：

```python
controller.resume(
    run_id,
    *,
    now=None,
    observed_fingerprints=None,
    budget_policy=None,
)
```

恢复顺序固定为：

1. 读取 run head 和当前 episode/wave journal；校验每条记录的 digest、lineage 和 CAS parent。
2. 校验 run 状态。`completed`、`failed`、`cancelled` 只能返回既有终态；`unknown` 必须先通过 reconcile；`paused`、`running` 才能继续执行。
3. 校验 fingerprint 和 budget。任何不兼容漂移都在启动 solver/evaluator 前拒绝。
4. 读取 side-effect receipt。已有完整 terminal receipt 时只恢复其结果，不再次调用 solver 或 evaluator。
5. 对没有 terminal receipt 的 episode 继续同一 `episode_id`、同一 request digest 和同一 memory snapshot；不得创建第二个 target/practice identity。
6. 完成验证、commit 或 transfer 后追加新的 checkpoint，再决定下一个 phase。

恢复结果必须指出 `resumed_from_record_sha256` 和 `resume_reason`。这两个字段用于审计，不得改变 request 或 evidence digest。

## 4. Side-effect 幂等性

每类外部副作用有稳定幂等键：

| 副作用 | 幂等键 | 已有 terminal evidence 时的行为 |
| --- | --- | --- |
| solver/evaluator execution | `run_id + episode_id + request_sha256` | 读取并复用唯一 receipt；禁止再次执行 |
| verifier decision | `episode_id + evidence_sha256 + verifier_fingerprint` | 读取并复用同一 decision；证据或 verifier 改变则 drift |
| memory commit | `parent_snapshot_sha256 + episode_id + verifier_receipt_sha256` | 已提交则返回原 snapshot；不同 parent 走 CAS 失败 |
| frozen transfer | `run_id + target_id + memory_snapshot_sha256 + solver_fingerprint` | 已有 transfer receipt 则只读返回 |

同一个幂等键收到字节不同的 receipt、不同的 request 或不同的 fingerprint 时必须 fail closed，并保留冲突原因。成功 resume 不得通过复制旧 receipt、清空预算、换用新的 episode ID 或省略 evidence 来绕过幂等检查。

## 5. Unknown reconcile gate

`unknown` 表示控制面无法证明 worker 是否已经完成；它不是失败，也不是可直接重试的信号。run 或 episode 进入 `unknown` 后：

- 禁止新 target、practice、retry、memory commit 和 transfer side effect；
- ledger 只允许追加 reconcile 记录，不能直接把状态改回 `running`；
- reconcile 必须核对 process ownership、PID/PGID 或等价进程证据、heartbeat、workspace、request/receipt 文件、evaluator evidence 及全部 fingerprint；
- reconcile 只能落到以下明确结论：`already_terminal`、`recoverable`、`abandoned`、`drifted`、`manual_review`；
- `already_terminal` 只在 receipt 完整且绑定精确时复用；`recoverable` 继续原 episode；其他结论必须终止或等待人工处理；
- 未通过 reconcile 前，DRS 不得进入 practice/retry，BRS 不得合并 wave 中任何 child。

worker 仍存活、进程已退出但 receipt 完整、receipt 缺失、workspace 被替换和 fingerprint 漂移至少要有不同的诊断码。reconcile 本身也必须是 append-only、CAS 保护和幂等的。

## 6. Fingerprint drift gate

resume 前必须比较以下绑定：

```text
contract_sha256
evaluator_sha256
environment_sha256
memory_snapshot_sha256
solver_id + solver_fingerprint
actor_fingerprint（若存在）
budget_digest / deadline
```

阶段 1 默认采用 exact-match policy。任意值缺失、改变或无法重新计算都拒绝复用旧 terminal receipt，并将 run/episode 标记为 `drifted` 或 `manual_review`。未来若允许兼容 patch，必须显式注册 policy、记录旧/新 digest 和理由；不能由 resume 调用方临时放宽。

推荐固定诊断码：`rsi_resume_contract_drift`、`rsi_resume_evaluator_drift`、`rsi_resume_environment_drift`、`rsi_resume_memory_drift`、`rsi_resume_solver_drift`、`rsi_resume_actor_drift`、`rsi_resume_budget_drift`。

## 7. Budget、深度和终止

每个 run 维护 planned/consumed/remaining 三组可查询值。所有 child episode 从父 run 的剩余预算派生；child 不能增加父预算。以下任一条件达到上限时，控制器必须追加明确终态并停止创建新 episode：

- `now >= deadline_at`；
- `depth >= max_depth`；
- practice、target、solver、evaluator、verifier 或 transfer 调用数达到上限；
- unknown reconcile 次数达到 `unknown_retry_limit`；
- no-improvement 或 mode-specific wave 上限达到。

预算耗尽的终态应区分 `timed_out`、`budget_exhausted`、`unknown` 和 `failed` 的原因。预算检查必须发生在每个 side effect 前和 resume 后；失败重试不能通过省略 `budget`、复制旧 request 或新建 run 来放宽原策略。

## 8. 验收矩阵

阶段 1 的 provider-free 验收至少包含：

1. 在 target、practice、verify、commit、transfer 前后各注入一次中断；resume 只执行缺失的 side effect。
2. 已有 terminal receipt 的 target/practice/transfer 重启两次，调用计数不增加，返回同一 receipt digest。
3. `unknown` worker 分别覆盖存活、已退出有 receipt、缺 receipt、workspace/fingerprint 漂移；未经 reconcile 均不能继续。
4. 修改 contract/evaluator/environment/memory/solver/actor/budget 任一绑定，resume 在 solver 启动前拒绝。
5. 让 deadline、depth、practice 和 nested solver budget 耗尽；不创建额外 episode、不提交 memory、不启动 transfer。
6. 两个并发 resume 使用同一 checkpoint；只有一个 CAS 成功，另一个得到 `rsi_record_parent_conflict` 或等价固定错误。

测试可以先以 `xfail(strict=False)` 形式落地，直到 controller/store API 完成；通过时应自动转为绿色，不改变现有 provider-free suite 的成功标准。

