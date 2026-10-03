# Validation

本 feature 的验证只使用本地 subprocess、loopback transport、临时 workspace 和独立 fixture evaluator。

验收矩阵：

1. 正常 worker claim → heartbeat → terminal cleanup 产生一份可重放 receipt。
2. PID/PGID/start identity、owner token、workspace、transport 或 journal inode 替换被拒绝。
3. worker crash、heartbeat loss、timeout、cancel 和缺少 terminal receipt 进入 unknown/quarantine，不重启、不生成成功。
4. evaluator receipt 与 candidate source/execution/publication、task/holdout/seed/config 完整绑定；score 修改不能伪造 pass。
5. 只有 worker terminal evidence 与 evaluator pass evidence 同时匹配时，gateway 才能映射 `SolverResult`。
6. 重复完成、只读恢复和 receipt tamper 均幂等或 fail-closed。

禁止运行 WebAgent、远程 evaluator、公司评测平台、真实模型或真实 OpenEvolve/Shinka campaign。
