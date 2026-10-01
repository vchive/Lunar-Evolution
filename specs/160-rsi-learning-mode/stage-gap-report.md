# Lunar RSI 阶段性能力差距报告

2026-10-01 最新更新：controller durable resume、unknown/callback reconcile gate、预算和指纹
恢复已通过本地矩阵；另补 schema v3 holdout pass/policy/input gate、ledger-backed durable
regression trials、v2 promotion identity、Actor→clean-room verifier、governed frozen-snapshot
下一次 dispatch gate 和只读 usage CLI。本轮组合 **890 passed**（其中 RSI 773），之后新增三条
alias/corruption/legacy-v1 回归的 focused 组合 **43 passed**。详细边界见 `priority-execution.md`。
campaign budget 尚未与 parent learning run 合账，gate 跨代需要 re-admit + 新 run，默认
holdout/quarantine 和完整桥接证据自动持久化仍开放；这些不能从本地 fixture 推导生产完成。
下面 A1/A2/A3/A5 的“现状证据”保留原始缺口分析，当前完成度以 `tasks.md`、`validation.md`
和代码为准。真实 Actor/官方 evaluator、外部 worker 来源和 ownership、默认 holdout/quarantine
调度、真实 process adapter/campaign 仍开放；fixture 通过不等于这些生产能力完成。

> 目的：为后续 SDD 提供经过代码、规格和测试核对的建设清单。本文只把当前确实缺失、且会阻塞 RSI 正确运行或真实评估的能力列入近期计划；通用平台最佳实践与远期研究能力单独标记，避免过度设计。
>
> 核对依据：Feature 160 代码、测试、tasks.md、validation.md、research.md，以及 153/154/156/157/158/159 producer 规格。本报告不代表真实模型、WebAgent、OpenEvolve 或 Shinka campaign 已经运行成功。

## 1. 当前基线与目标

Lunar RSI 是位于求解器之上的跨 episode 学习控制层：

Normal solve / AgentLoop
        │
Evolve: Native Population / OpenEvolve / Shinka
        │
RSI control plane
        ├─ Curriculum
        ├─ Practice Episode
        ├─ SolverGateway
        ├─ Official Evaluator
        ├─ Independent Verifier
        ├─ Memory Governance
        └─ Frozen Transfer / Regression

当前已经形成的主链路是：

Curriculum → Practice Episode → SolverGateway → Evaluator/Receipt → Verifier → Memory Snapshot → Transfer Receipt

阶段目标不是一次性做出可以任意修改自身的 Agent，而是先得到一个可恢复、可验证、可晋级、可迁移的 RSI 闭环。

## 2. 证据分级

### A：已确认缺失，近期 SDD 必须补

代码或测试直接证明能力不存在；缺失会阻止中断恢复、可信验证或正确的学习闭环。

### B：协议已有但运行时未接通，接真实 solver 前必须补

数据模型、receipt 或 adapter 已存在，但还不能驱动端到端行为。

### C：非当前主线的能力

这类能力不能按同一个“暂缓”结论处理：有些是当前目标明确不需要，有些应做一个受控的窄版本，有些则是可以保留的长期研究轨道。只有最后一类才适合在当前 SDD 之外继续规划。

## 3. 已具备，不重复建设

- RSI run、episode、verifier decision、memory snapshot、transfer receipt 数据模型。
- canonical digest、scope/compatibility、只读 memory snapshot。
- SQLite append-only ledger、CAS 状态迁移、worker reconcile 基础能力。
- DRS/BRS 控制策略、frozen parent、按 ordinal 合并规则。
- provider-free SolverGateway，以及 Mock、Native Population、OpenEvolve、Shinka 本地 fixture/adapters。
- PracticeEpisodeRunner、target → capability gap → practice → retry 主链路。
- Actor 隔离 workspace、candidate source/dependency/actor/solver/environment fingerprint、bounded trace。
- verifier-gated memory commit 和 frozen-memory transfer test。
- rsi run、rsi inspect、rsi reconcile CLI。
- 专项 RSI 测试通过。测试证明的是协议和 fixture 行为，不代表真实模型或 producer 效果。

