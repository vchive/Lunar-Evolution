# Feature 160: RSI learning mode

**Status**: Draft design based on open-source RSI research

## Problem

Lunar 已经统一了算法合同、精确评测、候选档案、外部 producer、worker 生命周期和恢复协议。
这些能力适合搜索候选算法，但还不能表达 RSIAgent 式的跨 episode 学习：选择下一个练习、
独立验证环境结果、提交可迁移经验，并在冻结经验后重新测试目标。

如果直接把 RSI 当作另一个 `EvolutionStrategy`，Curriculum、Verifier 和 Memory 会被压缩成
“候选生成器”，导致求解器内部的 population 状态与跨任务能力混在一起，也会允许搜索过程中
实时写入自由文本经验。

## Outcome

增加一个独立的 `RSI Learning Mode`。它复用 Lunar 的 Contract、AgentLoopRuntime、工具、
Solver Adapter、Exact Evaluator、Receipt、Store 和恢复协议，但拥有自己的 Curriculum、
Practice Episode、Independent Verifier、Memory Snapshot 和 Frozen-Memory Transfer Test。

RSI 不是 OpenEvolve 或 ShinkaEvolve 的同级搜索后端，而是调用这些 solver 的上层学习控制器。

## Scope

- 固定基础模型参数，第一阶段不做 SFT、RL 或模型权重更新。
- 支持 BRS broad wave 和 DRS target-gap-practice 循环。
- Actor 通过 Lunar solve 流程调用已注册的 solver/workflow。
- 每个 practice 产生 bounded episode、candidate/material bundle、候选源码/依赖指纹和 evaluator receipt。
- Episode 还保留 bounded 的公开 action/tool/observation 轨迹；私有推理不进入控制面。
- Independent Verifier 在 memory commit 之前决定 `pass`、`fail` 或 `unresolved`。
- 只有 approved memory snapshot 才能进入下一轮或 frozen target solve。
- 学习运行、practice、验证、memory commit 和 transfer test 都可以恢复。

## Contract

### 1. 控制面分离

```text
Algorithm Mode
    Controller → Solver Adapter → Exact Evaluator → Candidate Delivery

RSI Mode
    Curriculum → Practice → Lunar Actor/Solver → Verifier
             → Approved Memory Snapshot → Frozen Transfer Test
```

`EvolutionStrategy` 继续只表示候选搜索；`RSILearningController` 不实现该协议，也不修改
`PopulationStrategy` 或 `OpenEvolveStrategy` 的 island/population 语义。

### 2. Practice Episode

每个 practice 必须固定并持久化：

- `contract_digest`、`evaluator_digest`、`environment_digest`；
- `memory_snapshot_digest` 和 memory scope；
- curriculum decision、parent target 和 practice charter；
- Actor adapter、solver adapter、budget 和 workspace；
- action/tool/observation trace 的 bounded 摘要；
- candidate/material bundle、execution evidence 和 local evaluator receipt；
- verifier outcome、diagnosis 和 terminal recovery state。

外部 solver 的 score 只作为 provenance。Lunar Exact Evaluator 或独立 Verifier 才能产生
admission 和 memory commit 所需的权威结果。

### 3. Memory Snapshot

memory entry 必须带有：

- `memory_id`、版本和父 snapshot；
- 适用的 contract/problem family；
- 触发条件、策略摘要、失败边界和预期结果；
- 兼容的 solver/workflow 范围；
- verifier outcome、receipt digest 和来源 episode；
- `approved`、`rejected`、`unresolved` 状态。

当前 `MemoryStore` 的普通 note/lexical recall 不直接获得 memory commit 权限。它可以继续
服务普通对话，但 RSI memory 必须使用 verifier-gated、content-addressed snapshot。

### 4. BRS / DRS

#### Durable candidate governance boundary

An explicit `memory_governance` ledger selects the `candidate_only` controller policy. A passing
practice creates durable observed, verified and candidate records, retaining the complete immutable
memory content and source episode/verifier identity. Every append uses compare-and-swap; exact
repetition is idempotent, and an interrupted partial nomination resumes its missing transitions.
Restoration reopens the full journal and source episode history, rejecting missing transitions,
changed content, source drift, stale parents and invalid verifier/gate histories.

This policy never adds a candidate to the solver snapshot. It rejects nonempty initial snapshots
and approved/active writes until trusted holdout evidence is connected. Caller-supplied gate scores
are insufficient. The selected policy is a durable run pin; resume cannot switch it. Existing
`verifier_snapshot` fixtures keep their protocol behavior and do not establish B2 promotion
acceptance. Trusted native promotion and explicit active retrieval now reopen retained panel evidence;
default DRS/BRS automatic retrieval and automatic transfer regression remain open.

The CLI exposes this opt-in policy as `rsi run --memory-policy candidate-only`; `resume` restores
the pinned policy. `inspect` reports candidate lifecycle heads using read-only journal validation.
Committed nominations must be validated from retained history, never recreated during recovery.

#### Durable verifier reservation and reconciliation

