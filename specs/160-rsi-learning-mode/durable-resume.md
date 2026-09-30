# Feature 160 阶段 1：可恢复 RSI 契约

**状态：本地 RSI 组合 289 项通过，包含 v2 DRS/BRS、CLI 和 transfer 基础恢复矩阵；尚有 callback/unknown transfer receipt 恢复接口开放，详见 validation.md。**

本文规定 `RSILearningController` 的本地可恢复行为。当前代码已有 append-only ledger、CAS、controller lock、持久化 request/result、v2 DRS/BRS plan 和恢复驱动，不能再把它描述为只有只读 resume。与此同时，模块存在不等于整份验收矩阵已经完成；`tasks.md` 将阶段 1 的实现和最终集成验收分开记录。

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

每次控制面边界都追加一个不可变 checkpoint；旧记录永远不原位修改。v2 run checkpoint 的主要结构如下（嵌套对象省略内容，实际 wire 以代码为准）：

```json
{
  "schema_version": "2",
  "kind": "rsi_run_checkpoint",
  "run_id": "rsi-...",
  "mode": "drs|brs",
  "status": "running|completed|failed|cancelled|unknown|budget_exhausted",
  "phase": "created|launch|evaluated|commit|committed|terminal",
  "current_episode_id": null,
  "plan": {},
  "pins": {},
  "root_snapshot": {},
  "memory_snapshot": {},
  "budget_state": {"planned": {}, "consumed": {}, "remaining": {}},
  "intents": {},
  "executions": {},
  "decisions": {},
  "judgments": {}
}
```

`plan` 固定 DRS 次数上限或 BRS wave、practices 和并发配置；`intents` 绑定原 episode 与请求，`executions` 保存结果及 verifier。run head 固定初始 component fingerprints 和预算 policy；controller journal 单独维护 hash-chain 与 CAS digest。绝对 deadline 的实际字段是 `deadline_unix`，预算上限包括 `max_depth`、各 invocation limit 和 `max_unknown_retries`。planned 不扩大，consumed 单调增加，resume 不重置剩余量和 deadline。

checkpoint 的 `phase` 表示持久化控制面边界。solver 启动前先预留预算、保存 intent，再由 runner 写入 running episode；gateway 返回后先保存结果，再推进 episode 和 journal。进程退出不会自动把所有记录改为 unknown；恢复根据持久证据判断可继续、需恢复或需 reconcile。已发起且结果未知的请求不能重发。

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
2. 校验 run 状态。`completed`、`failed`、`cancelled`、`budget_exhausted` 复用既有终态；已落盘 terminal journal 需要幂等补齐 run head，不能因恢复时 deadline 已过而改写结论；`unknown` 必须先通过 reconcile。
3. 校验 fingerprint 和 budget。任何不兼容漂移都在启动 solver/evaluator 前拒绝。
4. 读取 side-effect receipt。已有完整 terminal receipt 时只恢复其结果，不再次调用 solver 或 evaluator。
5. 对只有 intent、尚无 running episode 的请求，可以启动同一 ID 和同一 request。已有 running/unknown 而无结果证据的请求必须停在 recovery/reconcile gate。只有完整 v2 plan 才允许继续后续尚未启动的 planned episode；旧 checkpoint 不猜测计划。
6. 完成验证、commit 或 transfer 后追加新的 checkpoint，再决定下一个 phase。

审计使用 run/episode revision、controller hash-chain、reconciliation journal 和固定错误码。`LearningRunResult` 当前不承诺 `resumed_from_record_sha256` 或 `resume_reason` 字段，不应将草案字段当成已实现接口。

## 4. Side-effect 幂等性

每类外部副作用有稳定幂等键：

| 副作用 | 幂等键 | 已有 terminal evidence 时的行为 |
| --- | --- | --- |
| solver/evaluator execution | `run_id + episode_id + request_sha256` | 读取并复用唯一 receipt；禁止再次执行 |
| verifier decision | `episode_id + evidence_sha256 + verifier_fingerprint` | 读取并复用同一 decision；证据或 verifier 改变则 drift |
| memory commit | `parent_snapshot_sha256 + episode_id + verifier_receipt_sha256` | 已提交则返回原 snapshot；不同 parent 走 CAS 失败 |
| frozen transfer | `run_id + target_id + memory_snapshot_sha256 + solver_fingerprint` | 已有 transfer receipt 则只读返回 |

同一个幂等键收到字节不同的 receipt、不同的 request 或不同的 fingerprint 时必须 fail closed，并保留冲突原因。成功 resume 不得通过复制旧 receipt、清空预算、换用新的 episode ID 或省略 evidence 来绕过幂等检查。

表中的 verifier 复用保证适用于已经持久化的 decision。DRS/BRS 的 verifier/curriculum/judge 在调用内部中断、结果尚未保存时仍可能重算本地 deterministic fixture，真实外部 callback 的 exactly-once 尚未实现。显式 started gate 当前仅在 frozen transfer 的 verifier/judge 上提供；该 gate 的不确定结果还缺少专用 evidence-bound 续接 API。

## 5. Unknown reconcile gate

`unknown` 表示控制面无法证明 worker 是否已经完成；它不是失败，也不是可直接重试的信号。run 或 episode 进入 `unknown` 后：