## 4. A 类：近期必须建设

### A1. Controller-level durable resume

现状证据：RSILearningController 没有 resume(run_id)。_start_run() 会重新创建 run；同一 run 再启动会产生记录冲突。DRS 会重新创建 target episode，BRS 没有可恢复的 wave journal，terminal receipt 不能幂等复用。

为什么必须补：RSI 是多 episode、长时间运行流程。没有恢复入口，ledger 只是历史记录，不是控制状态；进程中断后无法保证不重复调用 solver/evaluator，也无法继续原来的学习链路。

最小范围：增加 resume(run_id)、run/episode/transfer 查询、terminal receipt 幂等复用、DRS target checkpoint、BRS wave/ordinal checkpoint、恢复前 fingerprint 检查，以及持久化 deadline 和预算。

验收标准：在 target、practice、verify、commit、transfer 任意阶段中断后重新启动，只继续未完成 side effect；不会创建第二个 target episode，不会重复提交已完成的 memory 或 transfer。

### A2. Unknown reconcile gate 与恢复状态机

现状证据：reconcile_worker() 和 rsi reconcile 主要修改 ledger 状态；不能检查原 worker/进程是否仍在运行，不能读取 evidence 决定继续、隔离、取消或重试，也不能让 DRS/BRS 在 reconcile 后自动恢复。

为什么必须补：worker 被杀、机器重启或 evaluator 超时后，状态可能是 unknown。直接重试可能重复运行 solver 或把未知结果错误晋级；直接失败又会丢失可恢复结果。

最小范围：unknown 进入 quarantine，禁止新 practice/retry；检查 process ownership、heartbeat、workspace、receipt 和 evaluator evidence；区分 recoverable、already-terminal、abandoned、drifted、manual-review；reconcile 完成后才允许 controller 继续；BRS 未完成 wave 不得提前合并。

验收标准：对 worker 已完成但进程退出、worker 仍存活、receipt 缺失、环境漂移四类 fixture 给出不同结论，且不会重复 side effect。

### A3. Fingerprint drift gate

现状证据：系统记录了 contract、evaluator、environment、solver、actor、memory fingerprint，但恢复时没有统一比较和拒绝策略。

为什么必须补：恢复时 evaluator、依赖或 memory scope 发生变化，旧 receipt 不能安全复用，新旧结果不可比较，memory 可能在错误环境下激活。

最小范围：定义 resume compatibility policy；恢复前比较各类 fingerprint；兼容的 patch 版本明确放行，不兼容变化进入 drifted/manual-review；记录 drift reason。

验收标准：篡改 evaluator、依赖、solver 配置或 memory digest 后恢复，系统拒绝复用旧 terminal receipt，并保留可审计原因。

### A4. Clean-room independent verifier

现状证据：已增加 provider-free `CleanRoomVerifier`，会在隔离 workspace 重开 candidate source/dependencies，重算 source/task/evaluator digest，检测 workspace 修改，并对超时、异常和不可信 evidence fail-closed。`CleanRoomAdmissionGate` 现在把通过的 clean-room verdict 严格绑定到 episode、source/dependency/task/evaluator provenance，并幂等写入 governance 的 `observed → verified`；它仍是独立 admission boundary，尚未由 controller 自动调用，也不会替代真实 Actor environment 或官方 evaluator。

为什么必须补：Actor 的成功不能直接成为学习证据。memory commit 必须基于独立可复核的 artifact 和 evaluator 结果，否则错误、伪造或环境污染会进入长期 memory。

最小范围：verifier 独立 workspace 和最小权限；定位源码、依赖锁定和运行输入；重算 source/dependency/environment digest；重新执行官方 evaluator 或受信 wrapper；隔离 Actor 私有 trace。当前已完成本地 wrapper/contamination slice 及 spawn 进程生命周期/超时边界；真实官方 evaluator、Actor environment 和外部真实性接线仍待完成。

