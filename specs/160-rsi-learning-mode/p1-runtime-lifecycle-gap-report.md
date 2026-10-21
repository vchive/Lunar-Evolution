# P1 runtime 与 producer lifecycle gap report

日期：2026-10-17  
基线：`origin/main` `a82f55a`（PR118）  
范围：OpenEvolve、ShinkaEvolve、本地 producer lifecycle、取消/清理和 RSI CLI。  
执行边界：只检查仓库代码和 provider-free fixture；本轮没有启动真实模型、远程
evaluator、WebAgent、OpenEvolve/Shinka campaign 或公司评测平台。

## 结论

当前代码已经提供两条不同的本地边界：

1. OpenEvolve 有一个显式注入的 **native trusted** 单次执行路径。它能在固定
   launch intent、一次性 attestation、native bootstrap 和 host-only broker 的约束下
   完成 claim、进程执行、请求计数、清理、独立本地评测、seed admission、publication
   acknowledgement 和只读 replay。
2. ShinkaEvolve 有一个有界的 **read-only exporter**。它读取已完成的 SQLite/source
   snapshot，重建现有 producer envelope，并保留 source、selection、lineage 和
   producer score 的 provenance；它不会启动 Shinka、调用 evaluator、创建 export
   目录或发布候选。

这两条边界都不能被描述为已经验收了真实 Python project lifecycle。当前没有被审阅和
冻结的 CPython/source/toolchain/sealed runtime profile，也没有可接受的 OpenEvolve 或
Shinka project entrypoint、依赖闭包和 input/result mapping。provider-free 的入口描述符与
lifecycle report 组合 API 已把 profile、相对入口、请求/结果文件名和保留 lifecycle
诊断绑定起来，但它是 detached contract，不执行或检查项目。这是安全的契约进展，不是
runtime acceptance；把一个 Python fixture 接到 `native-producer` 仍会制造错误的生产能力声明。

## 已存在的能力

| 区域 | 当前实现 | 证据边界 |
| --- | --- | --- |
| OpenEvolve native lifecycle | `openevolve_native.py` 通过 `producer_lifecycle.run_native_trusted_lifecycle` 复用 native scheduler、broker、receipt、cleanup 和 prepared bundle；完成后使用 retained checkpoints replay，不重新启动。 | 仅显式 Python API；需要调用方提供已经冻结的 native executable、artifact、intent、attestation、groups 和 evaluator。没有 Python SDK/runtime acceptance。 |
| OpenEvolve 取消与 deadline | `SolveExecutionControl`、parent deadline、owner continuation guard 和 `cancelled` callback 贯穿 native attempt；进程清理不确定时保留 unknown/固定错误。 | provider-free/native fixture 已覆盖；不能代替真实项目在 accepted runtime 上的中断矩阵。 |
| Shinka snapshot/export | `shinka_handoff.py` 和 `python_producer_export.py` 以 descriptor-relative、bounded、SQLite signature-checked 方式读取完成的 run。 | 只读 provenance；没有 Shinka launcher、scheduler、process owner 或 live cancellation。 |
| 通用 cooperative lifecycle | `run_producer_lifecycle` 可执行一个显式 producer intent 并在 cleanup/envelope/receipt 全部稳定后准备 bundle。 | `request_coverage=cooperative_declaration_only`、`broker_coverage=not_integrated`；不是生产 external producer admission。 |
| Python producer composition | `PythonProducerRSIGateway`、逐 episode staging、native claim/receipt/replay 和 adapter export 已接线。 | `production_admission=False`；context 必须由调用方预先准备，不能从 producer id 推导 project。 |
| RSI CLI | `rsi run|resume --solver-execution fixture` 只执行 provider-free fixture；显式 `native-producer` 在读取 contract、创建 ledger 或构造 fixture gateway 前固定拒绝。 | 这条拒绝是有意的安全契约，不是暂时的 fixture fallback。 |

## 未完成的真实 P1 能力

### 1. Runtime/profile closure

在任何 project lifecycle 代码之前，必须冻结一个实际 profile：source archive/tree、patch
provenance、Python/native dependency closure、generated resources、loader/import policy、
toolchain/sysroot、sealed image、entrypoint、request/memory mapping、result contract 和
所有独立 digest。Feature189/193 的 DTO、静态检查器和 offline recipe 只验证形状；它们
不提供真实 CPython、SDK 或可执行 image。

### 2. OpenEvolve/Shinka project entrypoint

provider-free contract seam 已由 `project_entrypoint_descriptor.py` 部分实现：它将一个
profile digest 与相对入口、固定生命周期模式和 request/result 文件名绑定，组合函数再将
声明绑定到 retained lifecycle diagnostics。它仍不满足 runtime 要求。后续仍须在独立验收
的 runtime 上实现至少一个本地项目入口，并复用 native scheduler/claim/receipt mapper。入口
必须实际读取原始 RSI request/memory grants，经 host broker 计费，并产出绑定原
launch/run 的 bounded result。不能接受任意 module、factory、shell、host interpreter 或
ambient package installation。

### 3. Runtime-gated cancellation and cleanup

在 accepted runtime 上需要保留 startup、timeout/cancel、parent loss、missing terminal、
callback failure、cleanup uncertainty、source/runtime/journal drift 的原始观察。任何
无法证明的终态都必须保持 unknown，不能通过重启或删除目录“修复”。现有 process/native
fixture 测试覆盖了规则，但还没有真实项目的 raw evidence。

### 4. Production CLI composition

只有 profile、runtime、entrypoint 和独立 Linux acceptance 全部完成后，才可以把
`native-producer` 接入 `rsi run|resume`。CLI 必须消费原 request、memory、result、
evaluation 和 publication evidence，复用 controller budget/unknown/fingerprint gates，
并让终态 resume 只读恢复。若 profile 不存在，继续保持当前 pre-I/O refusal。

## 本轮验证

基线工作区只读审计确认：

- OpenEvolve native lifecycle 的 focused tests 已覆盖成功、replay、取消、deadline、
  owner loss、cleanup uncertainty 和 binding drift（`tests/test_openevolve_native.py`、
  `tests/test_producer_lifecycle.py`）。
- Shinka exporter 的 focused tests 已覆盖 SQLite/source drift、selection、lineage、
  cleanup 和 read-only 行为（`tests/test_shinka_handoff.py`、
  `tests/test_python_producer_export.py`）。
- RSI CLI native opt-in 在 contract/config/ledger/fixture I/O 之前拒绝，且不会 fallback
  到 fixture（`tests/test_rsi_producer_gateway.py::test_native_cli_opt_in_refuses_before_contract_config_ledger_or_fixture_io`）。

这些 fixture 结果不关闭真实 runtime/producer/CLI 验收。

## 推荐后续顺序

1. 先冻结一个真实 project runtime profile，并独立验收 source/toolchain/sealed image；
2. 在该 profile 上实现一个不含任意动态加载的 OpenEvolve 或 Shinka entrypoint；
3. 把该入口接到已有 native scheduler/receipt/cleanup/reconcile，并完成 Linux 中断矩阵；
4. 最后增加 production CLI 的显式 opt-in，保持默认 fixture 和 `production_admission=False`；
5. 在上述证据合格前，不实现 remote evaluator、外部 worker authentication、多机
   ownership 或 distributed scheduler。

