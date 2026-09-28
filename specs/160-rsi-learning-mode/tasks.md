# Tasks

- [x] T160-01 定义 RSI run、practice episode、verifier decision、memory snapshot 和 transfer receipt（协议 MVP）。
- [x] T160-02 增加 canonical digest、scope/compatibility 和 read-only snapshot loader（协议 MVP）。
- [x] T160-03 增加 provider-free SolverGateway 请求/结果边界与 deterministic mock fixture。
- [x] T160-04 增加独立 Verifier 接口 fixture，拒绝未验证、unknown、abandoned 和篡改 episode。
- [x] T160-05 实现 verifier-gated memory commit 和 compare-and-swap parent snapshot fixture。
- [x] T160-06 实现 BRS broad wave 的并行 practice、验证后有序合并和 frozen-parent 校验；持久 wave journal、unknown quarantine 和中断合并恢复已补齐。
- [x] T160-07 实现 DRS target attempt → capability gap → practice → retry target，并对 unknown/timeout/abandoned/cancelled 短路。
- [x] T160-08 实现 frozen-memory transfer test，并在测试期间锁定 memory/curriculum 写入。
- [x] T160-09 增加本地 mock/native/OpenEvolve/Shinka provider-free 集成 fixture 和
  target/practice timeout、abandoned、cancelled 状态矩阵；BRS 遇到不确定 worker 会保留
  wave evidence 并阻止合并；全链路 DRS fixture 回归通过。
- [x] T160-10 增加显式本地 CLI/诊断/恢复入口（`rsi run|inspect|resume|reconcile`）；CLI 只重建自己的 fixture run，真实 solver campaign 和 LLM curriculum 仍开放。
- [x] T160-11 将 candidate source、dependency、actor/solver fingerprint 和 bounded public action/tool/observation trace 纳入 episode evidence；MemoryItem 增加 condition/action/observed-result/applicability 因果投影。
- [ ] T160-12 接入真实 Actor environment runner，并由独立 verifier 重开和校验 evaluator receipt；provider-free fixture 不得替代该验收。
  本地 native candidate/evaluator 子进程及独立重评已实现；AgentLoop runtime/receipt profile
  指纹和路径绑定已实现。真实模型 Actor 环境验收及跨任务效果证据仍不能由本地 fixture 替代。
- [x] T160-12a 实现 NativePopulationGateway / NativeIndependentVerifier，重开候选、依赖、执行与
  评测证据，隔离重评，并在终态恢复时只读复核原证据、不重跑 solver/evaluator。
- [x] T160-12b durable AgentLoop Actor 必须提供 runtime/receipt 配置指纹，拒绝同名但配置变化的恢复。
- [x] T160-13 增加 durable controller-level resume、unknown reconcile gate 和 diversity/failure-boundary curriculum policy。
  包含 DRS/BRS checkpoint、跨进程锁、CAS/hash-chain、solver/settings/actor/环境指纹、
  verified terminal 幂等复用、memory lineage、CLI result-backed reconciliation 和历史反馈重建。
- [x] T160-14 冻结宿主声明的 task panel，对照 empty/frozen memory 的独立评测并持久化比较收据；
  21 项本地测试覆盖双合同、改善/持平/退步、篡改和中断不重跑。宿主负责已批准快照与 heldout
  来源；fixture 改善只证明测量方法，不证明真实模型泛化收益。
- [ ] T160-15 在生产边界闭合后单独验收真实 Actor、OpenEvolve/Shinka campaign；LLM curriculum 可选。
