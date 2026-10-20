## 2026-10-21 当前执行清单（main 本地领先 origin，待推送）

本轮新增四项 provider-free 收尾：static-Python acceptance 强制 installation/build 最终
artifact pin 一致；build provenance 的五个 closure section 缺失或漂移时直接拒绝；reserved
serial worker 异常路径在 retained absolute deadline 内有界等待，未退出固定进入 unknown，
不继续 settlement；input/result DTO 拒绝全零和全 f 占位 digest。对应 focused tests、Ruff、
compileall 和 `git diff --check` 均通过。

外部只读 benchmark checkout 继续只做复制和本地 evaluator smoke。新增
`irregular_packing` 合法 20,100 行 grid submission 得到 `validity=1.0`、`overall=0.0590`，
重复摆放负向 case 得到 `validity=0`；原 checkout 保持 clean。详见
[`benchmark-case-smoke-20261021.md`](benchmark-case-smoke-20261021.md)。这些结果仍是
provider-free evaluator-path evidence，不是模型 campaign、远程评测或生产准入。剩余
`steel_coil_cutting`、`supply_chain_inventory` 与 `ore_reclaiming_scheduling` 的正向/负向结果见
[`benchmark-case-smoke-20261021-remaining.md`](benchmark-case-smoke-20261021-remaining.md)；
这些结果是 evaluator-path smoke，不代表模型 campaign 或优化质量。

P1 的真实 CPython/stdlib closure、source/toolchain/static ELF、sealed startup、owner/lifecycle、
authoritative input/result、OpenEvolve/Shinka project lifecycle 和 Linux 中断矩阵仍开放；P2 的
remote evaluator、外部 worker 认证、多机 ownership 和 distributed service 继续后置。保持
`production_admission=false`、`online_publication=false`。

## 2026-10-20 当前执行清单（main `8e4411f`，已推送）

本轮 provider-free 收尾已完成：producer process 的启动时钟/parent deadline 统一固定拒绝，
static-Python acceptance pins 对五个 DTO section 强制 exact key-set，runtime/tree binding
使用严格且有界的 validated projection cache（漂移、子类和未知结构仍走完整校验）。producer
process 17 项、binding/fresh-tree/parser 74 项、static acceptance CLI 4 项通过；四个自然
reserved serial inert case 也分别通过。5090gpu 隔离目录完成 focused 回归和 compileall，
但 frozen CPython 的受控检查还确认 `_get_supported_file_loaders()` 为空、`sys.path_hooks`
为空且 `python313.zip` 不存在，所以 `linecache`/`traceback`/`collections`/`keyword`
等 stdlib closure 仍被阻断。README 的本地 DRS run/inspect/usage/resume
已实跑成功。下面的 P1/P2 边界保持不变。

`8e4411f` 还固定了 pytest 的本地 `src` 解析路径，并让只读 mailbox inspection
同时核对 SQLite 主库、WAL 和 SHM 快照；多 episode fixture 使用短临时父目录触发
原有 32 KiB binding ceiling，不改变生产上限。

Feature191/195 另增加了只读 `rsi project-preflight --diagnostics` 能力矩阵。它只把
detached profile 标为 verified，并明确 accepted runtime、entrypoint、lifecycle、Linux
acceptance 与 controller admission 的阻断原因；不会初始化 ledger、启动 producer 或
改变 `production_admission=false`。

本轮还用用户提供的外部 benchmark checkout 做了只读 case smoke：复制
`train_delay_rescheduling` 与 `city_delivery_routing` 到 ignored validation 目录，分别
用原 evaluator 验证了一个合法提交和一个负向 baseline。源 checkout 未修改，case 结果只
证明 evaluator/输入复制链路可用，不替代真实模型 campaign、官方 evaluator 或生产验收。
其中 `train_delay` 进一步通过 Lunar `effect-kit`/`effect-trial` 的 deterministic harness
连续 3 次完成，三次 `validity=1.0`、`overall=0.6827`、`objective=109620`；官方 extractor
未运行，仍只作为本地 staging 证据。

此前已合入 PR153/154/155/160/161/165/166/169/170/173/176/177/178/179：启动失败诊断与
retained producer-process 生命周期 CLI、Python producer receipt 的 task/timeout 绑定、
OpenEvolve/Shinka 项目生命周期 profile preflight、retained Python terminal 的只读
binding/deadline 检查、static Python no-dynamic recipe gate、acceptance envelope provenance
绑定、retained producer acceptance 的只读组合 CLI、5090gpu frozen bootstrap 与 linecache
closure 观察、detached replay schema 收紧、known-terminal cleanup 门禁，以及 producer
adapter 的固定失败分类/sidecar 复核。5090gpu 上
新增的 source-owned `linecache` closure probe 记录于
[linecache-closure-probe-20261020.md](../specs/189-static-python-fixture/linecache-closure-probe-20261020.md)，
仍是诊断材料；它把下一缺口具体定位到 `traceback`、`collections` 和 `keyword`，不构成 sealed runtime 或生产准入。
它们保留
`production_admission=false` 与 `online_publication=false`，不启动真实 producer、
evaluator 或 campaign。

PR160 的 terminal 命令只校验已保留的 canonical terminal；`unknown` 固定返回
`reconcile_required`，不会初始化 ledger 或自动重启。PR161 的 recipe gate 只拒绝
shared/PIE/dynamic-loader flags、共享 link inputs、重复或 shell-like 值。PR165 将
静态 acceptance 的 detached pins 与 canonical wire 绑定，并明确 `detached-pins-only`；
PR166 的 `rsi producer-acceptance` 组合 project preflight、terminal 和可选 replay，始终
返回 `blocked/runtime_acceptance_required`。PR169 的 5090gpu 观察确认 command-body 路径
仍在 `linecache` 缺失处失败；PR173 仅把 source-owned `linecache.py` 冻结进受控 no-dynamic
fixed-main 诊断，并验证 loader-negative，不代表完整 stdlib closure；PR170 收紧 replay report 的闭合 schema。这些门禁都不把 DTO 或描述符检查提升为实际
ELF、sealed runtime、Linux lifecycle 或生产准入；PR176 进一步要求已知 terminal 的
cleanup_status 为 `cleaned` 或 `already_exited`，但仍只消费 retained evidence；PR155 仍校验 source/runtime/toolchain/
request/result 摘要，PR154 漂移时返回 `receipt_binding_drift`。

PR138（`af1cc62`）已将 reserved BRS serial owner/ledger/terminal/finalization 链路合入
`main`，PR139（`b51d50d`）同步了交接和发布边界。当前 P0 的本地 provider-free
serial 行为已完成；下面的旧表保留历史批次，不再把它们描述为当前未完成项。