验收标准：修改 candidate 源码、依赖、输入或 producer score 而不更新绑定 artifact 时，verifier 拒绝；Actor 报告成功但 clean-room evaluator 失败时，不得 commit memory。

### A5. 预算、递归深度和终止策略

现状证据：项目已有部分 run/worker budget 规格，但 RSI 控制器尚未把递归深度、practice 次数、solver/evaluator/verifier/transfer 子预算和 retry 上限统一纳入 run contract 与恢复状态。

为什么必须补：RSI 会调用 solver，solver 可能启动多轮搜索；retry、memory commit 或嵌套调用可能无界增长。

最小范围：max_depth、max_practice_episodes、max_solver_invocations、deadline、各子预算、max_unknown_retries；记录 planned/consumed/remaining；记录每个 run、episode、solver、evaluator 和 verifier 的调用次数、token/请求量、wall time、CPU/GPU time 以及可配置的估算成本；budget 超限进入明确终态；solver→RSI 做 depth/cycle 检查。

验收标准：超时、失败重试和嵌套 solver fixture 在预算耗尽后停止，不创建额外 episode，不触发无界 retry。

## 5. B 类：接真实 solver 前必须接通

### B1. Producer lifecycle 端到端闭环

OpenEvolve/Shinka 的本地 fixture/adapters 已存在，但 launcher、scheduler、process lifecycle、publication 仍未完全接通。缺少 trusted launcher/bootstrap、process ownership、timeout/cancel/cleanup、durable process receipt、unknown recovery、admission、archive/publication 和 parent delivery。

验收标准：本地 producer campaign 能完成 request、受控启动、超时或取消、receipt、candidate 验证、admission、publication；进程中断后可恢复或明确隔离。

### B2. Memory governance 与 promotion gate

已增加独立 append-only SQLite memory admission control plane，支持 observed → verified → candidate → shadow → approved → active → deprecated/revoked、CAS digest、verifier/pass、holdout/baseline regression 和 compatibility drift gate；另有显式 `MemoryPromotionAdapter` 接收 transfer report 并强制两步晋级。`RSILearningController.promote_transfer_regression()` 现在提供一个**显式 opt-in 的 provider-free 组合入口**：冻结 controller 当前 snapshot，执行本地 transfer regression，再经 adapter 做 `shadow → approved`（可选继续 `approved → active`），并在 snapshot、parent snapshot、solver/verifier/curriculum/judge fingerprint 或 CAS 漂移时 fail-closed；已完成的 promotion 可幂等重放，不重复 runner 或 governance revision。它不修改只读 `RSIMemoryStore`，也不代表真实 evaluator、自动 holdout campaign 或默认 controller 触发已经接通。

`MemoryPromotionAdapter.quarantine_failed_report()` 现在补齐 provider-free 的失败回滚边界：对已批准或激活的 admission，只有 canonical、快照绑定且带非空 rejection reasons 的失败 transfer report 才能通过 CAS 原子追加 `revoked`；撤销后不再可检索，使用新 head digest 重放只读返回，不重复写 revision。它不提供真实 evaluator 真实性，也不把失败报告升级为默认自动调度。

失败撤销的 reason 绑定 canonical report digest；手工撤销或另一份失败报告不得冒充同一次
重放。controller 晋级在每次 runner 前后复核组件，approval 同次 CAS 以 reason digest 绑定
观测 pins；重启后即使 compatibility 为空也不能激活漂移组件，旧无绑定 approval 不自动补造
身份。这仍是可信本地 callback 边界，不保证观察 callback 内瞬时更改后原地恢复的状态。

最小范围：observed → verified → candidate → shadow → approved → active → deprecated/revoked。candidate 必须绑定 verifier receipt、source episode、scope、compatibility 和 parent snapshot；用 baseline/holdout 决定 promotion；支持冲突、rollback、quarantine。

验收标准：单次 pass 只能产生 candidate 或 approved-pending，不能直接 active；holdout 失败、回归或 fingerprint 不兼容时不能晋级；撤销后新 episode 不再检索该 memory。

### B3. Transfer regression suite

