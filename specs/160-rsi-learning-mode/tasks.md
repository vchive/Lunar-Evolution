# Tasks

- [x] T160-01 定义 RSI run、practice episode、verifier decision、memory snapshot 和 transfer receipt（协议 MVP）。
- [x] T160-02 增加 canonical digest、scope/compatibility 和 read-only snapshot loader（协议 MVP）。
- [x] T160-03 增加 provider-free SolverGateway 请求/结果边界与 deterministic mock fixture。
- [x] T160-04 增加独立 Verifier 接口 fixture，拒绝未验证、unknown、abandoned 和篡改 episode。
- [x] T160-05 实现 verifier-gated memory commit 和 compare-and-swap parent snapshot fixture。
- [x] T160-06 实现 BRS broad wave 的 provider-free 并行 practice、验证后有序合并和 frozen-parent 校验；持久恢复验收见 T160-13。
- [x] T160-07 实现 DRS target attempt → capability gap → practice → retry target，并对 unknown/timeout/abandoned/cancelled 短路。
- [x] T160-08 实现 frozen-memory transfer test，并在测试期间锁定 memory/curriculum 写入。
- [x] T160-09 增加本地 mock/native/OpenEvolve/Shinka provider-free 集成 fixture 和
  target/practice timeout、abandoned、cancelled 状态矩阵；BRS 遇到不确定 worker 会保留
  wave evidence 并阻止合并；全链路 DRS fixture 回归通过。
- [x] T160-10 增加显式本地 CLI/诊断/恢复入口（`rsi run|inspect|reconcile`）；controller 恢复见 T160-13，真实 solver adapter 和 LLM curriculum 不在本轮验收范围。
- [x] T160-11 将 candidate source、dependency、actor/solver fingerprint 和 bounded public action/tool/observation trace 纳入 episode evidence；MemoryItem 增加 condition/action/observed-result/applicability 因果投影。
- [x] T160-12 增加 provider-free clean-room verifier MVP：候选源/依赖在隔离 workspace 重开，重算 evaluator/source/task 指纹，检测 workspace 修改并对超时、异常和不可信证据 fail-closed；真实 Actor environment runner 和官方 evaluator 仍待接入。
- [ ] T160-13 增加 durable controller-level resume、unknown reconcile gate 和 diversity/failure-boundary curriculum policy。
  - [x] 阶段 1 基础：append-only run/episode ledger、controller lock、CAS/hash-chain checkpoint、immutable request/result wire 和 evidence-bound episode reconcile。
  - [x] 阶段 1 控制流实现：v2 checkpoint 持久化 DRS/BRS plan、launch intent、curriculum decision、execution、judgment、memory snapshot 和预算；恢复可进入原计划中后续尚未启动的 episode。
  - [x] 阶段 1 identity 实现：恢复时重新计算当前 gateway/verifier/curriculum/target-judge 配置及代码指纹；mutable instance、函数捕获和 bound method 配置需可审计的显式 hook。
  - [x] 阶段 1 预算基础：planned/consumed/remaining、绝对 `deadline_unix`、原子 solver/evaluator/verifier 预留和 budget-exhausted 终态；预算模块提供 depth/cycle 与 unknown-retry gate。
  - [x] 阶段 1 本地集成矩阵：DRS/BRS 中断、显式 unknown 失败/无结果取消、memory publication、terminal journal 优先于恢复 deadline、逐 verifier deadline、并发锁，以及 CLI 重复 `rsi run` 的 fixture 回归。
  - [x] 阶段 1 frozen transfer 基础恢复：请求/组件/预算绑定、结果与 receipt publication 中断恢复、terminal receipt 重放和未知 callback 隔离；最终测试数量由集成报告补充。
  - [x] 阶段 1 callback 恢复接口：transfer verifier/judge 已 started 但没有持久结果时，通过专用 evidence-bound `reconcile_callback` 登记已有结果，再续接原流程；不自动重试。
  - [x] 阶段 1 控制器 callback 语义：DRS/BRS verifier/curriculum/judge 先写 started、后写已校验结果；未知调用隔离整条 run，显式对账及精确重放不重复调用或扣预算。CLI 支持 inspect 和只登记结果的对账；旧版本缺少 started 协议的非终态记录需迁移，不能推断未执行。
  - [x] 阶段 1 unknown transfer 失败处置：worker 已显式 settle 为失败/取消/超时/放弃后，`reconcile_receipt` 原子追加 failed revision 与 checkpoint；保留旧 unknown 收据和原始 worker result，禁止通用 transition 绕过。
  - [ ] 后续真实接线：上述对账采用可信本地证据；外部来源真实性、worker ownership 和外部幂等协议仍需 adapter 验收。unknown→passed 需要独立可信完成证据协议，本轮不得从 unknown 声明推导成功。
  - [x] 阶段 2 provider-free policy：显式 `FailureBoundaryPolicy`，未覆盖 capability/prerequisite 优先、hard-negative 阈值、单 cluster 预算与 novelty；新 ledger 绑定 diagnosis/policy 摘要并逐条重演选择，controller checkpoint 校验 policy drift；旧无 policy checkpoint 只按默认 v1 和旧 digest 公式恢复。仍需调用方显式注入，不包含默认调度、bandit/RL 或真实 evaluator。