| 优先级 | 当前剩余出口 | 状态 |
| --- | --- | --- |
| P1 | Feature189/193 真实 CPython、toolchain/static ELF、sealed runtime 和 Linux lifecycle | 原始静态 CPython 在 `encodings` 前失败；冻结 `encodings` 的实验镜像可空启动但缺少完整 stdlib closure；no-dynamic fixed-main inert probe 已有独立诊断记录。`_lunar_static_main`、完整 import/codec negative、owner/lifecycle 和 Linux acceptance 仍开放，见 [sealed startup probe](feature189-sealed-startup-probe.md) |
| P1 | Feature191/195 OpenEvolve/Shinka project lifecycle、生产 RSI CLI/Linux acceptance | PR155 只完成只读 profile preflight；真实 project entrypoint、取消/清理、结果归属、producer admission 和 CLI 验收仍开放 |
| P2 | remote evaluator、外部 worker 认证、多机 ownership、distributed scheduler/service API | 后置，不进入当前单机正确性批次 |

`production_admission` 与 `online_publication` 继续关闭；本轮不运行真实 solver、WebAgent、远程 evaluator 或公司评测平台。

## 2026-10-19 当前执行清单（历史批次）

当前开发按以下出口推进；组件测试通过、最终来源验收、完整CI与main合入分别记录。

| 优先级 | 连续交付结果 | 当前状态 |
| --- | --- | --- |
| P0 | 原rejected owner自然ready/ACK | PR136最终`c445a612`同库存1,079项在macOS/Linux各全过，独立source/import/raw复核通过，PR已ready；完整CI/main待完成。 |
| P0 | 单原始ordinal拒绝到root结算/owner退出与明确恢复 | `codex/brs-rejected-lifecycle`已接通自然拒绝/ACK/mailbox/failed result与原子root结算；修复live恢复重入flock。14项集成场景、组件兼容、独立复核及完整CI仍待最终同源结果。 |
| P0 | 原整wave reservation下的serial continuation | 工作树已接入 reserved projection/prefix、全域 ledger/reservation 观察、fresh child preparation exchange、native provider/completion、serial driver 和 finalization readers；组件焦点证据仍不等于集成验收。早先的 material path/pin gate 已通过严格 `rejections/<terminal-id>.json` 映射修复（pure validator 70 项及新增 5 项回归通过），但当前最小 `rejected -> rejected` 双 child 已推进到 `rsi_brs_reserved_serial_settled_transport_missing`，仍未完成 owner admission/mailbox handoff。自然 outcome 矩阵、fresh resume、最终来源验收和 CI 仍待完成。 |
| P1 | 实际sealed Python runtime、一个项目再第二个、生产CLI | source/installation/build/startup/input/handoff比较器和adapter/exporter已有；真实输入、实物构建/运行证据、项目lifecycle及CLI验收仍未完成。 |
| P2 | 多机ownership、外部认证、分布式调度和remote evaluator | 后置，不进入当前开发批次。 |

PR136接受材料已封存在主checkout ignored
`.lunar-evolution/validation/rejection-staged-ack-20261018-llo7u7ne/`。
当前行为开发的失败和固定源码副本记录在
`.lunar-evolution/validation/rejected-lifecycle-dev-20261018/`，不得混算为最终验收。
公开native BRS、`production_admission`、`online_publication`保持关闭。

# Current release backlog — 2026-10-18

## 当前后继：原 BRS owner 拒绝 C1

- P0：PR123–127完整CI及依赖顺序合入。PR127冻结`f0e39b9`的相同302项scoped
  双平台与独审接受，PR已ready；完整CI最近各33项排队，仍未合入main。
- P1本轮：仅原owner ordinal-zero拒绝C1，显式fresh schema、完整native material
  与create-only descriptor、原scope/CAS/readback、完整retained容量和future P预留。
  首次`986d9b1`scope因双候选fixture receipt复用及lazy reader alias恢复缺失失败；
  原始材料保留NOT_ACCEPTED，test-only后继重新冻结回归。
  见 [rejection-owner-c1.md](../specs/196-brs-owner-worker-handoff/rejection-owner-c1.md)。
- P1后续：同owner P/C2与拒绝lifecycle；root execution settlement/owner retirement；
  已预留整wave预算的serial接线；真实source/toolchain/sealed runtime、
  OpenEvolve/Shinka lifecycle与生产CLI/Linux中断验收。
- P2继续后置。public native BRS、production admission、online publication仍关闭。

当前普通consume不会结算root execution；detached successor会再次增加计数，不能
直接接到已预留整wave的controller。本轮开发状态不代替其后独立冻结验收。

## 当前后继：独立终态恢复证据

- P0：PR123–126 的完整 CI 和依赖顺序合入。PR126 冻结 `74a3f52` 已通过
  macOS/Linux 各相同561项 scoped 验证和独审；最新完整33项 CI仍全部排队。
- P1（本轮）：独立 callback/worker terminal 持久观察、callback 前 durable ACK、
  只读独立证据组合，以及显式 fresh-compose + 同事务 source pins consume。
  契约见 [terminal-recovery-evidence.md](../specs/196-brs-owner-worker-handoff/terminal-recovery-evidence.md)。
  代码和组件回归已完成；冻结来源的双平台验收及独审单独记录在对应PR和ignored
  validation原始材料。本提交不提前宣称完整CI或最终验收通过。
- P1（后续）：原生 all-rejected C1/P/C2、serial successor、真实 source/toolchain/
  sealed runtime、OpenEvolve/Shinka lifecycle和生产CLI/Linux中断验收。
- P2：外部认证、多机ownership、分布式服务和远程evaluator继续后置。

仅本地 inert/provider-free fixtures。原unknown capture不能补录升级；传输、callback、
worker退出、原producer cleanup和自然episode终态分别取证。公开native BRS、
production admission和online publication继续关闭。

下列各节为此前切片的历史记录。

## 当前后继：持久化恢复观察

- P0：PR123/124/125 的完整 CI 与依赖顺序合入。三个候选分别有各自冻结来源的
  双平台 scoped 验收；PR125 `1e7f6cf` 的相同213项用例、静态检查和独审通过，
  最近33项 Actions 仍排队。不得用 scoped 结果代替完整 CI。
- P1（本轮）：原 owner 的 mailbox 四阶段观察持久化、原 native producer 记录绑定、
  重建 ledger 的只读核验。契约见 [durable-recovery-evidence.md](../specs/196-brs-owner-worker-handoff/durable-recovery-evidence.md)。
  side namespace 不推进原 root 或消费 obligation；原进程材料缺失固定 unknown。
- P1（后续）：自动终态证据组合/consume、serial successor 在线组合，以及真实
  source/toolchain/sealed runtime、OpenEvolve/Shinka lifecycle、生产 CLI/Linux 中断验收。
  transport receipt、detached callback 或旧 producer cleanup 均不能代替 episode 终态。
- P2：外部 worker 认证、多机 ownership、分布式 scheduler/service 与远程 evaluator
  后置，不作为当前单机正确性的开发前置。

当前分支 `codex/brs-durable-recovery-evidence` 的实现已完成，最终冻结双平台验收仍待完成；仅本地
inert/provider-free fixture，公开 native BRS、production admission 与 online publication
继续关闭。下列各节保留各候选当时的记录。

