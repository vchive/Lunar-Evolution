# RSI 本地运行接线指南

本指南对应 Feature 160 的当前 Python API。它说明已可组合的本地运行链路，执行边界以
[`HANDOFF.md`](../HANDOFF.md) 和
[`stage-gap-report.md`](../specs/160-rsi-learning-mode/stage-gap-report.md) 为准。
下面的 fixture 不调用模型或远程 evaluator，也不启动真实 OpenEvolve/Shinka campaign。

## 1. 选择治理入口

| 入口 | 适用情形 | 接线要求 |
| --- | --- | --- |
| `GovernedMemorySnapshotGate` | 消费一份已经完成治理的冻结快照 | exact snapshot digest、每个 memory ID 对应的 active admission、scope、compatibility |
| `RSIGovernanceCoordinator` | 同一个 DRS/BRS run 内生成新记忆并逐代晋级 | 同一 `RSILedger` 实例、冻结 task manifest、显式 trial runner、generation policy |

固定快照入口的最小形状如下；`snapshot` 和 `active_admissions` 必须来自已经验证的治理历史：

```python
from lunar_evolution import GovernedMemorySnapshotGate, RSILearningController, RSIMemoryStore

gate = GovernedMemorySnapshotGate(
    governance,
    snapshot_sha256=snapshot.digest(),
    admissions=active_admissions,  # {memory_id: admission_id}
    scope=scope,
    compatibility=compatibility,
)
controller = RSILearningController(
    gateway,
    verifier=verifier,
    ledger=ledger,
    memory_store=RSIMemoryStore(snapshot),
    memory_admission_gate=gate,
)
```

固定 gate 不会自动接纳新快照。需要在同一 run 内学习新记忆时，使用下一节的 coordinator。
两个入口都会在新 solver dispatch 前检查当前治理 head；撤销会阻止新的检索和执行。
已完成 run 的 `resume()` 是历史结果的只读重放，不代表其旧快照仍可用于新执行。

## 2. 同一 run 的 generation、holdout 和共享预算

以下示例保存为本地 `.py` 文件后可直接运行，会使用新临时目录。callback 源码必须可读取，
以便生成稳定 fingerprint。`trial(task, memory, repetition)` 应返回 `TransferObservation`；
正式接入时，其 pass、访问记录和收据必须由受信评测链路产生。

```python
import hashlib
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from lunar_evolution import (
    DeterministicMockSolver,
    GenerationGovernancePolicy,
    MemoryGovernanceStore,
    RegressionPolicy,
    RSIGovernanceCoordinator,
    RSILearningController,
    RSILedger,
    TransferObservation,
    TransferTask,
)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class LocalTrials:
    def rsi_fingerprint_config(self):
        return {"fixture": "local-rsi-guide-v1"}

    def __call__(self, task, memory, repetition):
        return TransferObservation(
            passed=True,
            score=0.3 + 0.2 * len(memory.items),
            accessed_task_ids=(task.task_id,),
            memory_ids_used=tuple(item.memory_id for item in memory.items),
        )


def target_judge(execution):
    return execution.episode.wave > 0, "fixture requests one practice round"


with TemporaryDirectory(prefix="lunar-rsi-guide-") as temporary:
    root = Path(temporary)
    ledger = RSILedger(root / "rsi.sqlite3")
    pins = {
        "contract": digest("fixture-contract"),
        "evaluator": digest("fixture-evaluator"),
        "environment": digest("fixture-environment"),
        "solver": "fixture",
    }
    tasks = (
        TransferTask("seen", "family-a", "seen", "seen-target", digest("seen-input")),
        TransferTask("unseen-a", "family-a", "unseen", "target-a", digest("unseen-a-input")),
        TransferTask("unseen-b", "family-b", "unseen", "target-b", digest("unseen-b-input")),
    )
    coordinator = RSIGovernanceCoordinator(
        MemoryGovernanceStore(root / "governance.sqlite3"),
        ledger=ledger,
        scope="fixture",
        compatibility=pins,
        policy=GenerationGovernancePolicy(RegressionPolicy(repetitions=2)),
    )
    controller = RSILearningController(
        DeterministicMockSolver(),
        ledger=ledger,
        target_judge=target_judge,
        memory_admission_gate=coordinator,
        generation_regression_tasks=tasks,
        generation_regression_runner=LocalTrials(),
        generation_revalidate_before_dispatch=False,
    )
    result = controller.run_drs(
        run_id="local-rsi",
        contract_sha256=pins["contract"],
        evaluator_sha256=pins["evaluator"],
        environment_sha256=pins["environment"],
        solver_id=pins["solver"],
        max_practice_rounds=1,
        max_target_attempts=2,
        budget={
            "max_solver_invocations": 3,
            "max_evaluator_invocations": 40,
            "max_verifier_invocations": 3,
            "max_transfer_invocations": 36,
            "max_unknown_retries": 4,
            "deadline_unix": time.time() + 60,
        },
    )
    assert result.status == "completed"
    coordinator.validate(result.memory_snapshot)
    assert controller.resume("local-rsi").memory_snapshot == result.memory_snapshot
```