- [x] T160-14 增加独立 memory admission governance 控制面：append-only admission history、CAS 状态转移、verifier/pass、holdout/baseline regression gate、compatibility drift 和 revoke fail-closed；不修改只读 RSIMemoryStore。clean-room verdict 的 `observed → verified` admission bridge 见 T160-21；provider-free 失败 transfer report 的快照绑定 quarantine/revoke 见 `MemoryPromotionAdapter.quarantine_failed_report()`。
- [x] T160-15 统一 provider-free solver adapter contract：生命周期、request pins、预算/deadline、terminal status、recovery 和 ownership receipt；OpenEvolve/Shinka 仅声明 fixture capability，不启动真实项目。
- [x] T160-16 增加 provider-free frozen-memory transfer regression 窄版本：no/old/current memory 对照、seen/unseen 多目标、重复试验、污染检查和 promotion evidence；已由 controller 的显式 `promote_transfer_regression()` 组合入口按调用方请求接线，默认自动触发和真实 evaluator 仍待接线。
- [x] T160-17 增加 provider-free failure-driven curriculum 窄版本：failure cluster、capability coverage、hard-negative/boundary probe、重复抑制、预算审计和 canonical ledger replay；可选 controller checkpoint/resume 接线及显式可配置 policy、policy-bound digest/replay 已完成（见 `curriculum-policy.md`），复杂 bandit/RL 后置。
- [x] T160-18 增加显式 transfer-report → memory-governance promotion adapter：校验 report digest、holdout/baseline/regression evidence 和 CAS，强制 shadow → approved → active 两步晋级。
- [x] T160-19 增加 provider-free 用量/成本 accounting 窄版本：run/episode/adapter-stage append-only JSON receipt、CAS/hash-chain、未知 token/time fail-closed、可配置估算成本、预算摘要和 durable reopen。真实 provider billing、GPU 计量和真实 process adapter 接线仍待后续。
- [x] T160-20 增加 controller-level transfer promotion 组合入口：冻结当前/parent memory，执行本地 transfer regression，校验 solver/verifier/curriculum/judge fingerprint 与 CAS，并通过 `MemoryPromotionAdapter` 强制 `shadow → approved`（可选 `approved → active`）；重复调用只读重放，不重复 runner 或 governance revision。该入口为显式 opt-in 的 provider-free 路径，不等于默认自动调度或真实 evaluator 接线。
- [x] T160-21 增加 clean-room verdict admission bridge：严格校验 episode、source/dependency/task/evaluator provenance 与 `pass` verdict，幂等写入 governance 的 `observed → verified`；不修改 `RSIMemoryStore`，不自动推进 candidate/shadow，也不提供外部真实性证明。

## 本轮边界

- v2 durable plan 允许完成已知 episode 后继续原计划中的新 target/practice；已写入 running 的未知 solver 请求不得重发。
- 没有完整 plan 的旧 checkpoint 只恢复已存在的证据，不猜测缺失的 BRS wave 或创建后续 episode。
- 本轮验证只使用本地 fixture。OpenEvolve/Shinka/native 的 fixture ID 和 receipt 协议通过，不等于真实 producer campaign 或模型效果已经验收。
- `RSIRunBudget` 的 depth/cycle API 不代表已实现 solver→RSI 嵌套调度；当前 DRS/BRS 是 depth 0。真实递归、嵌套资源预算与 token/成本统计保留在后续任务。
- T160-12 的真实 Actor、官方 evaluator、真实 producer lifecycle/adapter 接线、holdout/transfer regression 的 controller 自动接线和复杂 curriculum 仍按阶段报告独立推进；不增加分布式平台、自修改 Agent 或模型训练实现范围。
- 专用 callback 恢复接口已具备；真实 worker ownership/heartbeat/workspace 检查和旧不确定记录的迁移仍有开放边界，不能由本地矩阵推导生产恢复或分布式 exactly-once。