## 当前后继：完整 mailbox result envelope 组合

PR124 最终 `56745c2` 已获 macOS/Linux 各288项相同 scoped fixture 回归和独审通过；
PR123/124 的完整33-job CI仍排队，尚未合入 main。当前 `codex/brs-exact-result-composition`
在该冻结来源上接通原 owner mailbox → 既有 exact result envelope → 原 worker one-shot
callback。契约见 [Feature196](../specs/196-brs-owner-worker-handoff/exact-mailbox-result-composition.md)。

本轮保留原native all-rejected refusal，不伪造legacy ready ACK/selected-return。callback只
处理detached观察，不写episode/result，不证明process cleanup，也不消费恢复义务。实现与
最终冻结验收正在进行；自动终态恢复仍需独立证据observer和durable capture，真实runtime/
OpenEvolve/Shinka lifecycle/生产CLI验收继续开放。P2继续后置。


以下为此前切片的历史记录，不覆盖上述当前状态。

## 此前切片：原 owner mailbox 的恢复义务登记

`codex/brs-owner-lifecycle` 基于 PR123 的 `96a7394`，开发原 owner 的一次性
`retain_reconcile_obligation`，并由私有 mailbox composition 在 publication 事务前调用。
只追加精确 obligation；同事务校验原 run/episode/claim pins，相邻读回与原 source/control
复验通过后才同步 owner/wave 游标。未知结果保留义务并 poison 原 owner，不重试或刷新 capture。

契约见 [Feature196](../specs/196-brs-owner-worker-handoff/owner-mailbox-reconcile-registration.md)。
本轮回归、独审与完整 CI 尚待最终来源验收。PR123 已有双平台各374项 scoped 本地通过，
其33-job完整 CI仍排队，尚未合入 main。

本切片只覆盖 mailbox publication 边界，producer preparation 已发生；它不自动消费
terminal obligation，不覆盖首次 producer launch，也不启用 public native BRS。自动终态恢复、
真实 source/toolchain/sealed runtime、OpenEvolve/Shinka lifecycle、生产 CLI/Linux 中断矩阵
继续为 P1；P2 继续后置。

## 当前候选：BRS recovery correctness

`codex/p1-recovery-final` 修复三项现有行为：未消费 obligation 阻止默认
resume/drive/finalization，`rsi inspect` 正确报告 reconcile，selected terminal consume
必须与实际 ledger/native claim/result 一致。注册验证原 handoff 的 owner thread/head/state，
拒绝无关后续 checkpoint 上的重放；多 obligation 保持各自 capture 并独立消费。
终态校验与删除通过同一 SQLite 事务完成；批量 API 仍是逐项提交，失败后先读取剩余记录。
契约与具体任务见 [Feature196](../specs/196-brs-owner-worker-handoff/tasks.md)。

- P0：完成该候选的统一 macOS/Linux focused 回归、静态检查、独立审查及所需 GitHub CI，
  全部通过后合入 main。排队或取消的旧 run 不作为完整通过证据。
- P1：显式 API 尚未成为自动 selected-owner recovery。真实 source/toolchain/build closure、
  sealed runtime、OpenEvolve/Shinka project lifecycle、生产 CLI 和 Linux 中断矩阵仍未验收；
  不以 fixture 或已有 wheel/C build 代替真实 Python runtime。
- P2：远程 evaluator、外部 worker 认证、多机 ownership 和分布式服务继续后置。

以下是历史批次记录，不覆盖本节的候选状态和剩余边界。

## 2026-10-17：controller explicit reconcile resume facade 与 runtime gap audit（本轮完成）

PR118（`a82f55a`）增加 `RSILearningController.resume_brs_reconcile`：它在单次 per-run owner lock 下先解析全部 DTO/wire evidence，预拒绝未知 episode，再按稳定 episode 顺序调用 `consume_brs_selected_reconcile`。只有完整 `already_terminal` evidence 会消费 obligation；unknown、manual review、recoverable、abandoned 和 drifted 保留 checkpoint。PR119（`545e9d8`）进一步将输入收窄为 plain dict，拒绝 mapping 子类在安全边界执行调用方代码。

PR120（`79ead61`）记录真实 lifecycle gap：OpenEvolve native 已有 provider-free trusted 单次路径，Shinka 仍是只读 SQLite/source exporter；真实 CPython/source/toolchain/sealed runtime profile、项目 entrypoint、取消/清理原始证据和 production CLI 尚未验收。当前不把 fixture 接到 `native-producer`，也不启动真实 campaign。

当前 P1 下一步是冻结一个真实 runtime profile 后再接一个项目入口并完成 Linux 中断矩阵；P2 继续后置。

## 2026-10-17：selected obligation registration 与 terminal consume（本轮完成）

PR116（合并提交 `0eacf72`）在 phase CAS 之上增加两个显式、owner-locked 的 provider-free API：`register_brs_selected_obligation` 在 selected handoff、native plan/prepared pin 和 episode record 已冻结后登记 durable obligation；`consume_brs_selected_reconcile` 在 resume-time 重新校验 immutable bindings，并且只在完整 terminal evidence 下通过最新 checkpoint head 做 CAS 消费。registration 保留 append 前 captured parent digest，返回 append 后 checkpoint head；精确重放幂等。

unknown、manual review、recoverable 和 drifted evidence 均保持 obligation 与 checkpoint 不变，不会刷新 head、重试或启动 worker。对应 controller focused 25 项、扩展 reconcile/handoff/result 86 项，以及 Ruff、compileall、diff-check 均通过。该切片仍不改变默认 `_drive_brs()`/`resume()`、public native BRS 或生产 admission。

下一步 P1 是在已批准的 selected owner lifecycle 中显式调用 registration/consume，并完成真实 CPython/source/toolchain/sealed runtime、OpenEvolve/Shinka lifecycle 和生产 CLI 验收。

## 2026-10-17：controller-owned BRS reconcile phase CAS（本轮完成）

在 selected reconcile facade 之上，本轮增加 `RSILedger.apply_brs_reconcile_decision`
及同义 `reconcile_brs_selected` controller helper。它要求调用方提供完整
`BRSReconcileDecision` 与 `BRSReconcileEvidence`，在原 obligation digest、evidence digest
和 controller lock 均匹配时，通过 checkpoint CAS 只推进相邻 phase：
`selected → worker_running/reconcile_required`、`reconcile_required → settled`。
`manual_review` 保持原 checkpoint 不变，`drifted` 明确拒绝；captured checkpoint identity
不会被刷新。对应 6 项 phase-CAS focused tests、obligation/facade 回归及 Ruff、compileall、
diff-check 已通过。

这是显式 opt-in persistence boundary，不代表默认 `_drive_brs()`、`resume()` 或 selected
handoff 已自动接入；完整 process/native/mailbox/result evidence 仍需由本地 adapter 先观察。
真实 CPython/source/toolchain/sealed runtime、OpenEvolve/Shinka lifecycle 和生产 CLI 验收仍
开放，远程 evaluator、外部 worker authentication、多机 ownership 与分布式 scheduler 继续后置。

