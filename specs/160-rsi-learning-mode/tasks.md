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
- [ ] T160-12 接入真实 Actor environment runner，并由独立 verifier 重开和校验 evaluator receipt；provider-free fixture 不得替代该验收。
- [ ] T160-13 增加 durable controller-level resume、unknown reconcile gate 和 diversity/failure-boundary curriculum policy。
  - [x] 阶段 1 基础：append-only run/episode ledger、controller lock、CAS/hash-chain checkpoint、immutable request/result wire 和 evidence-bound episode reconcile。
  - [x] 阶段 1 控制流实现：v2 checkpoint 持久化 DRS/BRS plan、launch intent、curriculum decision、execution、judgment、memory snapshot 和预算；恢复可进入原计划中后续尚未启动的 episode。
  - [x] 阶段 1 identity 实现：恢复时重新计算当前 gateway/verifier/curriculum/target-judge 配置及代码指纹；mutable instance、函数捕获和 bound method 配置需可审计的显式 hook。
  - [x] 阶段 1 预算基础：planned/consumed/remaining、绝对 `deadline_unix`、原子 solver/evaluator/verifier 预留和 budget-exhausted 终态；预算模块提供 depth/cycle 与 unknown-retry gate。
  - [x] 阶段 1 本地集成矩阵：DRS/BRS 中断、显式 unknown 失败/无结果取消、memory publication、terminal journal 优先于恢复 deadline、逐 verifier deadline、并发锁，以及 CLI 重复 `rsi run` 的 fixture 回归。
  - [x] 阶段 1 frozen transfer 基础恢复：请求/组件/预算绑定、结果与 receipt publication 中断恢复、terminal receipt 重放和未知 callback 隔离；最终测试数量由集成报告补充。
  - [ ] 阶段 1 剩余恢复接口：transfer verifier/judge 已 started 但没有持久结果时，提供专用 evidence-bound reconcile/续接 API；当前明确隔离，不能自动重试。
  - [ ] 阶段 1 真实 callback 语义：DRS/BRS verifier/curriculum/judge 在调用内部中断、结果未保存时，当前允许重算本地 deterministic fixture；真实 callback 的 started gate、外部幂等或 evidence-bound reconcile 尚未接通，不能宣称 exactly-once。
  - [ ] 阶段 1 剩余 transfer 分支：已发布 unknown transfer receipt 后，即使 worker 已显式 settle，仍返回 `rsi_transfer_unknown_receipt_reconcile_required`；后续需定义显式 receipt reconcile 语义，不能覆盖旧 receipt。
  - [ ] 阶段 2：diversity/failure-boundary curriculum policy（仍待实现）。

## 本轮边界

- v2 durable plan 允许完成已知 episode 后继续原计划中的新 target/practice；已写入 running 的未知 solver 请求不得重发。
- 没有完整 plan 的旧 checkpoint 只恢复已存在的证据，不猜测缺失的 BRS wave 或创建后续 episode。
- 本轮验证只使用本地 fixture。OpenEvolve/Shinka/native 的 fixture ID 和 receipt 协议通过，不等于真实 producer campaign 或模型效果已经验收。
- `RSIRunBudget` 的 depth/cycle API 不代表已实现 solver→RSI 嵌套调度；当前 DRS/BRS 是 depth 0。真实递归、嵌套资源预算与 token/成本统计保留在后续任务。
- T160-12 的真实 Actor、clean-room verifier、真实 producer lifecycle/adapter 接线、memory governance、holdout/transfer regression 和复杂 curriculum 仍按阶段报告独立推进；不增加分布式平台、自修改 Agent 或模型训练实现范围。
- 真实 worker ownership/heartbeat/workspace 检查及 callback 不确定结果的专用恢复接口仍有开放边界；阶段 1 整体不能因本地矩阵通过而标成全部完成。
