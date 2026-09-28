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
lineage、verifier-gated snapshot、BRS/DRS 调度和 transfer guard；真实 OSWorld/ALE 风格
Actor 环境、receipt 重开/隔离 verifier 和自主多样性 curriculum 仍属于后续接线工作。

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