## 2026-10-17：PR113 合入与 selected reconcile facade

PR113 已以合并提交 `22ec975` 合入 `main`。在 durable obligation 基础层之上，本轮增加
显式 opt-in 的 `reconcile_brs_selected` 纯 facade：它绑定 obligation digest 和全部
captured identity，检查 process/native/mailbox/result evidence，区分 running、unknown、
drifted 与完整 terminal evidence；仅返回只读 decision，不写 ledger、不推进默认
`_drive_brs()`/`resume()`，也不把 `unknown` 推断为成功。对应 10 项 facade 与 19 项
obligation/resume focused 回归通过，Ruff、compileall、diff-check 通过。

下一步 P1 是把已完成的 controller-owned phase CAS helper 接到 selected handoff 前后的
controller checkpoint，并由默认路径显式调用；真实
CPython/source/toolchain/sealed runtime、OpenEvolve/Shinka lifecycle 和生产 CLI 验收仍开放；
远程 evaluator、外部 worker authentication、多机 ownership 与分布式 scheduler 继续后置。

## 2026-10-17：BRS durable reconcile obligation 基础层（已合入 PR113）

PR113 当前合并提交为 `22ec975`，基于 `main` 的 `a8996a3`。本轮已完成
BRS durable reconcile obligation 的最小持久化基础层：controller checkpoint 可以在锁内
原子登记、读取、校验、幂等重放和按 obligation digest 删除 owner obligation。记录固定
run/episode/request/native-plan/checkpoint/episode-record 指纹，并校验 phase、mailbox、
transaction、worker profile 和终止状态；缺失、冲突、漂移或未知状态均拒绝继续。

该基础层是显式 opt-in 的 recovery fence，**不等于默认 controller online reconcile 已接通**；phase CAS helper 需要显式调用，且不改变默认 `_drive_brs()`/`resume()`。
当前 `_drive_brs()`、`resume()` 和默认调度路径不会自动消费 obligation、探测 worker/process/
mailbox/result evidence 或推进 phase；也不会把 `unknown` 推断为成功。后续 P1 仍需把 obligation 接到默认 selected handoff 前后的 controller checkpoint，并由默认路径显式消费
facade decision。对应 focused obligation 回归为 9/9，
facade 回归为 10/10；这些本地结果不替代真实 runtime/producer 验收。

## 本轮后继开发状态

原主控 retained native reader、显式 prepared-reference 登记和原 false preparation
契约修复已在`05cd548`整合：macOS/Linux各498个不同focused cases全通过，
完整raw/source/import独审接受。高层before留存在`855b08e`实现：
macOS/Linux各34例（31新+3兼容）全通过并获独审。两来源分别验收，不能累计，
也不称855已重新通过498。详情见Feature196 `publication-validation.md`。