新记忆先产生 candidate generation。coordinator 重新接纳该代的继承项，运行冻结的
`no_memory`、`old_memory`、`current_memory` 三个 arm，再把完整通过的 generation 激活。
holdout 失败则拒绝该代，controller 保留 parent snapshot；unknown 会阻止后续 solver。
调用方不能通过替换 manifest、runner、组件或父快照来继续同一 intent。

`GenerationCampaignRunner` 使用 `ParentRunBudget(ledger, run_id)`。每个 child trial 在
dispatch 前从原学习 run 同时扣除 transfer 和 evaluator 配额；恢复保留原绝对 deadline，
不会重置已用预算。单独调用 `DurableRegressionCampaign.run()` 时，通过
`parent_budget=ParentRunBudget(ledger, run_id)` 接入同一账户。parent run 必须已经存在，且
campaign 与 controller 使用同一个 ledger 实例。`validate_history()` 可只读检查预算历史。

将 `generation_revalidate_before_dispatch` 设为 `True`，会在每个携带非空 memory 的新
episode intent 前运行一次回归，validation ID 为 `dispatch:<request.digest()>`。
同一 request 的 before-run 检查复用已完成验证。BRS 由 controller 线程准备验证，worker
只读复核；回归失败会 quarantine 当前 generation，unknown 必须显式 reconcile。
该开关默认 `False`，开启后也消耗上述原 run 预算。它属于 run fingerprint，resume 时不能改变。
详见 [`controller-dispatch-revalidation.md`](../specs/160-rsi-learning-mode/controller-dispatch-revalidation.md)。

## 3. Actor 独立验证、完整 evidence 与显式 admission

Actor gateway 的 `workspace_root` 与 bridge 应一致。evaluator 必须是可导入模块中的顶层
函数，不能是 lambda、嵌套函数或仅存在于交互环境的函数，因为验证使用独立 spawn 进程。
evaluator 的 fingerprint 必须与 `evaluator_sha256` 一致。

```python
from lunar_evolution import (
    ActorCleanRoomEvidenceStore,
    AgentLoopCleanRoomVerifier,
    DurableActorCleanRoomVerifier,
)
from lunar_evolution.rsi_identity import component_fingerprint

bridge = AgentLoopCleanRoomVerifier(
    workspace_root,
    task_input=public_input_bytes,
    evaluator=importable_evaluator,
    evaluator_sha256=component_fingerprint(importable_evaluator),
    contract_sha256=contract_sha256,
    environment_sha256=environment_sha256,
    candidate_path="candidate.py",
    dependency_paths=("requirements.txt",),
    timeout_seconds=30,
)
evidence_store = ActorCleanRoomEvidenceStore(evidence_directory)
durable_verifier = DurableActorCleanRoomVerifier(bridge, evidence_store)
# 构造 controller 时传 verifier=durable_verifier。
```

wrapper 在返回 verifier decision 前写入完整 evidence sidecar。相同输入的已完成验证读取
旧记录；已有 started claim 而没有完整记录时返回 `rsi_actor_evidence_unknown_reconcile_required`，
不自动重跑 evaluator。恢复必须提供原先实际观察到的 decision 与完整 evidence，经
`evidence_store.save(...)` 的严格绑定检查写入，再按 controller callback 证据恢复协议登记。
不要删除 claim 来绕过 unknown；本 API 不负责认证外部 worker 的完成证明。

独立验证 pass 后，显式 admission 使用如下形状。这里的 `admission` 应由调用方创建，包含
memory snapshot/item、episode、parent、scope、compatibility、contract，以及独立持有的
source/dependency/task-input/evaluator pins：

```python
from lunar_evolution import CleanRoomAdmissionGate

verified = evidence_store.admit(
    execution.episode,
    execution.request,
    execution.result,
    verifier_config=bridge.rsi_fingerprint_config(),
    verifier_fingerprint=component_fingerprint(bridge),
    admission=admission,  # CleanRoomAdmissionRequest
    gate=CleanRoomAdmissionGate(governance),
)
assert verified.state == "verified"
```

