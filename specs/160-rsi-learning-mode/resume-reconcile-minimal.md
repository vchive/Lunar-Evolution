# Controller resume 最小闭环（阶段 1）

本文件区分旧 checkpoint 的证据恢复与 v2 checkpoint 的控制流续跑。
`RSILearningController.resume(run_id)` 在 per-run `controller_lock` 内读取 run、checkpoint、
episode head 和持久化 request/result。新启动的 v2 run 保存完整 DRS/BRS plan；它恢复已完成步骤，
再执行原计划中尚未启动的步骤。旧记录缺少完整 plan 时只恢复已有证据。

## 行为

1. `completed`、`failed`、`cancelled`、`budget_exhausted` 的 run 复用 terminal 结果，不重发 solver 或创建 episode。
2. `running`/`paused` 的 v2 run 先校验持久化 plan、pins、root/current snapshot 和预算，再恢复 execution、decision、judgment 和 memory commit。
3. 已有完整 request/result wire 的 episode 按原 ID、request digest 和结果证据 reconcile；已持久化的 verifier decision 直接复用。已有 gateway 结果的恢复不得再次调用 gateway。
4. 已持久化 launch intent、但尚无 episode head，表示 runner 还未记录启动；恢复可以执行该预留过预算的原请求。已存在 `running` head 而没有结果，则报 `rsi_resume_recovery_required`；不得因缺少结果重新发起 solver。
5. `unknown` 或缺少结果证据的 child 隔离整条 run，阻止 DRS 新 practice/retry 和 BRS wave 合并。解除隔离必须使用 evidence-bound reconcile，不能把 unknown 猜成成功或失败。原始结果 wire 保持不可变。
6. v2 plan 中后续尚未启动的 target/practice 可以创建其确定的 episode ID，并先预留、持久化预算和 intent 再启动。此类新工作属于原计划续跑，不是重试未知请求。
7. caller 提供的 `observed_fingerprints` 是附加断言；不能通过回传旧 fingerprint 掩盖当前组件变化。controller 重新计算当前组件代码及配置身份，并采用 exact-match gate。
8. fresh run 与 resume 使用同一 nonblocking controller lock。竞争控制器收到 `rsi_controller_busy`，不能把活跃 worker 当作已崩溃 worker。

## 幂等和不变量

- 相同 episode/request/result 的恢复不增加 gateway 调用；已落盘 terminal run 的再次恢复保持 record/receipt 不变。
- 原 plan、绝对 `deadline_unix` 和 planned budget 不扩大、不重置；已持久化 reservation 不重复扣除。新的 planned episode 消耗原 run 的剩余预算。
- result、reconciliation journal、controller checkpoint 和 run head 是依次持久化的边界。它们不是覆盖整个流程的一次事务，也不能声称任一步失败会回滚已发生的外部副作用；恢复通过证据、CAS 和幂等写入补齐后续边界。
- 已落盘 terminal checkpoint 应补齐尚未更新的 run head，恢复时刻超过 deadline 不应改写已经确定的终态。
- BRS 使用同一 frozen parent，全部 child 完成并解除不确定状态后才按 ordinal 合并；memory publication 中断必须复用已发布 snapshot。

## 验收状态

上述契约由 `test_rsi_resume_reconcile_contract.py`、`test_rsi_resume_matrix.py` 和
`test_rsi_durable_flow.py` 的本地中断测试覆盖，DRS/BRS 与 CLI 重复运行矩阵已通过；
当前轮次最终集成结果与数量见 `validation.md` 和交接记录。
不能仅凭旧的只读 resume 测试通过，就把 DRS/BRS 续跑、memory commit、transfer 和所有 unknown 分支标成完成。

真实 producer 的 PID/ownership、heartbeat、workspace、evaluator receipt 与进程仍存活判定，
属于后续受控 adapter/lifecycle 接线；本地 result fixture 不替代这些生产证据。

Frozen transfer 的 verifier/judge 已 started 却无结果时，通过 `reconcile_callback` 登记
带输入/结果/收据绑定的本地证据后续接，不重新调用 callback。已发布 unknown receipt 的
worker 明确失败后，`reconcile_receipt` 原子追加 failed revision，保留旧 receipt/result。

DRS/BRS 的 verifier/curriculum/judge 也已接入独立 started/result journal 和显式对账 API。
未知 callback 隔离整条 run；CLI 对账只登记结果，不自动续跑。对账预留一次 unknown 预算，
deadline 后允许收录已有结果，但不放宽后续工作期限。没有新 callback 协议标记的旧不确定
记录停在迁移门，不再把缺日志当作“从未调用”。这不认证真实外部来源，也不声称分布式 exactly-once。
