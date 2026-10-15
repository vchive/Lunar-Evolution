# Current release backlog — 2026-10-16

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
确定性 latency fixture 已合入，Ruff/compileall/diff-check通过。完整owner
transaction、controller/mailbox service、拒绝C1/P/C2、独立
result delivery/settlement、reconcile、连续ordinal与policy/memory仍开放。
冻结 [PR109](https://github.com/vchive/Lunar-Evolution/pull/109)的完整33-job CI、
actual checkout/source/import/raw独审和main合并是独立P0，后继不追加或取消其来源。
公开native BRS、online publication与production admission仍关闭。详见HANDOFF最新条目。

## 2026-10-16：私有成功检查点与证据转换

PB-02c preparation → mailbox detached evidence 和 PB-03d 原 BRS owner
staged/terminal checkpoint 已开发并通过独立源码审查。统一产品/测试冻结来源为
`01c3bd1`；Mac/Linux 各通过相同 322 个不同 focused cases、零失败/错误/跳过。
Mac 的179/143两组使用Python3.11/3.13，Linux各自为隔离Python3.12；具体环境、
原始证据独审与仍待完成的正式 CI 门槛见 Feature196
[`staged-terminal.md`](../specs/196-brs-owner-worker-handoff/staged-terminal.md)。

当前优先级：

- P0：PB-03h 候选的 Mac/Linux 72-case 完整回归、source/import/XML/nodeid/tree 独审，
  新 PR 的完整 CI 与 main 合并；冻结 PR109 不修改、不取消、不追加提交。
- P1：staged/precommit/terminal 高层接口、原 transaction owner dispatch、controller/
  mailbox service、rejection C1/P/C2、独立 return/settlement；再接 reconcile、serial
  successor 与 policy/memory。retained reader、prepared pin 已完成顶部所列后继验收；
  已具备的私有接口和检查点仍不等于完整在线执行链路已接通。
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

2026-10-16 最新检查点：main 仍为下面的 PR99 基线。P0 当前出口改为顶部说明的
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

当前已确认的 main 基线为 `0cb49abb146d91cb59b71de45d01e16217ebed8d`（PR99）。
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
| Native 多 child BRS | provider-free BRS 和单 Python child ready/ack 已存在；PR102 提供 detached handoff/channel，PR104 私有 selected owner service 已通过 175 个 provider-free focused cases（104 existing + 13 ACK + 30 handoff + 28 service），含锁、预算、指纹、结果和 durable ACK 边界；本分支已新增私有 owner 对本次 service 返回结果的 checkpoint CAS/完整读回，最终 callback hardening 整合来源的 360 cases、全仓静态及独立 raw/source/install/exit 审计已通过，已包含于顶部统一候选但尚未合入 main。此切片不包含 publication 或 sibling transition；公共 native BRS 仍未启用。 | 按 [Feature196](../specs/196-brs-owner-worker-handoff/spec.md) 接通 selected child staging/claim、原 owner/CAS、ready/ack、串行 publication 与完整中断验收；完成最终来源 CI 与独立审计。 |
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