`CleanRoomAdmissionRequest.expected_source_sha256` 和 `expected_dependency_sha256` 是
clean-room 原始 artifact digest；Actor result 中的 source/dependency manifest digest 是另一层
绑定，不能相互替代。`verifier_config` 和 `verifier_fingerprint` 使用 bridge 身份，不能换成
durable wrapper 的身份。该显式入口只推进 `observed → verified`；还需 candidate、shadow
和 holdout 才能 active。详见
[`actor-evidence-persistence.md`](../specs/160-rsi-learning-mode/actor-evidence-persistence.md)。

## 4. Unknown 的恢复顺序

generation holdout 有 child trial 和 outer holdout 两层持久 callback。恢复必须按以下顺序：

1. 检查原运行身份与实际完成证据。对 started child trial，使用
   `DurableRegressionCampaign.reconcile_trial(admission_id, callback_id, ...)`，提供该 callback
   的 checkpoint、原 binding digest、实际结果 digest 和 completion receipt。
2. 重新调用 `controller.generation_campaign_runner(run_id)(request)` 生成完整 child report。
   已完成 trial 只读重放，只执行确实未开始的剩余 trial。`request` 必须复原自原 generation
   intent；revalidation 还必须包含原 `validation_id`。child admission ID 使用
   `GenerationCampaignRunner.admission_id(request)` 派生，不能自行拼接。
3. 对 outer holdout 使用以下显式登记入口。传入的是 **outer callback 的 checkpoint**，不是
   generation 的 checkpoint；evidence 绑定完整序列化 report。
4. 最后调用 `controller.resume(run_id)`。若还有其他 unknown、预算耗尽或身份漂移，继续停止。

```python
settled = coordinator.reconcile_holdout(
    generation_id,
    expected_checkpoint_sha256=outer_callback_checkpoint_sha256,
    report=complete_child_report,
    evidence=outer_completion_evidence,
    validation_id=validation_id,  # 初次 admission 为 None；revalidation 必须使用原 ID。
)
result = controller.resume(run_id)
```

child 与 outer 的每次显式 reconciliation 分别扣除一个 parent `unknown_retries` 配额；
相同 evidence 的幂等重放不会再次扣费。evidence 的哈希绑定保证本地协议一致性，不能凭空
证明远程进程已经结束。fixture 中手工构造的 completion receipt 不可用于正式验收。
完整本地恢复示例见
[`test_rsi_controller_generation.py`](../tests/test_rsi_controller_generation.py) 和
[`test_rsi_controller_revalidation.py`](../tests/test_rsi_controller_revalidation.py)。

### 4.1 Solver 调用的持久记录

`DurableSolverGateway` 是显式启用的本地包装器。它在调用前记录 started，保存完整结果后
才返回；重复请求复用原结果。它与 controller 使用同一个 `RSILedger`，不再分配 solver
预算。调用方必须保持 `scope_id` 和完整请求不变；同一 episode 换 scope、配置或请求都会拒绝。

```python
from lunar_evolution import DurableSolverGateway, RSILearningController, RSILedger
from lunar_evolution.rsi_gateway import DeterministicMockSolver

ledger = RSILedger("/tmp/lunar-durable-example.sqlite3")
gateway = DurableSolverGateway(DeterministicMockSolver(), ledger, scope_id="my-learning-run")
controller = RSILearningController(gateway, ledger=ledger)
# 使用现有 controller.run_drs(...) 或 controller.run_brs(...)。
```

如果 adapter 的完整结果已落盘、controller 的结果登记尚未完成，可用原始请求调用
`gateway.restore_result(request)`，再调用 `controller.resume(run_id)`。这一步只复核并登记
已保存的结果，不启动 worker。若只有 started、没有完整结果，恢复会停止；显式
`reconcile(...)` 只接受失败、取消、超时或放弃，不接受 completed 或 unknown。

这套协议依赖受信本地代码和 SQLite，不能认证外部 worker，也不承诺远程调用 exactly-once。
候选与 evaluator 收据仍需独立验证；包装器不授予记忆晋级权限。详细契约见
[`durable-adapter.md`](../specs/160-rsi-learning-mode/durable-adapter.md)。

### 4.2 读取已发布 native 候选的证据

