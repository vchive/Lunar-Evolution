# Feature 160：控制器 callback 的持久恢复契约

本文延续阶段 1，不增加新的 RSI 学习目标。范围是本地 DRS/BRS 的 verifier、target
judge、curriculum，以及 frozen transfer 的显式对账入口。DRS/BRS 使用独立 callback
journal；transfer 为兼容既有 v1 checkpoint 保留原 journal，恢复原则相同但 wire 不同。
测试只使用本地
fixture；本轮不运行模型、WebAgent、远程 evaluator 或真实 producer campaign。

## 1. 必须保持的边界

callback 返回前进程可能退出。`started` 只证明调用已被允许开始，不能证明它未运行、失败
或可安全重试。恢复遇到没有结果的 `started` 日志时必须停在 reconcile gate，不再次执行
callback，不调用其他 solver/verifier/judge/curriculum，不发布 memory。BRS 必须先检查
整波的不确定 callback，再执行任一恢复副作用。

已有完整结果时读取原结果。若 callback 结果已落盘、episode 或 controller checkpoint
尚未推进，恢复只补齐后续记录。显式对账只登记已有结果，不调用 callback，不自动续跑。
之后的 `resume` 按原计划和剩余预算继续。未完成的 solver 结果只生成本地 unresolved
诊断，不能经 callback 对账变成缺少原执行证据的 pass。

这是一条 **local trusted evidence** 路径。摘要用于绑定原始输入、组件和结果、防止错误
拼接；它们不认证外部来源，不证明调用方的声明真实，也不提供真实外部系统的 exactly-once
保证。后续接真实 callback 仍需来源认证、进程归属或外部幂等协议的独立验收。

## 2. 稳定身份与 append-only 日志

每次调用使用稳定 callback ID：

| stage | callback ID | 不可变输入 |
| --- | --- | --- |
| verifier | `verifier:{episode_id}` | 原 `SolverRequest` 和已保存 `SolverResult` |
| judge | `judge:{target_id}` | 完整已验证 `EpisodeExecution` |
| curriculum | `curriculum:{practice_id}` | target episode、diagnosis、wave、ordinal |

binding 包含 `stage`、`input`、`component_sha256`。开始调用前追加 `started`；返回值通过
对应的 schema 和身份校验后再追加结果。相同 ID 的 binding 不得更换。原始 `started`、
结果和 reconcile 记录全部保留，当前 head 用 digest 做 compare-and-swap。

组件校验使用当前真实组件的代码与配置指纹，不能以 caller 提供的旧 observed 指纹代替。
同一 run 的 launch、resume、reconcile 共用 controller lock；并发调用不能绕过 gate。

新 run payload 与 v2 flow checkpoint 固定 `callback_protocol_version="1"`。升级前旧 v2
记录没有该标记时，若已存在 episode head，不能把「没有 callback 日志」解释为「从未调用」；
恢复须拒绝并返回 migration gate。尚无任何 episode 的旧记录可以安全初始化新协议。
更旧的非 v2 证据若缺少 verifier decision，也不得自动重调用户 verifier。已保存完整终态的
旧 run 仍可只读返回；本轮不实现对未知旧 callback 的自动迁移或重新运行。

## 3. 控制器接口

```python
digest, state = controller.callback_checkpoint(run_id, callback_id)
# 不存在时返回 None。

controller.reconcile_callback(
    run_id,
    callback_id,
    expected_checkpoint_sha256=digest,
    result=result_wire,
    evidence={
        "source": "local-fixture-or-local-operator",
        "binding_sha256": digest_of(state["binding"]),
        "result_sha256": digest_of(result_wire),
        "receipt_sha256": original_receipt_digest,
    },
)
```

`source` 必须非空；所有摘要必须是合法 SHA-256。binding 和 result 摘要必须匹配原绑定及
提交的精确 canonical wire。`receipt_sha256` 表示调用者保留的本地证据标识，不伪装为
已完成外部真实性认证。旧 CAS head、不同 binding、不同结果或证据均拒绝。

result wire 按 stage 严格解析：

- verifier：`VerifierDecision.to_dict()`；episode ID、contract、evaluator、environment、
  candidate/execution/official receipt 和 evidence 必须绑定原请求与结果。pass 必须满足
  原始 completed 结果、必备收据、独立性及全部检查通过，不能伪造 pins 绕过验证。
