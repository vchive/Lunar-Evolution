# Current release backlog — 2026-10-15

本文按**已合入 main、当前批次待验收、真实运行时待验收、明确后置**四种状态记录工作。
本地通过、最终来源 CI、独立来源审计、合入和真实 campaign 验收分别记录，不能互相替代。

## 当前状态与本轮出口

当前已确认的 main 基线为 `0cb49abb146d91cb59b71de45d01e16217ebed8d`（PR99）。
单 child 的原 controller → owner/CAS → gateway → claim/running → scheduler →
admission/publication → receipt/verifier → 只读恢复已完成本地 fixture 验收并合入。
默认 staging-only、生产 CLI native 拒绝和 `production_admission=false` 保留。

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
已确认排队，最终 CI/独审和合入仍开放。这一批实现同 workspace 的连续 DRS
发布、独立 ready capsule 和历史只读恢复；三轮不同 child、练习记忆晋级、目标重试已有
本地验收。较早 head 的成功与失败按各自来源保留，不能代替当前最终来源。PR103 已将
该恢复批次与 parser、六分片 CI 及 BRS handoff/service ancestry 整合，并以 `main` 为
base；当前应以 PR103 的最终来源 CI、独立审计和合入作为单一出口。
规格见 [multi-episode-publication.md](../specs/191-python-worker-adapter/multi-episode-publication.md)
与 [ready-capsule.md](../specs/191-python-worker-adapter/ready-capsule.md)。

PR101 仍作为恢复批次的历史草稿保留；其 known rejection、BRS partial-wave
修复和纯 BRS child preflight 已由 PR103 统一候选承接。较早 PR101 CI 的取消或 pending
状态不构成最终验收，必须核对 PR103 最后一次实际推送的 head。

Known rejection v2 已接通 controller、owner、scheduler 和 gateway；
只允许 fresh、显式 opt-in DRS。原 owner 两案、T4 多候选案、T5 五个中断边界与原 C2
连续 reconcile 已通过；连续恢复只消费一次 unknown evidence 预算、保留一次原 solver
invocation。冻结来源 RPP/PRP/RRR 三案各 1 pass，原 XML/SQLite/source 独立审查通过；
后续修复/parser 联合候选在 [PR103](https://github.com/vchive/Lunar-Evolution/pull/103)，
PR103 统一候选仍待最终集成来源 CI、独立审计和合入。
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

## P0：当前 DRS 批次

| 剩余工作 | 已有实现 / 本地证据 | 结束条件 |
| --- | --- | --- |
| PR100/PR103 连续发布与历史恢复 | append lineage、原 owner/CAS、独立 held pins、fresh dispatch lease、ready capsule、历史只读 inspection 已实现；三轮 DRS 已有本地验收，最终集成候选集中在 PR103。 | PR103 最终 head 全部 CI jobs 完成，原始 log/ZIP/JUnit/inventory 与 checkout/source/tree/import 独立一致；合入 main。 |
| Known rejection 原始恢复验收 | 原 owner、T4/T5、连续 reconcile 与 RPP/PRP/RRR 全部通过；mixed 原 XML/SQLite/source 独立审查通过，证据边界详见 HANDOFF。 | 本地出口已关闭；最终集成来源仍须 CI/审计和合入，不能将冻结来源结果直接改称新 parser 候选验收。 |
| PR103 恢复批次最终集成发布 | 统一候选包含 known rejection、BRS partial-wave 修复、parser 及 BRS handoff/service ancestry；`9203ef1` 官方21 success/3 cancelled，整轮未获接受。正在拆分同文件的三个重用例，保留六个普通分片及全部 inventory。 | 修复后的最终实际推送 head 通过 focused/static checks、完整 CI、raw/source/tree 独立审计，再合入 main。 |
| 发布文档与证据状态 | GitHub README、台账和对应 SDD 按代码与验收区分状态。 | 用最终实际结果更新状态，链接可用；不把 partial log、不同 source 的局部成功或 skipped Linux gate 当作接受。 |

Known rejection 复用原评测证据结算失败结果；拒绝与进程故障分别处理，不生成官方成功。
C1/P/C2 不完整、missing、unknown、配置/来源漂移、取消或 deadline 均不产生新执行权。
已有 started claim 不能通过 readback/reconcile 自动重启。

## P1：下一轮接线与真实本地验收

| 工作 | 当前边界 | 结束条件 |
| --- | --- | --- |
| BRS partial-wave durable resume | 已在 PR101 集成树接入 completed-obligation 与 pending-dispatch 分离、锁外 replay callback 和 exact identity/head 复核；347 个本地 cases、789 文件 source map、Ruff/compileall/diff-check 已通过。仍不授予 completed child 新 token，也不启用 native multi-child。 | 随 PR101 完成最终 integrated source/CI/audit 和合入；产品行为保持 provider-free。 |
| Native 多 child BRS | provider-free BRS 和单 Python child ready/ack 已存在；PR102 提供 detached handoff/channel，PR104 私有 selected owner service 已通过 175 个 provider-free focused cases（104 existing + 13 ACK + 30 handoff + 28 service），含锁、预算、指纹、结果和 durable ACK 边界；公共 native BRS 仍未启用。 | 按 [Feature196](../specs/196-brs-owner-worker-handoff/spec.md) 接通 selected child staging/claim、原 owner/CAS、ready/ack、串行 publication 与完整中断验收；完成最终来源 CI 与独立审计。 |
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