`read_native_retained_candidate` 供调用方显式读取已经发布的候选及其完整材料。调用方需要
原始 native recovery 参数、指定 candidate ID、原 published journal 和正式 producer
execution receipt 的摘要；它不会选 best、启动 solver、重新评测或修改账本。

```python
from lunar_evolution import read_native_retained_candidate

evidence = read_native_retained_candidate(
    workspace,
    candidate_id=candidate_id,
    expected_journal_sha256=published_journal_sha256,
    expected_producer_execution_receipt_sha256=producer_execution_receipt_sha256,
    **native_recovery_pins,  # 原 intent/attestation/artifact/contract/groups 和 evaluator 等 pins。
)
materials = dict(evidence.portable_materials)  # 独立字典；值是已验证的不可变 bytes。
metadata = evidence.to_dict()  # 原生证据身份和材料 hash/size，不含原始源码。
```

只接受精确匹配的 published 终态；prepared、unknown、部分提交和缺失/漂移的证据都会拒绝。
它要求当前 archive/state 仍匹配原 transaction 的发布摘要；后来推进过的 population 需要
单独的历史证据读取协议。该 API 不创建 workspace、lock 或收据，重复读取保持原文件不变。

此前未绑定输入的 native launch 没有 RSI episode、memory 或完整 SolverRequest，因此这里返回的是
`NativeRetainedCandidateEvidence`，不能拿它追认某次 RSI 求解或记忆的效果。bundle digest、
入口源码 digest、producer execution、candidate execution、evaluation receipt/result 均有独立
字段；`native_dependency_sha256` 也不等于 Actor dependency manifest。候选分数保留为来源
信息，RSI 学习仍需要独立 verifier 和 holdout。完整契约见
[`native-retained-evidence.md`](../specs/160-rsi-learning-mode/native-retained-evidence.md)。

### 4.3 在 native 启动前交付 RSI 请求与冻结记忆

`prepare_native_rsi_inputs` 保存原始完整 `SolverRequest` 和 approved `MemorySnapshot`，
返回只含两个精确文件的 read paths。输入保存在独立 `.rsi-input` 目录，不能放进 target
可写的 work/output 中。先准备输入，再把 manifest 摘要加入原 intent 的末尾 argv，最后
构造一次性 attestation 并绑定原 launch：

```python
from lunar_evolution import (
    bind_native_rsi_launch,
    prepare_native_rsi_inputs,
    validate_native_rsi_launch_inputs,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)

inputs = prepare_native_rsi_inputs(
    workspace, journal_id=journal_id, request=request, memory=approved_snapshot,
)
intent = build_producer_launch_intent(
    **launch_options,  # 原 launch/contract/evaluator/environment 等配置。
    journal_id=journal_id,
    argv=(*target_argv, *inputs.argv_fragment),
    working_directory="work", output_directory="output",
)
attestation = build_producer_launch_attestation(intent, once_id)
bound = bind_native_rsi_launch(
    workspace, intent=intent, attestation=attestation, artifact=artifact, inputs=inputs,
)
retained = validate_native_rsi_launch_inputs(
    workspace, intent=intent, attestation=attestation, artifact=artifact,
)
assert retained == bound
```

target 从 `work` 读取 `../.rsi-input/request.json` 和 `../.rsi-input/memory.json`，需要明确
支持这两个输入及保留的 argv 标记。manifest/binding 的原 inode 和摘要都会复验；只复制
相同 bytes 到另一个 inode、去掉 argv 标记、事后补绑定或修改任何输入都不能继续执行。
Linux 含只读输入的 profile 也拒绝 chmod/fchmod/fchmodat/fchmodat2；work/output 仍可创建
和写入文件，不能依赖运行中修改权限。

正式 native attempt 在消费前、gate 前、终态写入前及恢复时复验输入。原 `deadline_unix`
仅映射一次到本次 monotonic deadline，再与 caller/intent 取更早边界。历史只读恢复允许
原 deadline 已过，不刷新预算、不重新执行。求解/评测计数仍由 RSI controller 管理。

正式 native bootstrap 现在持有 controller lifeline：单独杀死 controller 会停止原进程组
内的 target。缺少终态确认仍保留 unknown；该机制不提供恢复进程额外的 signal 权限。
正式 attempt 还将原 intent/parent/RSI deadline 一次映射给 bootstrap 和 broker；控制器
暂停而管道仍打开时，bootstrap 也会在原到期时间停止自己的组。直接 target 退出后
guardian 会随 bootstrap 结束，遗留 descendants 的持续监督仍需后续清理协议。
这些 API 只完成启动前输入交付，不生成 `SolverResult`，不证明记忆改善效果，也未接通
controller cancellation 或 unknown-to-success 对账。完整契约见
[`native-launch-inputs.md`](../specs/160-rsi-learning-mode/native-launch-inputs.md) 和
[`native-controller-lifeline.md`](../specs/157-producer-request-evidence/native-controller-lifeline.md) 和
[`native-deadline-guard.md`](../specs/157-producer-request-evidence/native-deadline-guard.md)。

