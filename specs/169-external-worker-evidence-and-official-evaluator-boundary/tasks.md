# Tasks

- [x] T169-01 定义 canonical `ExternalWorkerTrustProfile`、create-only claim、heartbeat、terminal receipt 和 owner/attempt binding。
- [x] T169-02 实现 provider-free worker evidence store，覆盖 PID/PGID/start identity、workspace/transport/journal inode drift、heartbeat loss、duplicate callback、unknown quarantine。
- [x] T169-03 定义 `OfficialEvaluatorProfile` 与独立 `EvaluationReceipt`，分离 score、raw verdict 和 authority。
- [x] T169-04 实现 evaluator receipt verifier，拒绝 source/execution/publication/holdout/seed/config drift 与 score spoof。
- [x] T169-05 将两类 receipt 绑定到 NativeRSISolverGateway 的 same-attempt mapping；任一缺失只返回 unresolved/unknown。
- [x] T169-06 增加本地 subprocess/loopback fixture，运行 ownership、crash、cancel、timeout、recovery 和 tamper 矩阵。
- [x] T169-07 更新 Feature 160、priority-execution、HANDOFF，记录本地完成边界和真实 campaign 非目标。
- [x] T169-08 增加统一只读 worker evidence verifier，将 attestation、registration、handoff
  和 bootstrap handshake evidence 重新绑定；此历史实现不能单独建立 process terminal，
  已由 T169-09 收紧 completed/failed 分类。它不授予
  外部认证或多机 ownership 权限。

- [x] T169-09 修正统一 verifier：必须核验独立 native process terminal、原始 deadline、
  cleanup receipt，复用 native recovery 的纯 record 校验；alive_after 必须 false，
  handshake-only/缺证据保持 unknown。覆盖实际 C exit、取消/unknown、rehashed drift、
  只读重复核验，输出精确收据摘要。

## 当前边界

T169-01 至 T169-07 的本地 provider-free 实现已完成并合入 `main`。本地矩阵覆盖 claim、heartbeat、terminal cleanup、unknown quarantine、profile drift、独立 evaluator receipt、same-attempt gateway mapping、native replay、tamper 和三版本 CI。

T169-08 的 bootstrap-only 分类不足，T169-09 本地修正完成，当前分支验证后待 CI/合入。
所有 trusted status 都以完整 trusted-local receipts 为前提；不等于外部项目身份认证。

真实外部 worker 来源认证、远程/多机 ownership lease、官方远程 evaluator、真实 OpenEvolve/Shinka campaign 不属于本地完成声明。
