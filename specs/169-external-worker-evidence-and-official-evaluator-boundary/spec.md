# Feature 169 — External worker evidence and official evaluator boundary

**状态：SDD 规格，provider-free 本地实现阶段。**

Feature 160 已完成本地 native RSI 的 request/memory/plan、candidate、execution、evaluation、publication 和 provenance sidecar 组合。Feature 169 只补齐两个独立的可信证据边界：外部 worker 的 ownership/生命周期证据，以及 official evaluator 的独立结果收据。

## 目标

一个 worker 的 terminal receipt 不能证明 evaluator 通过；一个 evaluator score/pass 也不能证明 worker 属于本次 launch。只有两类收据都绑定同一 attempt、request、plan、candidate 和输入指纹，且 controller 自己观察到终态与清理完成时，才允许 native gateway 构造 authoritative `SolverResult`。

## Worker evidence

`ExternalWorkerTrustProfile` 固定 project/version/commit、executable/runtime/dependency digests、launch intent、parent/task/episode、owner token、PID/PGID/start identity、workspace/transport/journal inode。首次 claim 为 create-only；heartbeat 和 terminal receipt 只能追加，状态限定为 `running|completed|failed|cancelled|timed_out|unknown|recovery_required`。

`unknown` 只能进入 quarantine，或通过 controller-owned 的失败/取消/超时终态收据结束；调用方声明不能把 unknown 变成 passed。恢复必须重新检查 PID/PGID/start identity、workspace、transport 和 journal，拒绝 inode 替换、owner token 漂移、过期 heartbeat 和重复 terminal callback。

## Evaluator evidence

`OfficialEvaluatorProfile` 固定 evaluator code/config/version、contract/task/input/holdout/seed、candidate source/execution/publication digests、clean-room workspace 和 raw verdict。`EvaluationReceipt` 必须由 controller 绑定的 evaluator runner 产生；score 仅为 informational，缺失、篡改、holdout mismatch、unsigned/unknown receipt 均为 unresolved。

## Non-goals

本 feature 不启动真实 OpenEvolve/Shinka campaign、不访问远程 evaluator、不提供分布式 lease、不增加自动后台 scheduler，也不把模型分数直接写入 memory。

## 本机 process/workspace evidence adapter（P1 窄接线）

`external_worker_process_evidence.py` 提供只读的本机 `observe_local_worker()`。它重新读取
claim 中的 PID/PGID/start identity，并用当前主机的进程接口核对精确进程和私有进程组；同时用
`lstat` 比较 workspace、transport、journal 的设备号/inode，拒绝符号链接替换。只有 PID 已退出、
进程组也已消失、三处对象仍匹配时，观察结果才允许通过 `reconcile_evidence()` 绑定到失败、取消、
超时或放弃收据。

该适配器不会发信号、启动 worker、把权限错误当作退出、或提供远程来源认证。进程身份不可读、
进程组 probe 被拒绝、对象缺失或指纹漂移都会保留为 `unknown`/`drifted`，不得生成 reconcile
证据。它只证明一次本机观察，不能推导多机 ownership、exactly-once 或官方 evaluator 结果。