## 5. P2：显式 memory 翻译与重复评测置信策略

两个 API 都已从 `lunar_evolution` 导出，目前是独立、显式入口，不会自动替换 controller
的晋级判断。翻译需要调用方声明 solver/contract 映射，保留 source 证据：

```python
from lunar_evolution import SolverMemoryMapping, recover_translation, translate_memory

mapping = SolverMemoryMapping(
    mapping_id=mapping_id,
    source_solver_id=source_solver_id,
    target_solver_id=target_solver_id,
    source_solver_fingerprint=source_solver_fingerprint,
    target_solver_fingerprint=target_solver_fingerprint,
    source_contract_sha256=source_contract_sha256,
    target_contract_sha256=target_contract_sha256,
    condition=target_condition,
    action=target_action,
    applicability=target_applicability,
    rationale=mapping_rationale,
)
candidate = translate_memory(
    source_snapshot, source_memory_id, mapping,
    expected_source_receipt_sha256=source_receipt_sha256,
    candidate_id=target_memory_id,
)
draft = candidate.draft_memory_item()
replayed = recover_translation(
    candidate.to_bytes(), source_snapshot=source_snapshot, mapping=mapping,
    expected_source_receipt_sha256=source_receipt_sha256,
    expected_receipt_sha256=candidate.receipt_sha256,
)
```

`draft` 为 unresolved，必须在目标 solver 下重新独立验证并通过 holdout；翻译收据不是
目标 verifier 证明，也不能把 draft 直接放入 approved snapshot。

置信接口消费已取得的原始布尔 pass 记录，不调用 evaluator：

```python
from lunar_evolution import (
    ConfidencePolicy,
    PassObservation,
    evaluate_transfer_confidence,
    recover_confidence_report,
)

# 每个 arm 为 PassObservation(task_sha256, repetition, seed, passed, receipt_sha256, score=None) 序列。
policy = ConfidencePolicy(min_samples=8, confidence_level=0.95, min_pass_rate=0.75)
report = evaluate_transfer_confidence(
    observations,  # keys: no_memory、old_memory、current_memory
    task_manifest_sha256=task_manifest_sha256,
    evaluator_fingerprint=evaluator_fingerprint,
    policy=policy,
)
replayed = recover_confidence_report(
    report.to_bytes(),
    expected_receipt_sha256=report.receipt_sha256,
    expected_task_manifest_sha256=task_manifest_sha256,
    expected_evaluator_fingerprint=evaluator_fingerprint,
    expected_policy=policy,
)
```

三个 arm 必须具有相同、按顺序排列的 task/repetition/seed 覆盖，每个 task 至少两次。
重复 seed、重复 observation receipt 和不可比较的覆盖会拒绝；样本不足或区间不确定返回
unresolved。只有 pass 才允许 `report.promotion_evidence()`。Wilson 区间是各 arm 的边际
置信区间，不提供全部比较的联合置信保证；正式接线还须把 raw receipts、manifest、
evaluator 与实际 campaign 和 snapshot pair 一一绑定。

## 6. 验证边界和阅读入口

- 本地 fixture 回归验证恢复、预算、治理、证据绑定和污染拒绝协议，不能证明真实效果。
- 正式项目信任接入仍需实际 Actor artifact、官方 evaluator、producer ownership、完整
  cleanup/recovery/transport 和可信完成证据；Python callback 是受信本地代码，不是 OS sandbox。
- 真实效果验收需要独立任务集、冻结 baseline、重复 seed 和用量记录；必须另行按当前运行授权执行。

对应 SDD：[`generation-governance.md`](../specs/160-rsi-learning-mode/generation-governance.md)、
[`controller-generation-governance.md`](../specs/160-rsi-learning-mode/controller-generation-governance.md)、
[`shared-parent-budget.md`](../specs/160-rsi-learning-mode/shared-parent-budget.md)、
[`memory-translation.md`](../specs/160-rsi-learning-mode/memory-translation.md)、
[`noise-confidence.md`](../specs/160-rsi-learning-mode/noise-confidence.md)。