- 禁止新 target、practice、retry、memory commit 和 transfer side effect；
- ledger 只允许追加 reconcile 记录，不能直接把状态改回 `running`；
- reconcile 必须核对 process ownership、PID/PGID 或等价进程证据、heartbeat、workspace、request/receipt 文件、evaluator evidence 及全部 fingerprint；
- reconcile 只能落到以下明确结论：`already_terminal`、`recoverable`、`abandoned`、`drifted`、`manual_review`；
- `already_terminal` 只在 receipt 完整且绑定精确时复用；`recoverable` 继续原 episode；其他结论必须终止或等待人工处理；
- 未通过 reconcile 前，DRS 不得进入 practice/retry，BRS 不得合并 wave 中任何 child。

上述 process ownership、heartbeat 和 workspace 检查是接真实 producer 时的接线要求。当前本地路径依据 immutable request/result 与 evidence-bound reconciliation journal；不能将它声称为完整的进程存活或外部 ownership 探测。显式 reconcile 为失败/取消等结论时也必须保持原结果 wire 不可变，并使 controller 能识别已解决的不确定状态。

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

阶段 1 采用 exact-match policy，另绑定 verifier、curriculum、target judge 的代码及配置身份。controller 必须重新计算当前组件指纹；调用方回传旧 fingerprint 不能代替该检查。无法构建可信身份或存在变化时 fail closed，保留已有记录并返回 drift/identity 错误。`drifted`/`manual_review` 尚不是当前 run 的自动持久状态；兼容 patch policy 仍未实现。

mutable instance 需显式配置 hook；函数默认值、closure 和 bound owner 的配置必须被绑定或拒绝。模块全局、导入依赖和 provider/model 配置需要组件 hook 主动投影，本地 identity helper 不发现完整 Python 依赖图，也不替代 producer/environment attestation。

推荐固定诊断码：`rsi_resume_contract_drift`、`rsi_resume_evaluator_drift`、`rsi_resume_environment_drift`、`rsi_resume_memory_drift`、`rsi_resume_solver_drift`、`rsi_resume_actor_drift`、`rsi_resume_budget_drift`。

## 7. Budget、深度和终止

每个 run 维护 planned/consumed/remaining 三组可查询值。所有 child episode 从父 run 的剩余预算派生；child 不能增加父预算。以下任一条件达到上限时，控制器必须追加明确终态并停止创建新 episode：

- `now >= deadline_unix`；
- 新 child 的 `depth > max_depth`，或 ancestry 存在环；
- practice、target、solver、evaluator、verifier 或 transfer 调用数达到上限；
- unknown reconcile/retry 次数超过 `max_unknown_retries`（预算原语已有，真实 adapter 接线需单独验收）；
- mode-specific plan 上限达到。no-improvement policy 不属于已完成能力。

预算耗尽的终态应区分 `timed_out`、`budget_exhausted`、`unknown` 和 `failed` 的原因。预算检查必须发生在每个 side effect 前和 resume 后；失败重试不能通过省略 `budget`、复制旧 request 或新建 run 来放宽原策略。

当前 controller DRS/BRS 以 depth 0 运行，launch 原子预留 solver、evaluator、verifier；它们是保守的控制面预留计数，不能当作真实 provider 请求数、token 用量或成本。transfer 使用独立持久边界和调用预算。递归 solver→RSI 调度、嵌套预算传播、CPU/GPU/token 用量及成本统计仍在后续范围。

## 8. 验收矩阵

阶段 1 的 provider-free 验收至少包含：

1. 在 target、practice、verify、commit、transfer 前后各注入一次中断；resume 只执行缺失的 side effect。
2. 已有 terminal receipt 的 target/practice/transfer 重启两次，调用计数不增加，返回同一 receipt digest。
3. `unknown` worker 分别覆盖存活、已退出有 receipt、缺 receipt、workspace/fingerprint 漂移；未经 reconcile 均不能继续。
4. 修改 contract/evaluator/environment/memory/solver/actor/budget 任一绑定，resume 在 solver 启动前拒绝。
5. 让 deadline、depth、practice 和 nested solver budget 耗尽；不创建额外 episode、不提交 memory、不启动 transfer。
6. 两个并发 resume 使用同一 checkpoint；只有一个 CAS 成功，另一个得到 `rsi_record_parent_conflict` 或等价固定错误。

阶段 1 完成判据是实际 crash injection 和副作用计数断言通过，不以占位 `xfail`、仅抛固定异常的测试或只读 receipt replay 代替。每轮测试结果在 `validation.md`/交接中记录；`tasks.md` 只勾选本地实际覆盖的边界，未实现的 callback 和外部证据恢复接口继续保持未完成。

当前本地 DRS/BRS 矩阵、显式 unknown 终止证据、memory publication、末态 journal/deadline、逐 verifier deadline、并发锁和 CLI 重复运行已通过；`tasks.md` 分别记录这些已覆盖项。Frozen transfer 的启动后未知 verifier/judge 尚无专用 evidence-bound 续接 API；已经发布 unknown transfer receipt 后显式 settle worker 仍停在 `rsi_transfer_unknown_receipt_reconcile_required`。保留这些 gate 是正确的保守行为，但不是对应恢复能力已经完成。
