# Tasks

- [ ] T169-01 定义 canonical `ExternalWorkerTrustProfile`、create-only claim、heartbeat、terminal receipt 和 owner/attempt binding。
- [ ] T169-02 实现 provider-free worker evidence store，覆盖 PID/PGID/start identity、workspace/transport/journal inode drift、heartbeat loss、duplicate callback、unknown quarantine。
- [ ] T169-03 定义 `OfficialEvaluatorProfile` 与独立 `EvaluationReceipt`，分离 score、raw verdict 和 authority。
- [ ] T169-04 实现 evaluator receipt verifier，拒绝 source/execution/publication/holdout/seed/config drift 与 score spoof。
- [ ] T169-05 将两类 receipt 绑定到 NativeRSISolverGateway 的 same-attempt mapping；任一缺失只返回 unresolved/unknown。
- [ ] T169-06 增加本地 subprocess/loopback fixture，运行 ownership、crash、cancel、timeout、recovery 和 tamper 矩阵。
- [ ] T169-07 更新 Feature 160、priority-execution、HANDOFF，记录本地完成边界和真实 campaign 非目标。