- judge：仅接受 `{"accepted": bool, "diagnosis": str}`。不得将非布尔值强制转换成 accepted；
  judge 的接受仍受 `execution.passed` 限制。
- curriculum：完整 `CurriculumDecision.to_dict()`，沿用字段、长度和 solver 兼容性校验。

已经处于终态的 run 拒绝新的对账写入。相同成功对账的精确重放只返回已有结果，不追加
记录、不重复扣预算。允许完成已发生调用的结果登记晚于原 deadline；后续新副作用仍必须
遵守原 deadline，不能因对账而续期。

## 4. 统一预算

首次成功登记不确定 callback 结果预留并持久化一次 `unknown_retries`。上限为零时拒绝
对账，保持原日志和预算。schema、evidence、指纹、CAS 校验失败不能扣减预算。
callback 已保存结果的自动重放和相同显式对账的重放不能再次计数；solver、evaluator、
verifier 等原有 invocation 计数不能因为恢复重置或重复增加。

## 5. 本地验收矩阵

- verifier、judge、curriculum 调用内部中断：恢复停在 gate，原 callback 调用数不增加。
- 显式有效对账后 DRS 续跑，原 callback 不重调，unknown 预算只消耗一次。
- callback 结果持久化后、episode/controller checkpoint 前中断：恢复复用原结果。
- 非法 result wire、错绑定 pins、receipt/evidence 摘要、旧 CAS 和组件漂移均拒绝，且无新副作用。
- BRS 任一 child 有不确定 callback 时，其余 child 不产生恢复副作用或 memory commit。
- unknown 预算为零时拒绝结果登记，精确对账重放不重复扣预算。
- 持有 run lock 的并发操作不能穿过对账入口；终态 run 不接收新的对账。

具体通过数量和剩余边界由 `validation.md` 的集成结果记录；本文件是行为契约，不以测试
文件存在或日志表存在作为完整生产恢复能力的证明。

## 6. Frozen transfer 对账入口

transfer 的 verifier/judge `started`、返回结果和预算已经保存在原 transfer checkpoint。
它继续使用独立的 `rsi-transfer-` namespace、原始 `intent` 和 controller lock，不将旧记录
转换为 DRS/BRS callback journal。

```python
new_checkpoint_digest = transfer_runner.reconcile_callback(
    run_id,
    target_id,
    stage="verifier",  # 或 "judge"
    expected_checkpoint_sha256=transfer_checkpoint_digest,
    result=result_wire,
    evidence={
        "source": "local-retained-callback-result",
        "binding_sha256": digest_of(transfer_checkpoint["intent"]),
        "result_sha256": digest_of(result_wire),
        "receipt_sha256": callback_receipt_digest,
    },
)
```

transfer evidence 仅接受上面的四个字段。verifier 的 `receipt_sha256` 必须等于 decision
中的 receipt；judge 的该字段必须等于 judgment canonical digest。当前组件指纹、原
request/snapshot、episode head、持久 solver result 和预算历史全部校验后，在一个
SQLite 事务内写入结果、一次 unknown 预算和证据绑定。该调用不运行 callback；之后调用
原 `run(...)` 继续固定请求。相同 evidence/result 的原 CAS 重放只读返回当前 checkpoint。

已经发布的 unknown transfer 收据不能直接修改，也不能因为 judge 接受而变成成功。
须先由 ledger 显式将原 episode 对账为 failed/cancelled/timed_out/abandoned，再调用：

```python
failed_receipt_record = transfer_runner.reconcile_receipt(
    run_id,
    target_id,
    expected_record_sha256=original_unknown_receipt_record_digest,
    evidence={
        "source": "local-worker-failure-settlement",
        "receipt_record_sha256": original_unknown_receipt_record_digest,
        "episode_record_sha256": settled_episode_record_digest,
        "journal_sha256": episode_reconciliation_journal_digest,
    },
)
```

此入口只追加 failed 收据 revision，并在同一事务内写入 transfer checkpoint 与一次
unknown 预算。原 unknown 收据和原 solver result 保留；诊断视图不伪造成功执行收据。
不同 evidence、旧 CAS、未通过 episode reconcile、组件漂移、预算回退均拒绝；精确重放
不再次扣预算。unknown→passed 不在本轮恢复范围内，必须有新的独立规格和完整成功证据。