The run budget includes separate evaluator, verifier and transfer invocation ceilings and counters.
The controller reserves verifier work and persists the request, result, source episode and verifier
identity before invocation. A retained decision is reused without another charge; an interrupted
intent with no retained decision puts the run in `unknown` and does not authorize replay.

`reconcile_verifier` accepts a retained decision only after checking the expected current episode
record, the original pending-intent digest and the verifier's read-only evidence validator. It
preserves the solver result and reservation. Repeating the same reconciliation is idempotent;
changed evidence, missing validation authority or a terminal exhausted run cannot restart work.
The local exact fixture reconstructs decisions without calling `verify`; a native verifier reopens
its retained independent execution evidence.

The CLI exposes pending intents through `rsi inspect` and accepts `rsi reconcile --verifier-decision
FILE --expected-record-sha256 DIGEST --expected-intent-sha256 DIGEST`. This mode is exclusive with
solver-result and worker-state reconciliation. Decision files are bounded regular JSON files with
an exact schema, including nested checks and duplicate-key rejection.

Native evaluator and standalone transfer runtime reservations are connected through explicit
durable scopes. Controller transfer budgets still require a shared run ledger. A gateway without
evaluator accounting support rejects a finite evaluator limit before execution. Legacy budget
checkpoints without stage counters require explicit migration;
recovery must not invent zero consumption for previously executed work.

- BRS 从同一份 frozen wave memory 启动多个 practice，所有 episode 验证完后才按确定顺序合并。
- DRS 先执行 target attempt，根据 PASS/FAIL/UNRESOLVED 和 capability gap 选择 practice；
  每次 practice commit 后再尝试 target。
- 学习运行有独立的 `max_waves`、`max_practice_rounds`、`max_target_attempts`、墙钟和
  no-improvement 预算。

### 5. Frozen-Memory Transfer Test

Transfer test 必须关闭 Curriculum 和 memory update，只读取已批准 snapshot 执行 target，
最后再调用 official evaluator。测试结果不能反向修改该 snapshot。

### 6. 安全和一致性不变量

1. 一个 solve/search phase 开始后，contract、evaluator 和 memory snapshot 不可变。
2. Solver adapter 不能直接写 RSI memory。
3. Verifier 不读取 Actor 私有推理或未提交的 memory 草稿。
4. 未验证、超时、abandoned、unknown 的 episode 不能晋级为 approved memory。
5. population/island/checkpoint 状态只属于 solver run，不自动转换为 RSI memory。
6. 恢复只能继续同一 episode 或同一 snapshot，不得静默重跑已知执行状态。

### 7. RSIAgent 对齐边界

Lunar 的 RSI mode 对齐 RSIAgent 的三 Agent 闭环：Curriculum 只选择练习，Actor 负责在
环境中执行，Independent Verifier 只读取声明的 episode evidence 并决定是否提交因果经验，
最后由 frozen-memory transfer 测量迁移效果。当前控制面已经具备 Curriculum、episode
lineage、verifier-gated snapshot、BRS/DRS 持久恢复和 transfer guard。本地 native
gateway、重开 receipt 后隔离重评的 verifier，以及历史覆盖/多样性/失败边界课程已实现。
真实模型/OSWorld/ALE 风格 Actor、完整开源 campaign 和通用迁移收益仍需后续独立验收。

## Lunar integration points

| RSI 组件 | 复用或新增位置 |
| --- | --- |
| Actor | `AgentLoopRuntime`、`AgentRegistry`、`run_evolution` 的 solver gateway |
| Solver | 现有 `PopulationStrategy`、`OpenEvolveStrategy`、`shinka_handoff`、传统 SolverAdapter |
| Evaluator | 现有 `Exact Evaluator`、candidate execution 和 receipt |
| Episode state | 新增 RSI Store records，复用 `Store` 的事件和恢复原则 |
| Curriculum | 新增 deterministic/LLM-assisted curriculum interface |
| Independent Verifier | 新增与 Actor 运行时隔离的 verifier interface |
| Memory | 新增 approved snapshot store；普通 `MemoryStore` 保持兼容 |
| Transfer | 新增 frozen-memory target runner 和 official evaluator gate |

## Non-goals

- 不把 RSI 实现成 OpenEvolve 的另一个策略名。
- 不把 population、island、elite 或 raw candidate genome 写进跨任务 memory。
- 不在第一阶段修改基础模型权重。
- 不实时混合 `search → memory write → search`。
- 不自动安装或依赖 OpenCode、WebAgent、远程 evaluator 或公司评测服务。
- 不直接复制 Gödel Agent 的任意自修改代码机制。

## Acceptance goals

1. RSI practice 可以调用任一已注册 solver，并生成与普通 solve 相同的 candidate/evaluator receipt。
2. Independent Verifier 可以阻止失败或 unknown episode 进入 approved memory。
3. BRS/DRS 在中断后能恢复，且不会重复提交或篡改已冻结 snapshot。
4. 同一 frozen memory 可以在同一个或兼容的 solver 上进行下一次 solve。
5. Frozen-memory transfer test 期间 Curriculum 和 memory update 均关闭。
6. 现有 population、OpenEvolve、ShinkaEvolve、普通 MemoryStore 和外部 producer 测试保持兼容。