已增加 provider-free `TransferRegressionSuite`：对 no-memory/old-memory/current-memory 三个冻结 arm
执行 seen/unseen 多目标、重复试验、输入/任务/记忆污染检查，并生成可喂给 promotion gate 的
holdout/baseline evidence。controller 现可通过显式 `promote_transfer_regression()` 组合这套 suite
和 promotion adapter；该入口只接受调用方提供的本地 runner，默认不会自动触发，也未接入真实
evaluator、跨任务数据集或生产 campaign。

最小范围：no-memory、old-memory、current-memory 对照；seen/unseen task split；多目标 holdout；repeated runs；task-family coverage；contamination check；promotion 后自动执行最小回归套件。

验收标准：memory 在 practice 任务通过但 holdout 无提升或有回归时，不得 active；报告收益、方差和成本。

### B4. Curriculum 从固定策略升级为可审计的失败驱动策略

已增加 provider-free `FailureDrivenCurriculum` 窄版本：有界 failure ontology、内容寻址 cluster、
capability/prerequisite coverage、hard-negative/boundary probe、重复抑制、budget/novelty/reason
审计和 canonical ledger replay；controller 可选地将 ledger 纳入 checkpoint 并在 resume 恢复。它保持确定性，不包含 bandit/RL。

已补齐显式 `FailureBoundaryPolicy`：未覆盖 capability/prerequisite 优先、可配置 hard-negative
阈值、单 cluster 选择上限与 novelty。新 selection 绑定 diagnosis 和 policy digest，恢复按
同一 policy 重演 cluster/task/reason/coverage/预算；ledger digest 即使没有 selection 也绑定
policy。旧无 policy checkpoint 只解释为默认 v1，不能采用当前自定义 policy，旧 digest 和
selection 派生字段均复核。详见 `curriculum-policy.md`；这仍是 opt-in 的本地 provider-free
能力，不代表默认调度或真实 evaluator 已接通。

最小范围：能力、前置能力、可观察失败、practice task、transfer task 的基本 ontology；失败模式聚类和去重；任务选择记录 reason、coverage、novelty 和 budget；先保持确定性、可重放，不引入复杂 bandit/RL。

验收标准：相同 ledger 和 seed 得到相同选择；连续重复失败会生成诊断或边界任务，而非无限重复同一 practice；选择理由可查询。

### B5. Solver adapter contract 与证据交接

已增加 provider-free `AdapterContractHarness`，统一 register → preflight → snapshot → execute → observe → finalize → verify → recover → close 生命周期、request pins、budget/deadline、terminal receipt、ownership 和 memory-write gate；OpenEvolve/Shinka 目前只是声明式 fixture capability。真实 process adapter 的 preflight、cancel、cleanup、external evidence 和 campaign 接线仍未完成。

最小范围：register → preflight → snapshot → execute → observe → finalize → verify → recover → close；capability/schema/version handshake；统一输入输出、预算和 receipt schema；solver-specific 状态不得直接写 approved memory。

验收标准：Mock、Native、OpenEvolve、Shinka 通过相同 contract tests；超时、取消、unknown 和恢复状态映射一致。

### B6. Artifact provenance 与污染隔离

已有 candidate source、依赖、environment、trace fingerprint，但任务输入、hidden evaluator、seed 和权限边界尚未形成端到端约束。

最小范围：绑定 task input/dataset、seed、evaluator code/config/version、container/dependency fingerprint；candidate 与 verifier workspace 分离；practice 不能读取 holdout/transfer 私有数据或其他 episode 私有 trace；score、receipt、verdict 分离。

验收标准：candidate 读取 hidden/holdout 数据、伪造 score 或跨 episode 读取私有 artifact 时，验证失败并记录 contamination reason。

## 6. C 类：按目标拆分的非主线能力

### C0. 当前明确不需要

这些能力不属于 Lunar 当前的本地研究型求解器接入和 RSI 正确性目标。除非产品边界改变，否则不进入近期或中期 SDD：

