# Tasks

- [x] T160-01 定义 RSI run、practice episode、verifier decision、memory snapshot 和 transfer receipt（协议 MVP）。
- [x] T160-02 增加 canonical digest、scope/compatibility 和 read-only snapshot loader（协议 MVP）。
- [x] T160-03 增加 provider-free SolverGateway 请求/结果边界与 deterministic mock fixture。
- [x] T160-04 增加独立 Verifier 接口 fixture，拒绝未验证、unknown、abandoned 和篡改 episode。
- [x] T160-05 实现 verifier-gated memory commit 和 compare-and-swap parent snapshot fixture。
- [x] T160-06 实现 BRS broad wave 的 provider-free 并行 practice、验证后有序合并和 frozen-parent 校验；持久恢复仍待补齐。
- [x] T160-07 实现 DRS target attempt → capability gap → practice → retry target，并对 unknown/timeout/abandoned/cancelled 短路。
- [x] T160-08 实现 frozen-memory transfer test，并在测试期间锁定 memory/curriculum 写入。
- [x] T160-09 增加本地 mock/native/OpenEvolve/Shinka provider-free 集成 fixture 和
  target/practice timeout、abandoned、cancelled 状态矩阵；BRS 遇到不确定 worker 会保留
  wave evidence 并阻止合并；全链路 DRS fixture 回归通过。
- [x] T160-10 增加显式本地 CLI/诊断/恢复入口（`rsi run|inspect|reconcile`）；真实 solver adapter、durable controller resume 和 LLM curriculum 仍待后续阶段。
- [x] T160-11 将 candidate source、dependency、actor/solver fingerprint 和 bounded public action/tool/observation trace 纳入 episode evidence；MemoryItem 增加 condition/action/observed-result/applicability 因果投影。
- [ ] T160-12 接入真实 Actor environment runner，并由独立 verifier 重开和校验 evaluator receipt；provider-free fixture 不得替代该验收。
- [ ] T160-13 增加 durable controller-level resume、unknown reconcile gate 和 diversity/failure-boundary curriculum policy。
  - [x] 阶段 1：controller-level durable resume、evidence-bound unknown reconcile、fingerprint drift gate、预算/深度/终止状态持久化。
  - [ ] 阶段 2：diversity/failure-boundary curriculum policy（仍待实现）。