staged/precommit/terminal高层接口候选`7a21ed8`已完成静态独审；PB-03h exact BRS
私有transaction dispatch已在当前候选实现（SDD：Feature196
`private-native-dispatch.md`）。当前候选的15/15 native-dispatch、37/37
owner-lineage、30/30 transaction-control和17/17 staging-compatibility均通过，
确定性 latency fixture 已合入，Ruff/compileall/diff-check通过。当前 P1 集成分支又接入
私有 owner/mailbox composition、exact result delivery/one-shot settlement、本机
process/workspace reconcile evidence、serial successor 的 fresh handoff/claim/dispatch、
rejection C1/P/C2 adapter、policy/memory shadow gate，以及 BRS durable obligation 持久化基础层；
完整 owner transaction、默认 controller-level online reconcile wiring 与真实 runtime 仍开放。
当前 [PR113](https://github.com/vchive/Lunar-Evolution/pull/113) 候选的完整 33-job CI、
actual checkout/source/import/raw/tree 独审和 main 合并是 P0 出口；不要把本地 focused
结果或旧 PR 的来源当成该候选的最终验收。
公开native BRS、online publication与production admission仍关闭。详见HANDOFF最新条目。

## 2026-10-19：启动诊断与本地 producer-process 生命周期 CLI

`7f5dc25`（原始实现提交 `5411e0a`）增加了
`lunar-static-python-runtime-startup-diagnostic-v1`：它对有独立 SHA-256 pin 的有限 stderr
做 digest-only 分类（包括 `missing_encodings` 和 `getpath_configuration`），不保留原始 stderr，
且明确将 `runtime_execution_performed` 与 `production_admission` 保持为 `false`。这只能记录
5090gpu 构建探针的启动失败诊断，不能证明 sealed Python runtime、owner/lifecycle 或真实
campaign 已通过。

[PR153](https://github.com/vchive/Lunar-Evolution/pull/153) 增加 `producer-process inspect` 和需要 `--confirm` 的
`producer-process cleanup`，复用 retained process journal 的 owner、PID-reuse 和
recovery-lock 门禁。该 CLI 只提供本地生命周期 plumbing；未启动 OpenEvolve/Shinka、远程
evaluator 或真实 campaign，也不改变 `production_admission=false`。使用说明见
[`docs/local-producer-process-cli.md`](local-producer-process-cli.md)。

## 2026-10-16：私有成功检查点与证据转换

PB-02c preparation → mailbox detached evidence 和 PB-03d 原 BRS owner
staged/terminal checkpoint 已开发并通过独立源码审查。统一产品/测试冻结来源为
`01c3bd1`；Mac/Linux 各通过相同 322 个不同 focused cases、零失败/错误/跳过。
Mac 的179/143两组使用Python3.11/3.13，Linux各自为隔离Python3.12；具体环境、
原始证据独审与仍待完成的正式 CI 门槛见 Feature196
[`staged-terminal.md`](../specs/196-brs-owner-worker-handoff/staged-terminal.md)。

当前优先级：

- P0：PR113 已完成合入；主线 CI 仍按 GitHub Actions 独立运行并保留原始结果。
- P1：当前分支已完成私有 owner/mailbox composition、exact result delivery/settlement、
  本机 process/workspace evidence、serial successor dispatch、rejection C1/P/C2 adapter、
  policy/memory shadow gate 和 durable obligation 持久化基础层的 provider-free 最小切片；
  已增加显式 selected reconcile facade 和 controller-owned phase CAS helper；仍需把 obligation
  接入默认 controller selected handoff 前后的 checkpoint，并完成 online wiring（含完整 process/native/mailbox/result evidence）以及真实 runtime/
  producer/CLI 验收。retained reader、prepared pin 已完成顶部所列后继验收；这些私有接口
  仍不等于公开 native BRS 或生产 admission 已开启。
- P1：真实来源/工具链、sealed runtime、OpenEvolve/Shinka project lifecycle 和
  生产 CLI/Linux acceptance 仍按原独立范围开放，本轮不运行真实目标来替代验收设计。
- P2：外部认证、多机 ownership、分布式调度/服务化继续后置。

两项私有切片均保持 `online_publication=false`、`production_admission=false`，
公开 native BRS 入口继续拒绝。统一候选已包含 PR103/105/106/107/108，下一份 PR
直接 base main，完整 33-job 与 raw/source 独审通过后再合入并关闭被包含旧 PR。
旧规格中的 staged/terminal 待办仅按其当时来源解释；
当前尚缺的是完整 owner 在线组合，不需重写已完成的检查点 primitive。

本文按**已合入 main、当前批次待验收、真实运行时待验收、明确后置**四种状态记录工作。
本地通过、最终来源 CI、独立来源审计、合入和真实 campaign 验收分别记录，不能互相替代。

## 当前状态与本轮出口

2026-10-17 最新检查点：main 已合入 PR112，当前为 `a8996a3c94f5b07873e39e28c3ebff3953d1fa6c`；PR113 候选 HEAD 为
`4c86fe0`。本轮已完成 BRS durable reconcile obligation 持久化基础层，但 controller online
reconcile 仍未接通；P0 是 PR113 的完整 CI、来源审计与合入，P1 是显式 online reconcile
以及真实 runtime/producer/CLI 验收。以下 2026-10-16 内容保留为当时来源记录：

2026-10-16 检查点：main 已合入 PR109，当前为 `319c8ab79805031a724d0964ebd497c16359753c`。P0 当前出口改为顶部说明的
base-main 统一后继；它包含 PR103/105/106/107/108 的真实 Git 祖先，并须验收自己
最终 head 的完整 33-job、actual merge/source/import/raw 证据后合入。
PR103 `935ab57` 的 [CI 38752535974](https://github.com/vchive/Lunar-Evolution/actions/runs/38752535974)
保留自己的来源和未完整接受状态；不再以逐个合并旧 PR 作为当前路径。
旧 `9203ef1` 的 24-job run 和 PR105–107 已取消 runs 同样保持历史标签，不能当作
统一后继的验收，亦不需要重写或重跑已完成的切片来刷新旧 run。

P1 后继已实现私有 producer prepublication stop、共用 checkpoint kernel，以及原 BRS
owner 的首 ordinal before/prepared checkpoint；`e30f5f8` 的 installed Linux 回归为
450 个不同 case 全部通过，原始证据与 Git 来源已独立核对。它们没有接通完整 owner
publication transaction。两处测试夹具修正 `2576d2b` 的独立 121-case 回归通过；实际成功
路径的 episode 终态 CAS 竞态由 `27929e7`/`1603330` 独立修复，最终 16 项测试通过。
持久化 pre-wave policy 的 `399958c` 来源 402 项回归通过。上述改动已整合到草稿
[PR108](https://github.com/vchive/Lunar-Evolution/pull/108)，冻结 `9d66b23` 的 265 项
Linux 针对性回归全部通过、零 failure/error/skip；原始证据、own-editable 来源和全部
2,042 Git blobs 独立审查通过。全量 16,989 仅作 collection，额外执行 0 case，不能将
各来源计数相加。这些后继还没有合入 main，公共
native BRS 仍关闭，`production_admission=false`。

并行 PB-02c 已实现 producer preparation → 原 mailbox 的非授权证据转换；冻结
`1ca4325` 的 macOS/Linux 各自 179 cases 通过，独立代码与 Linux raw/source 审查通过。
它不替代 owner 的 fresh durable recovery，也没有接通在线发布事务。PB-03d 的
staged/terminal checkpoint primitive 已在统一 `01c3bd1` 实现并通过独立源码审查；
完整 online composition、最终 focused/raw 与正式 CI 分别记录，不把 primitive 当作发布执行。

历史记录中的 main 基线为 `0cb49abb146d91cb59b71de45d01e16217ebed8d`（PR99）；当前 main 已更新为 PR109 merge `319c8ab`。
单 child 的原 controller → owner/CAS → gateway → claim/running → scheduler →
admission/publication → receipt/verifier → 只读恢复已完成本地 fixture 验收并合入。
默认 staging-only、生产 CLI native 拒绝和 `production_admission=false` 保留。

### 历史过程（按原来源保留）

PR103 `9203ef1` 的 [CI 38688233723](https://github.com/vchive/Lunar-Evolution/actions/runs/38688233723)
最终为 **21 success、3 current-5 cancelled，NOT_ACCEPTED**。三份取消产物缺少最终
JUnit/summary，不能合入；24 份原始产物及日志已核对，成功部分不替代缺失的覆盖。
新修复把同文件内三个重 mixed 用例各放到独立 job，保留六个普通文件分片和完整用例
清单校验；新来源仍须完成 focused/static、三版完整 CI 和独立审计。旧官方结果及
服务器第5片原运行保持不变，partial progress 不算通过。详细来源见 HANDOFF 最新条目。

PR100 原 head `c73650a` 的
[CI 38582309622](https://github.com/vchive/Lunar-Evolution/actions/runs/38582309622)
已失败：actor evidence 替换竞态 fixture 提前在源码读取中触发；原失败与取消证据保留。
修复 `9db1ffda8bc6ebfd50c50d07e20fbc703b561514` 只将测试绑定原 evidence inode，
76 个相关本地 cases 通过。原 3.11/3.12 current-0 另因官方六小时 job 上限取消，
不能只修 fixture 后等待同一超时拓扑；正在按原确定性算法拆为六分片，保留全量 inventory。
fixture 修复已推送原分支，
[新 CI 38651297182](https://github.com/vchive/Lunar-Evolution/actions/runs/38651297182)
当时已确认排队，原始状态按来源保留；该历史 run 不再是当前合入出口。
这一批实现同 workspace 的连续 DRS
发布、独立 ready capsule 和历史只读恢复；三轮不同 child、练习记忆晋级、目标重试已有
本地验收。较早 head 的成功与失败按各自来源保留，不能代替当前最终来源。PR103 已将
该恢复批次与 parser、六分片 CI 及 BRS handoff/service ancestry 整合，并以 `main` 为
base；当时由 PR103 承接，现由顶部所列 base-main 统一后继承接最终验收与合入。
规格见 [multi-episode-publication.md](../specs/191-python-worker-adapter/multi-episode-publication.md)
与 [ready-capsule.md](../specs/191-python-worker-adapter/ready-capsule.md)。

PR101 仍作为恢复批次的历史草稿保留；其 known rejection、BRS partial-wave
修复和纯 BRS child preflight 已由 PR103 统一候选承接。较早 PR101 CI 的取消或 pending
状态不构成最终验收；现核对顶部统一后继实际最终 head，而非重新等待旧 PR101/103。

Known rejection v2 已接通 controller、owner、scheduler 和 gateway；
只允许 fresh、显式 opt-in DRS。原 owner 两案、T4 多候选案、T5 五个中断边界与原 C2
连续 reconcile 已通过；连续恢复只消费一次 unknown evidence 预算、保留一次原 solver
invocation。冻结来源 RPP/PRP/RRR 三案各 1 pass，原 XML/SQLite/source 独立审查通过；
后续修复/parser 联合候选在 [PR103](https://github.com/vchive/Lunar-Evolution/pull/103)，
该批已包含于顶部统一后继，其实际最终集成来源仍待完整 CI、独立审计和合入。
代码与规格见 [known-rejection-v2.md](../specs/191-python-worker-adapter/known-rejection-v2.md)、
[tasks](../specs/191-python-worker-adapter/known-rejection-v2-tasks.md) 和
[validation](../specs/191-python-worker-adapter/known-rejection-v2-validation.md)。
原始 XML、source maps、失败和中断记录保留在各自 ignored reports；当前验收状态以
[HANDOFF.md](../HANDOFF.md) 和最终验证记录为准。

Linux 开发服务器首轮 `f9048df` 六分片已失败：16,484 cases 中 15,976 pass、
234 failures、188 errors、86 skips，原始产物保留。严格 GCC、系统 Python 探测、
lineage/import-trap fixture、短 TMPDIR 和完整历史对象的修复已整合；局部通过不关闭
P0。新整合来源仍需 focused gate、完整六分片、三版正式 CI 和独立审计。
各切片范围与限制见 HANDOFF 和 Feature157/160/191 validation。

历史 PR103 来源 `9203ef1f0c3b5dd69e09c8cdb79b92c5af5e1e76` 的
[官方 CI 38688233723](https://github.com/vchive/Lunar-Evolution/actions/runs/38688233723)
最终为 21 success / 3 cancelled，未获完整接受。该提交 installed Linux focused 为 360 cases：354 pass、
6 个原架构 skips、零 failure/error；XML/install/source 与全仓静态检查已独立核对。
新的服务器六分片完整收集 16,503 cases，精确互斥覆盖，仍在运行。
较早 `bd902c9` 的 shard2 原始 XML 已确认唯一失败为 deadline 并发 fixture 读到
尚未完成的 writer 记录并按 `path_invalid` 拒绝；最终 fixture 对完整记录锁争用和
零字节/八字节记录拒绝分别同步验证，生产预算与拒绝逻辑未改。旧整轮仍保留原结果，
不能用修复后的 focused pass 改写。main 仍为上述 PR99 基线。

## P0：当前 DRS 批次

| 剩余工作 | 已有实现 / 本地证据 | 结束条件 |
| --- | --- | --- |
| PR100/PR103 连续发布与历史恢复 | append lineage、原 owner/CAS、独立 held pins、fresh dispatch lease、ready capsule、历史只读 inspection 已实现；三轮 DRS 已有本地验收，经 PR103 纳入顶部 base-main 统一后继。 | 统一后继最终 head 全部 33 CI jobs 完成，原始 log/ZIP/JUnit/inventory 与 checkout/source/tree/import 独立一致；合入 main。 |
| Known rejection 原始恢复验收 | 原 owner、T4/T5、连续 reconcile 与 RPP/PRP/RRR 全部通过；mixed 原 XML/SQLite/source 独立审查通过，证据边界详见 HANDOFF。 | 本地出口已关闭；最终集成来源仍须 CI/审计和合入，不能将冻结来源结果直接改称新 parser 候选验收。 |
| 恢复批次最终集成发布 | `935ab57` 的 heavy partition 已包含于统一后继，保留六个普通分片和三个独立重用例；其 279-case focused 是原来源验收，旧取消结果不改写。 | 顶部统一后继实际最终 head 通过完整 33-job 和 raw/source/tree 独审，再合入 main；不逐层 retarget 或合并旧 PR。 |
| 发布文档与证据状态 | GitHub README、台账和对应 SDD 按代码与验收区分状态。 | 用最终实际结果更新状态，链接可用；不把 partial log、不同 source 的局部成功或 skipped Linux gate 当作接受。 |

Known rejection 复用原评测证据结算失败结果；拒绝与进程故障分别处理，不生成官方成功。
C1/P/C2 不完整、missing、unknown、配置/来源漂移、取消或 deadline 均不产生新执行权。
已有 started claim 不能通过 readback/reconcile 自动重启。

## P1：下一轮接线与真实本地验收

私有 selected checkpoint settlement 已创建 stacked draft
[PR105](https://github.com/vchive/Lunar-Evolution/pull/105)：base 为 PR103 分支，
head `868bccccc9ede2cd035d28b16cfb316fef049c0a`，仅 9 个后继文件。
该 head 已是顶部统一后继的真实祖先。它的旧 CI 不代替统一候选或 main 验收；
不再逐层 retarget，统一候选完整接受并合入后才处置仍开放的旧 PR。

其后继 worker publication refusal 关闭了实际已发现的边界缺口：legacy worker helper、
generic/DRS facade 与 scheduler live BRS path 不能在 worker 线程执行发布。pin-only
ready/ACK 仍可用。该拒绝不是 owner publication 的成功路径：下一步必须在 worker
已有 receipt/output/handoff、episode/claim 仍自然为 running/started 时，将完整
transaction 和 rejection C1/P/C2 continuation 交给原 owner；不能等 completed return
后伪造 DRS scope。实现顺序与恢复边界见
[owner-publication-bridge.md](../specs/196-brs-owner-worker-handoff/owner-publication-bridge.md)。

| 工作 | 当前边界 | 结束条件 |
| --- | --- | --- |
| BRS partial-wave durable resume | 已在 PR101 集成树接入 completed-obligation 与 pending-dispatch 分离、锁外 replay callback 和 exact identity/head 复核；347 个本地 cases、789 文件 source map、Ruff/compileall/diff-check 已通过。仍不授予 completed child 新 token，也不启用 native multi-child。 | 随顶部统一后继完成最终 integrated source/CI/audit 和合入；产品行为保持 provider-free。 |
| Native 多 child BRS | provider-free BRS、ready/ack、owner CAS、私有 owner/mailbox composition、exact result delivery/settlement、serial successor claim/dispatch 与本机 process/workspace evidence 已在当前集成分支接线；focused slices 及静态检查通过，尚未合入 main。此切片仍保持 public native BRS 与 production admission 关闭。 | 按 [Feature196](../specs/196-brs-owner-worker-handoff/spec.md) 接通 rejection C1/P/C2、完整 durable recovery、policy/memory 与中断验收；完成最终来源 CI、独立审计并合入 main。 |
| 真实 Python runtime | bounded source/build/runtime contracts 和原 executable owner 已存在；真实 source/toolchain/static image/sealed startup 未验收。 | 完成下表 G0–G3/F01–F05 的真实 bytes、构建 closure、startup/input/lifecycle 和 dedicated Linux no-skip evidence。 |
| 本地 OpenEvolve/Shinka 与生产用 RSI CLI | adapter、bounded result exporter、native scheduler/claim/receipt mapper 和单 episode 组合已存在。当前 `rsi run` / `rsi resume` solver 选项仍是 `provider_free_fixture`。 | 至少一个实际 project profile/lifecycle 在 accepted runtime 下验收，opt-in CLI 消费原 request/memory/result/publication 证据，支持取消和只读恢复；不会落入 fixture gateway。 |

以上真实依赖需要独立的 source/toolchain/runtime 输入和执行授权。本轮仅使用本地 inert
fixtures；未执行 CPython/toolchain target、真实 solver/model/campaign、WebAgent、远程
evaluator 或公司评测平台。P0 本地闭环完成不自动关闭 P1 的真实运行时验收。

### 真实 source/toolchain/runtime 的验收细项

| 功能 / 对应任务 | 还缺的实际证据 | 结束条件 |
| --- | --- | --- |
| Feature189 G0/G1、Feature193 F02c：来源与工具链 | bounded SDD/profile freeze；CPython 3.13.12 acquisition/signature；确切 Zig/musl compiler/sysroot/libc、binutils/static-library pins；配置与 patch provenance。 | 独立核实真实 archive/tree/toolchain bytes 和来源，冻结可执行 recipe；保留第一份失败/取消证据，不以 caller metadata 或 synthetic receipt 完成 G1。 |
| Feature189 G2、Feature193 F01/F02c：配置与静态构建 closure | 实际 C/API/PyConfig review、finite startup/import/codec inventory、九个 generated headers、freezer/objects/archives/link map、static ELF。 | 用 pinned tools 构建并独立审计所有输入/产物；实际 image 无 PT_INTERP/DT_NEEDED，完整 closure 与 image SHA/size 相符，且不超过原 128 MiB ceiling。mock build report 和 detached DTO 不完成此项。 |
| Feature189 G3、Feature193 F03：sealed startup/owner | 实际 CPython identity/flags、无 host stdlib 的 startup、negative loader/codec/import、原 executable owner、FD census 和 native lifecycle。 | 原始 sealed target 在专用 Linux no-skip gate 上通过 baseline/negative/owner 检查；提供真实 image/source/runtime 和独立 raw/source/tree 审计。Feature190 已有 owner 实现无需重写。 |
| Feature193 F04：authoritative input/result | 原 marker → manifest/request/memory authority、既有两项 grants 的实际消费和 bounded producer result。 | 同一次 launch 的原始授权输入与结果匹配；fixed-computation report/caller-byte comparator 不被当作 solver result。 |
| Feature191 P0/P1、Feature193 F05：运行时中断与 publication | startup、timeout/cancel、parent-loss、restart refusal、missing terminal、callback error、cleanup uncertainty、source/runtime/journal drift 的真实观察。 | 接入原 Feature190 owner/lifecycle、terminal/broker/material/budget evidence；在所有中断路径保留 unknown，禁止无证据重试/成功；通过 runtime-gated evaluation/publication/recovery 的 dedicated Linux matrix 与独立审计。 |
| Feature191 P1、Feature193 F06、Feature195：真实本地 producer 与 RSI CLI | accepted runtime 下的 OpenEvolve/Shinka lifecycle/export、生产用 opt-in CLI 路径和实际 project/Linux acceptance。 | producer-backed 路径使用已有 native scheduler/claim/receipt mapper，不落到 fixture gateway；原 request/memory/result/evaluation/publication 归属及取消恢复通过独立验收。真实 campaign 另保留其原始 receipts 与运行授权。 |

本轮未执行这些真实依赖项，未运行 CPython/toolchain、solver/model/evaluator 或 campaign。
真实项目 source/dependencies、受控入口、broker/result export 与 acceptance 的设计边界见
[Feature191 project-runtime-profile.md](../specs/191-python-worker-adapter/project-runtime-profile.md)；它是尚未验收的设计，不能由当前 candidate
startup/codec 冻结模块列表推导实际 SDK 可用性。

## 已合入的基础能力

| 能力 | 集成与证据边界 |
| --- | --- |
| RSI 恢复与治理 | durable controller resume、unknown reconcile gate、fingerprint drift、统一预算、CLI usage、retained producer replay、admission/checkpoint references、DRS first-pin、BRS ready/ack 已存在。复用 `rsi replay` 与 `RetainedProducerReplayGateway`。 |
| Prepared 接线与 exporter | PR87 已集成 immutable post-execution supplier → 原 handoff pin → transaction prepared observer，以及 bounded OpenEvolve/Shinka result exporter。见 [late-prepared-scheduler-join.md](../specs/191-python-worker-adapter/late-prepared-scheduler-join.md) 与 [local-python-producer-export.md](../specs/191-python-worker-adapter/local-python-producer-export.md)。 |
| 构建与来源契约 | Feature189/193 的 source/staging/provenance 比较器、marker、detached contracts、mock driver 和独立 `run_pinned_build` 已开发。后者消费另行审阅的 recipe 与输入/tool pins，没有内置或自动推导真实 CPython recipe。它们不完成真实 G1/G2 验收。 |
| 单 episode 组合与逐 episode staging | `PythonProducerRSISolverGateway`、create-only preparing → ready/unknown、原 request/memory/file pins 与只读恢复已存在；一个 staged context 仅绑定一个 request/memory/launch。见 [per-episode-producer-launch.md](../specs/191-python-worker-adapter/per-episode-producer-launch.md)。 |
| Child claim 与 fresh preclaim | PR98 已接原 checkpoint CAS 与 claim insert 同事务、原 execution control/deadline/cancellation 及 provider read-only preclaim；claim API 单独调用只登记 claim。见 [controller-child-claim.md](../specs/191-python-worker-adapter/controller-child-claim.md)、[preclaim-execution-control.md](../specs/191-python-worker-adapter/preclaim-execution-control.md)、[fresh-native-preclaim.md](../specs/191-python-worker-adapter/fresh-native-preclaim.md)。 |
| 单 child 闭环 | PR99 已验收并合入。原 controller root/proof、exact ledger/constructor pins、所有历史 execution policy 保留。见 [child-execution-flow.md](../specs/191-python-worker-adapter/child-execution-flow.md)。 |

## P2：明确后置

| 功能 | 进入与结束条件 |
| --- | --- |
| 远程 evaluator、外部 worker 来源认证 | 先单独确认需求与受支持的身份/结果协议，再以真实外部 receipts 验收；不属于本轮发布出口。 |
| 多机 ownership、分布式 scheduler、service API、远程 Shinka/Slurm | 单独冻结跨主机 authority、租约、故障恢复和部署范围，再验收跨主机请求/结果；当前系统仍以本机 controller 与本地 ledger 为主。 |
| 模型训练/SFT/RL、模型适配与效果 campaign | 独立 Model Adaptation/研究轨道；在运行时和本地 producer 验收后按固定任务、预算、原始结果执行。 |

WebAgent 仅保留此前分数作为普通演化参考，不重新运行或另建对比 campaign。
多机与服务化、模型训练均不作为当前单机 RSI 正确性的前置条件。

## 历史集成与来源记录

本节是历史证据，不重新定义上面的当前待办。原失败、取消和旧来源结果仍保留；
同一功能后续集成通过不会把较早来源改写成成功。

- PR99 已合入 `main 0cb49abb146d91cb59b71de45d01e16217ebed8d`。最终 head `80d3f3af`
  的 [CI 38517739592](https://github.com/vchive/Lunar-Evolution/actions/runs/38517739592)
  通过 15/15 jobs；15 份原始 artifacts 的 source/tree/parents/import provenance、
  XML/inventory 已独立审计。每版 current 三分区覆盖 15,664 distinct cases，零失败/错误；
  92 skips 有跨平台/ABI 原因。合入 tree 与实际 tested merge tree 相同。
- PR98 已合入 `4767e539`。最终 head `8e56b42f` 的
  [CI 38511478558](https://github.com/vchive/Lunar-Evolution/actions/runs/38511478558)
  与独立审计已通过；PR99 在它之上补齐单 child 闭环。
- PR87 已合入 `17ebde4`，最终来源 CI 与独立 raw/source/tree 审计通过；该集成后的
  main CI 也通过 15/15。后续 PR100 与 known rejection 必须接受各自最终来源。
- PR100 的早期三轮验收曾暴露 checkpoint 容量、staged marker 历史读取、测试锁及
  Linux guardian fixture 等问题；ready capsule 保留原 112 KiB 上限、create-only、
  原 ready CAS 与 64 MiB 共同预算。早期 179 核心回归与后续修复 XML 仅证明各自来源。
  原失败及修复过程见 [HANDOFF.md](../HANDOFF.md) 和对应 [Feature191 validation](../specs/191-python-worker-adapter/validation.md)。

### 更早 CI 台账：CI 与 raw/source/tree audit 分开

下表通过 `gh pr view` 与 `gh run view` 核对：run 的完整 `headSha` 等于该 PR 的最终
`headRefOid`，且所有所列 jobs 都 completed/success。短 SHA 仅便于阅读。
15 checks 是 Python 3.11/3.12/3.13 × focused/current-0/current-1/current-2/history。
PR49–51 的原 workflow 是三版本 3 jobs，不能写成 15 checks。

| 对应实现 / task CI 部分 | 最终来源 | 成功 run / checks |
| --- | --- | --- |
| PR49 runtime observation policy | `87e579a` | [38198657810](https://github.com/vchive/Lunar-Evolution/actions/runs/38198657810), 3/3 |
| PR50 Feature193 T11b marker source | `861e068` | [38198840702](https://github.com/vchive/Lunar-Evolution/actions/runs/38198840702), 3/3 |
| PR51 Feature193 F01f preparation | `517593c` | [38198846690](https://github.com/vchive/Lunar-Evolution/actions/runs/38198846690), 3/3 |
| PR52 Feature193 F04e input-report source | `ac763f0` | [38199122019](https://github.com/vchive/Lunar-Evolution/actions/runs/38199122019), 15/15 |
| PR53 Feature193 F01k installation contract | `4f4d880` | [38199235337](https://github.com/vchive/Lunar-Evolution/actions/runs/38199235337), 15/15 |
| PR54 Feature193 F02 build-closure contract | `e08b044` | [38199240159](https://github.com/vchive/Lunar-Evolution/actions/runs/38199240159), 15/15 |
| PR55 Feature193 F03 startup contract | `37aa8ab` | [38199245419](https://github.com/vchive/Lunar-Evolution/actions/runs/38199245419), 15/15 |
| PR56 Feature193 F04c cross-pin contract | `7665164` | [38199255630](https://github.com/vchive/Lunar-Evolution/actions/runs/38199255630), 15/15 |
| PR57 Feature193 F05c handoff contract | `7ca3816` | [38199260479](https://github.com/vchive/Lunar-Evolution/actions/runs/38199260479), 15/15 |
| PR59 Feature193 F02d/F05d corrections | `a6a8eb2` | [38200497242](https://github.com/vchive/Lunar-Evolution/actions/runs/38200497242), 15/15 |
| PR64 integrated replay/resume CLI | `367fd1c` | [38216044832](https://github.com/vchive/Lunar-Evolution/actions/runs/38216044832), 15/15 |
| PR66 Feature193 controlled mock build driver | `3551b9e` | [38270514933](https://github.com/vchive/Lunar-Evolution/actions/runs/38270514933), 15/15 |
| PR76 boundary timing correction | `fef86f3` | [38310155020](https://github.com/vchive/Lunar-Evolution/actions/runs/38310155020), 15/15 |
| PR78 Shinka run-id normalization | `2764d5b` | [38314331155](https://github.com/vchive/Lunar-Evolution/actions/runs/38314331155), 15/15 |
| PR80 explicit prepared-boundary bridge | `94a2ec2` | [38327293323](https://github.com/vchive/Lunar-Evolution/actions/runs/38327293323), 15/15 |
| PR81 executable owner FD-boundary fixture | `cad9837` | [38320188791](https://github.com/vchive/Lunar-Evolution/actions/runs/38320188791), 15/15 |
| PR82 bound-result preflight / inherited integration | `6d4fdc2` | [38329866982](https://github.com/vchive/Lunar-Evolution/actions/runs/38329866982), 15/15 |

这次核对只确认 GitHub 最终来源 CI，不重新下载或独立审核 raw artifacts/tree inventory。
Feature193 和 observation policy 原任务中未完成的独立 raw/source/tree audit 继续保留；
已记录验收的 Feature189/190 基础 slice 不因本次只读核对重新标成未开发。

PR72/73/74 已合入，但其原来源 runs
[38289628526](https://github.com/vchive/Lunar-Evolution/actions/runs/38289628526)、
[38293790980](https://github.com/vchive/Lunar-Evolution/actions/runs/38293790980)、
[38295424243](https://github.com/vchive/Lunar-Evolution/actions/runs/38295424243)
分别只有 11/15、0/15、7/15 success，其余失败/取消。保留这些原结果，不关闭其原来源
CI 义务。后续 PR82 的完整集成来源通过 15/15，证明的是该集成 revision。
Feature195 的 replay context 修改已随 PR73 合入；PR64 的旧成功不能代替它的最终验收。

PR87 最终来源 `328b898` 的完整 CI 与独立 raw/source/tree 审计已通过，合入为
`17ebde4`；新执行机制/单 episode 组合须验收其自身最终来源。较早 PR 的原来源
义务继续按各自保留证据判断。被后续 push 取消的
旧 main runs（包括旧任务中引用的 `38331781593`）不算通过；不为刷新 run ID 新建
文档 PR 或 CI matrix。PR87 的最终来源由该 PR 的实际最后一次产品/测试集成决定。

## 使用规则

验收顺序为最终产品/测试集成 → 最终来源完整 CI → 原始日志/XML/source/import/tree
inventory 核对 → 独立审计 → 合入状态记录。功能存在、local pass、CI pass、merge 和
真实 runtime acceptance 是不同状态。仅推进当前 P0/P1 表中的具体剩余项；历史条目
保留其原来源，不为刷新 run ID 单独创建文档 PR 或 CI matrix。