- 多租户、租户隔离、用户账号/角色权限和 SaaS 账单。当前没有多用户服务化需求，不建设租户级资源管理、计费结算或完整授权系统。
- 本地用量与成本统计不在排除范围内：run 级别的调用次数、token/请求量、耗时、CPU/GPU 时间、solver/evaluator 成本和预算消耗应纳入 receipt 与 ledger，供实验比较、预算控制和事后审计使用。
- 远程分布式 scheduler、跨机器 worker 和服务发现。当前优先把单机控制器的 resume、unknown reconcile 和 evidence 做正确；分布式运行会引入另一套故障模型。
- 完整 lineage UI。CLI、ledger、receipt、inspect/reconcile 足以支撑开发和审计，完整 UI 不构成 RSI 闭环的前置条件。
- Gödel Agent/Darwin Gödel Machine 式任意自修改。它改变的是 Agent 本体的代码权限和安全边界，不是当前 solver 组合或跨 episode 学习问题；可作为独立研究方向保留，但不赋予主线 Actor 修改 Lunar 核心源码的权限。

### C1. 应该做，但先做受控的窄版本

这些能力有实际价值，不能简单归为“永远不做”，但应等核心闭环稳定后按最小可验证范围推进：

- **失败驱动 curriculum**：确定性 failure clustering、能力覆盖、hard negative、重复抑制和边界任务属于中期能力；复杂 bandit/RL curriculum 后置。B4 的窄版本先保证可重放和可审计。
- **跨 solver memory 适配**：先做 scope、compatibility 和不可迁移时的拒绝；只有出现真实迁移需求时，才为特定 solver 编写显式 translator，并用 holdout regression 验证后允许 promotion。禁止首版自动猜测不同 solver 的记忆语义。
- **Normal/Evolve/RSI 的共享控制原语**：当前不立即统一三种模式的控制面，但可以逐步抽取 run、task/episode、receipt、worker state、budget、recovery 和 artifact provenance 等稳定原语，减少重复实现。
- **evaluator 噪声模型**：先保留 seed、重复次数、原始分数和方差；只有噪声已经影响 promotion 决策时，再引入统计模型。

### C2. 可以做，但必须作为独立的长期轨道

#### C2.1 模型权重更新、SFT 与 RL

模型适配符合 RSI 的长期方向，因此不能写成“永远不做”。但它不是当前 test-time RSI 的缺失能力，也不应把 `RSILearningController` 直接改造成训练器。当前应先固定基础模型，完成可恢复、可验证、可晋级、可迁移的 memory 闭环；之后再以独立的 **Model Adaptation** 轨道引入训练。

三者的用途也不同：

- **SFT** 适合把经过验证的高质量轨迹、策略或 skill 固化到模型；
- **RL** 适合在 reward/evaluator 稳定且可防奖励投机时优化行为策略；
- **直接权重更新** 是承载这些训练过程的模型版本变化，不是 memory promotion 的替代品。

训练轨道至少需要独立的训练数据 provenance、checkpoint registry、train/eval/holdout 隔离、checkpoint fingerprint、baseline/challenger 对照、rollback、训练预算和污染检测。训练后仍需运行 frozen-memory transfer regression，确认收益来自模型适配而不是记忆泄漏，并明确新模型是否兼容旧 memory snapshot。

因此结论是：**模型权重更新可以做，但应在 Phase 5 作为可选实验轨道；它不阻塞当前 RSI 主线，也不能与 memory 学习控制器混成一个状态机。**

#### C2.2 其他条件性扩展

- memory 规模和任务多样性真实增长、结构化匹配出现召回瓶颈后，再评估 vector retrieval 或语义索引；首版继续使用可审计的结构化条件匹配。
- 需要更强 harness 演化时，再引入 prompt/tool/memory/control-flow 的 champion/challenger 版本化；这与模型训练分开评估。
- artifact GC 属于存储运维能力，只有本地 artifact 数量和保留成本成为问题时再做，不作为 RSI 正确性的前置条件。

## 7. 建设顺序与阶段出口

### 阶段 0：协议核对（当前）

数据模型、fixture gateway、receipt/fingerprint、ledger/CAS 和基础 DRS/BRS 已具备。出口：专项测试稳定通过，所有未接通项已列出。

