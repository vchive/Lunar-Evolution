# RSI 开源项目调研

**调研日期**：2026-09-28

**范围**：公开仓库和仓库内的架构文档；没有启动第三方模型、评测平台或远程服务。

## 项目分类

| 项目 | 改进对象 | 核心机制 | 对 Lunar 的价值 |
| --- | --- | --- | --- |
| [RSIAgent](https://github.com/AetherLabsAI/RSIAgent) | Agent 的环境能力和跨任务经验 | Curriculum → Actor → Independent Verifier → Memory；BRS/DRS；冻结记忆测试 | 直接借鉴学习控制面、独立验证、memory commit 和 frozen transfer |
| [RRSI](https://github.com/google-research/rrsi) | Agent harness | 在固定模型上搜索 prompts、tools、memory、control flow；critic、噪声门槛、成本规则、novelty 和 worktree | 借鉴 harness 候选的正则化和 promotion gate |
| [Gödel Agent](https://github.com/Arvid-pku/Godel_Agent) | Agent 自身逻辑和代码 | self-reference、monkey patching、自修改 policy | 说明自修改边界；不作为 Lunar 第一阶段实现方式 |
| [ScienceBuddy](https://github.com/Gen-Verse/ScienceBuddy) | Harness 和模型权重 | 内层固定模型搜索 harness，外层固定 harness 做 RL，交替继承 | 提供多时间尺度循环的参考；Lunar 第一阶段不更新模型权重 |
| [Skill-RSI](https://github.com/justinwetch/Skill-RSI) | Skill 包 | champion/challenger、ontology、deconstruction、preflight、对照评测和 promotion | 借鉴单 challenger、可解释实验计划和技能包回归门 |
| [LightRSI](https://github.com/zjunlp/LightRSI) | Host runtime 和上下文管理 | host-independent core、plugin lifecycle、host adapters、context/memory plugin | 借鉴插件生命周期和 host adapter；不把 context cleaner 当作完整 RSI |
| [RSIHub](https://github.com/simple-agent-lab/RSIHub) | Agent harness、prompt、skill、target code | select → rollout → analyze → mutate → guardrail → evaluate → absorb；固定 evaluator、声明 mutable surface、Git lineage | 与 Lunar 的 evaluator/receipt/lineage 方向最接近，可借鉴 stage contract 和 recipe |
| [Proteus](https://github.com/proteus-evolve/Proteus) | 任意 Agent harness | HarnessAdapter、context-fresh episode、snapshot、hidden/visible evaluator、crystallization 测试 | 借鉴 adapter 契约、快照隔离和“移除外部扰动再测” |
| [Evolver / EvoMap](https://github.com/EvoMap/evolver) | Agent 的策略经验和技能 | GEP 的 Gene、Capsule、EvolutionEvent；将经验压缩为可审计资产 | 借鉴结构化、短小、有 provenance 的 memory；不直接接入其网络 |
| [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) | 候选程序 | population、island、evaluator、archive、candidate lineage | 保持为 Solver/Workflow adapter |
| [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) | 候选程序 | program population、SQLite 结果、并行评测和 lineage | 保持为 Solver/Workflow adapter |

## 按改进对象比较

| 类别 | 代表项目 | 持久状态 | 后续任务如何变好 | 与 Lunar 的关系 |
| --- | --- | --- | --- | --- |
| 环境经验 RSI | RSIAgent | 通过 verifier 的跨 episode 策略记忆 | Curriculum 选 practice，Actor 读取已批准记忆 | Feature 160 的目标形态 |
| Harness RSI | RRSI、RSIHub、Proteus、Skill-RSI | prompt/tool/skill/control-flow 候选及评测 lineage | 对 harness 候选做独立对照、gate 和 promotion | 未来独立的 harness-evolution mode，不混入首次 memory RSI |
| 候选程序演化 | OpenEvolve、ShinkaEvolve、Lunar Population | candidate、parent、iteration、population/island、score | 在同一问题合同内搜索更好的程序 | Lunar SolverGateway 的下游后端 |
| Agent 自修改 | Gödel Agent、DGM | Agent 源码/执行树/parent-child | 修改实现并在 benchmark 上竞争 | 研究参照；第一阶段不授予 Actor 任意改 Lunar 源码权限 |
| 权重与 harness 联合训练 | ScienceBuddy | harness 变体与训练样本/模型 checkpoint | harness 搜索与权重优化交替 | 超出固定模型第一阶段范围 |
| 运行时扩展 | LightRSI | plugin/context/runtime state | 通过插件与上下文治理改变运行能力 | 可借鉴 adapter 生命周期；不是独立学习算法 |
| 经验资产交换 | Evolver / EvoMap | Gene、Capsule、EvolutionEvent | 检索可复用经验资产 | 仅借鉴结构化资产和 provenance；不接入外部网络 |

## 主要结论

### 1. RSIAgent 是学习控制器，不是搜索器

RSIAgent 的关键创新是选择下一个 practice/target，并在独立 Verifier 通过后提交经验。它的
memory 作用域是 Agent 能力和环境经验，不是某个 OpenEvolve island 的 population checkpoint。

### 2. RRSI、Skill-RSI、RSIHub、Proteus 更接近 Lunar 的平台层

这些项目共同强调：候选修改必须有明确的 mutable surface、独立 evaluator、可回滚快照、
可解释 lineage 和 promotion gate。Lunar 已经具备 Contract、Exact Evaluator、Receipt、
CandidateArchive、Checkpoint 和恢复状态，因此不需要重写成它们的运行时，只需要增加 RSI
学习控制面和相应的状态协议。

这些项目的共同点不代表它们都在做环境因果记忆：RRSI、RSIHub、Proteus 和 Skill-RSI 的
主要优化对象是 harness/skill 候选。它们的 promotion gate 可用于未来的 Harness Evolution，
不能代替 Feature 160 的 practice episode、Verifier 或跨 episode memory eligibility。

### 3. Gödel Agent 和 ScienceBuddy 不应成为第一阶段依赖

Gödel Agent 的自修改代码边界过宽；ScienceBuddy 的外层递归包含 GRPO/模型权重更新。Lunar
当前目标是固定基础模型、通过求解器和验证记忆提升能力，因此先采用冻结模型的 test-time RSI。

### 4. LightRSI 解决的是宿主运行时问题

LightRSI 的 plugin lifecycle、host adapter、context snapshot 和 recovery 对 Lunar 有工程借鉴，
但它本身不是 Curriculum → Actor → Verifier 的环境学习算法。它应作为运行时设计参考，而不是
RSI 控制器的直接实现。

### 5. Evolver 的 Gene/Capsule 适合作为 memory 表示参考

Lunar 不应把自由文本会话直接写入长期 memory。更合适的是保存经过验证的结构化经验：适用
contract、触发条件、策略摘要、失败边界、证据 receipt、兼容 solver 和 confidence。

## 对 Lunar 的归纳

Lunar 应采用如下分层：

```text
Lunar Platform
├── Contract / Exact Evaluator / Receipt
├── Runtime / Workspace / Worker / Recovery
├── Solver Adapter Registry
│   ├── Native Population
│   ├── OpenEvolve
│   ├── ShinkaEvolve
│   └── Traditional SolverAdapter
└── Optional RSI Learning Controller
    ├── Curriculum
    ├── Lunar Actor
    ├── Independent Verifier
    ├── Approved Memory Commit
    └── Frozen-Memory Transfer Test
```

RSI 学习循环应在 solve phase 之间读取冻结 memory；不能在一个 population/island 搜索中实时
写入 memory，也不能把外部 producer 的分数直接当作 RSI 的验证结果。

## 与 Lunar 现有能力的映射

| 已有能力 | 能提供什么 | 不能据此声称什么 |
| --- | --- | --- |
| `AgentLoopRuntime` / Agent registry | 可复用的 Actor 和显式 adapter 边界 | 尚无跨 episode Curriculum 或环境练习调度 |
| Native Population / OpenEvolve / Shinka handoff | 可由 RSI 发起的候选搜索 workflow | population、island、elite 不是 RSI 跨任务 memory |
| Exact Evaluator、candidate execution/evaluation receipt | 可审计的候选执行与目标分数 | 单个 solver 返回分数不等于独立 Verifier 通过 |
| Feature 044 Verified Experiment Memory | 由 archive 结果生成的受限 prompt feedback | 它是当前/后续候选搜索反馈，不是独立验证后的跨 episode snapshot |
| `MemoryStore` | 普通会话 note 的显式存储和 lexical recall | `remember()` 可直接写入；没有 RSI verifier gate、snapshot digest 或 approval lineage |
| Store、checkpoint、recovery | 可借鉴的持久化和故障恢复机制 | 尚无 RSI run/episode/memory 的原子状态机 |

因此 Feature 160 应新增 RSI 专用存储和控制器；不应把普通 `MemoryStore` 升格为 verifier 权威写入口，也不应复用候选 archive 作为 RSI memory。Feature 044 继续负责 solver 内候选反馈，Feature 160 负责 solve phase 之间经过验证的学习经验。
