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


## 2026-10-07 terminal authority correction

- Native attempt/cleanup/worker verifier/formal receipt/RSI scheduler/gateway integration:
  **138 passed, 0 skipped/failures/errors**, `/tmp/lunar-native-terminal-integration-oct7.xml`.
- CI runner/annotation/cleanroom integration: **113 passed, 0 skipped/failures/errors**,
  `/tmp/lunar-ci-evidence-integration-oct7.xml`.
- Independent review found an overflowing integer deadline could escape as `OverflowError`.
  Pure deadline validation now rejects it with the fixed drift code; the two huge-integer
  cases are included in the final worker/cleanup focus (**68 passed**, 0 failures/errors),
  `/tmp/lunar-worker-terminal-final-numeric-oct7.xml`.
- Ruff (`src tests tools`), compileall and `git diff --check` passed.

Worker focus covers handshake-only pass/failure and absent evidence staying unknown;
zero/nonzero/signal/cancellation classifications; unknown handshake plus verified cancellation;
rehashed owner/task/launch/registration/deadline/cleanup/status drift; malformed records;
cleanup still alive even after linked rehashing; no I/O/process/clock effects; actual local C
exit0/exit7 matching native read-only recovery with unchanged receipt bytes/inodes.
The existing native suite covers actual live cancellation and cleanup uncertainty.

Runner focus proves no current retry, narrow known archive failure only, no retry on incomplete
inventory/mixed failures/errors/other node/pytest crash, independent first/retry XML hashes,
and no third attempt. Annotation focus retains the known first failure as a warning only after
complete successful retry, while missing/malformed/failed retry and unrelated failures block.
Both XML files remain CI artifacts. Archive/frozen commits, manifests and test bytes are unchanged.

A local full regression run started before the final numeric-boundary correction; its result
cannot stand in for a final-head matrix. The committed head must independently pass Ubuntu
Python 3.11/3.12/3.13 full current/archive/frozen CI before merge. No model, external project
campaign, remote/company evaluator or multi-host acceptance is claimed.