### 阶段 1：可恢复 RSI（P0）

顺序：resume 与查询 → event/wave journal 和 side-effect idempotency → unknown quarantine 与恢复状态机 → fingerprint drift gate → 预算、深度和终止持久化。

出口：任意 episode 中断后可继续；不重复已完成 side effect；unknown 不会自动误重试或误晋级。

### 阶段 2：可信学习闭环（P1）

当前已完成 provider-free clean-room verifier（含本地 spawn 进程生命周期/超时边界）、provenance/污染检测、clean-room verdict → governance 的 verified admission bridge、transfer regression 窄版本、memory promotion adapter、controller 的显式 transfer promotion 组合入口、失败驱动 curriculum 及其可选 resume 接线和统一 adapter contract。剩余顺序为：接入真实 evaluator/Actor、将 holdout regression 接到受控的默认调度策略、把 provider-free quarantine 接到默认调度（当前仍是显式调用），以及真实 process adapter/campaign。

出口：错误或伪造 receipt 无法进入 active memory；局部成功不能冒充迁移能力。

### 阶段 3：真实 solver producer（P1）

顺序：trusted launcher/bootstrap → process ownership、timeout/cancel/cleanup → durable producer receipt、unknown recovery → admission/publication/parent delivery → OpenEvolve/Shinka 本地真实 campaign。

出口：真实 solver 可受控运行，结果可验证、可恢复、可交付；不依赖 WebAgent 或远程公司评测。

### 阶段 4：受控研究扩展（P2）

按实际使用量推进失败驱动 curriculum 的窄版本、显式跨 solver adapter、共享生命周期原语和 evaluator 噪声分析；不自动开启复杂 bandit/RL curriculum、完整统一控制面或分布式 scheduler。

### 阶段 5：可选 Model Adaptation 轨道（P3）

在阶段 1 至 3 的闭环和阶段 2 的 holdout 回归稳定后，单独建设训练数据 provenance、checkpoint registry、baseline/challenger、rollback、污染隔离和训练预算，再评估 SFT、RL 或其他权重更新方式。该轨道可以调用同一套 evaluator、verifier 和 transfer regression，但拥有独立的 checkpoint、版本和恢复状态；失败时回滚模型版本，不回写主线 memory 状态。

## 8. SDD 拆分建议

每个 feature 都应包含：现状证据（代码位置、未覆盖测试或可复现失败）；最小 contract（状态、输入输出、幂等键、fingerprint、预算）；failure matrix（中断、超时、取消、unknown、drift、verifier reject）；验收测试（至少一个 happy path 和一个不会重复副作用的恢复路径）。

建议后续 feature：

- 161-rsi-durable-resume
- 162-rsi-unknown-reconcile
- 163-rsi-fingerprint-drift-gate
- 164-rsi-cleanroom-verifier（provider-free MVP 已完成，真实 evaluator 接线待做）
- 165-rsi-budget-depth-termination
- 166-rsi-memory-promotion-transfer（promotion control plane 已完成，transfer regression 待做）
- 167-rsi-curriculum-failure-driven（provider-free 窄版本已完成，controller 默认接线待做）
- 168-solver-adapter-lifecycle（provider-free contract 已完成，真实 process adapter 待做）
- 169-producer-real-campaign-closure

这些编号只是拆分建议，不代表已经创建对应 feature。

## 9. 结论

当前真正的瓶颈不是再增加一个 solver，而是让已经存在的 RSI 协议具备四个性质：

可恢复 → 可验证 → 可晋级 → 可迁移

A 类决定 RSI 是否正确；B 类决定 RSI 是否能接真实 solver；C0 明确当前不需要的服务化和任意自修改，C1 保留按需收窄的扩展，C2 则把模型适配和其他研究能力放到独立轨道。这样既不会为多租户等当前没有的需求建平台，也不会错误地把模型权重更新排除在 Lunar 的长期路线之外；同时可以避免把 OpenEvolve 的 population、producer 的分数或一次成功 episode 误当成 RSI 的长期学习能力。
