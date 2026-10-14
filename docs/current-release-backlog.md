# Current release backlog — 2026-10-14

## Opt-in single-child execution — 2026-10-14

PR99 已合入 `main 0cb49abb146d91cb59b71de45d01e16217ebed8d`，接通显式
`producer_child_execution=True`：相邻 ready 的原 owner/CAS permit → child gateway →
原 claim → running → native scheduler → prepared admission/publication → receipt mapper →
result/verifier。原 controller root 和 proof 不替换；原 run 与全部历史版本固定 execution
policy。默认 staging-only 和 CLI native 拒绝行为不变，`production_admission=false`。
单 child 完整 inert fixture 与中断恢复回归已通过；最终 head `80d3f3af` 的 CI
`38517739592` 通过 15/15 jobs，原始 artifacts/source/tree 已独立审计。合入 tree
与实际 tested merge tree 相同。README 已发布到 GitHub 首页。
规格见 [`child-execution-flow.md`](../specs/191-python-worker-adapter/child-execution-flow.md)。

当前 `codex/multi-episode-publication` 正按现有 SDD 处理两个发布依赖：

- 原 Feature153 的 `_ensure_initial_population_window` 只允许第一批 producer admission；
  第二个 episode 对同一 archive 发布会被拒绝。
- 原 publication `_terminal` 要求当前 archive/state 等于该批的完整发布后摘要；合法的
  后续发布也会使早先 child 的恢复失败。

契约已选择同 workspace 的显式 append lineage，规格见
[`multi-episode-publication.md`](../specs/191-python-worker-adapter/multi-episode-publication.md)。
原 owner/CAS、fresh dispatch lease、每阶段独立 held pins、历史只读 inspection 和
原 deadline/cancellation 门禁已实现，正在统一来源下验收 target failure → practice
success → 新 approved memory → target retry。当前尚未验收或合入；`all_rejected`
opt-in 仍明确拒绝，不关闭整项、BRS、真实 runtime 或生产 CLI。不得移除初始门禁、忽略
archive 摘要或重复使用 root sidecar。

三轮实际验收已暴露 checkpoint 容量阻塞，正在按
[`ready-capsule.md`](../specs/191-python-worker-adapter/ready-capsule.md) 验证 MEP-only
独立 ready 证据文件。实现与独立代码审查已完成，保留原 112 KiB 上限、create-only
写入、原 ready CAS 和共同 64 MiB 预算；179 项核心回归已通过。三轮闭环与默认/历史
兼容尚在同一冻结来源下验收，未据开发测试关闭功能或合入。完整拒绝批次的关联、mapper
和历史恢复须下一片单独实现，不能把正常 validity=0 当进程失败。

## Current snapshot — 2026-10-14

已核实的集成基线是 `main 0cb49abb146d91cb59b71de45d01e16217ebed8d`。
PR99 的 [CI run 38517739592](https://github.com/vchive/Lunar-Evolution/actions/runs/38517739592)
已通过 15/15 jobs，15 份原始 artifacts 的 source/tree/parent/import provenance 和
XML/inventory 已独立核对。每版 current 三个分区覆盖 15,664 个不同 case、零失败和
错误；92 个 skips 有明确跨平台/ABI 原因，不能称全量 zero skips。之前因后续 push
取消的 main runs 保留原结果；其 pending 文字不再代表该集成基线的状态。

PR98 已合入 `4767e539`，集成三条 P0 接线：显式 controller child claim、
scheduler 原 execution control/cancellation/deadline 门禁、fresh gateway preclaim 调用。
claim 复用原表和 DTO，原 checkpoint CAS 与 insert 位于同一 SQLite 事务；中断或后续漂移
保留 started。首次 native gateway 执行在 claim 前调用 provider 的显式 read-only gate，
started/terminal 仍走原 recovery/replay。规格见 Feature191 `controller-child-claim.md`、
`preclaim-execution-control.md` 和 `fresh-native-preclaim.md`。最终 head `8e56b42f` 的
CI `38511478558` 与独立审计已通过；PR99 在此基础上补齐单 child 闭环。
旧 unbound native 仅只读观察 gateway 传入 ledger 的本次 inode pin，不新增持久 failure
authority；已绑定 Python child 仍要求原 exact ledger 和 constructor pin，不能卸除
绑定来进入兼容分支。取消/过期的 fresh request 在 claim 前拒绝，不再制造 started。

单 child 的 claim → execution → receipt → admission/publication → recovery 闭环已验收。
剩余 P0 是显式多 episode DRS 的连续发布/历史恢复与中断矩阵，随后单独处理 BRS。
默认 staging-only 和 CLI native opt-in 继续拒绝。缺失、unknown、漂移、取消和 deadline
不允许 fixture fallback、重复 staging 或重启 started claim。原单独 claim API 仍只
登记 claim，不因已有 claim/readback 自动取得执行 continuation。

真实 Python/CPython source、toolchain、sealed runtime、OpenEvolve/Shinka project lifecycle
和生产 RSI CLI 仍属于后续 P0/P1 验收，不能由 provider-free fixture 关闭。remote evaluator、
external worker authentication、multi-host ownership、distributed scheduler、service API
和远程 Shinka/Slurm 继续作为 P2 后置范围；所有条目保持 `production_admission=false`。

本轮起点为 `main 17ebde4`，PR87 已合入；其最终来源 CI 与独立 raw/source/tree
审计通过，合入后 main CI 也通过 15/15。本文按代码、指定任务清单及 GitHub 最终来源检查整理当前工作；
历史交接里的 pending 不等于功能尚未开发。所有条目保持
`production_admission=false`。

## 已开发的基础能力

durable controller resume、unknown reconcile gate、fingerprint drift、统一预算和
CLI usage、retained producer replay、admission row/checkpoint references、DRS first-pin、
BRS ready/ack、publication/recovery gates 已存在。`rsi replay` 与
`RetainedProducerReplayGateway` 已存在；无需再创建 replay DTO 或第二套 admission 接口。

Feature189 的 archive/source/staging/provenance 比较器、Feature193 的 marker source、
F01–F05 detached contracts 和 controlled build driver 已开发。driver 只接受 mock
backend，不产生实际 CPython image。新增独立 `run_pinned_build` 执行机制消费另行审阅的
recipe 和输入/tool bytes pins；它没有内置或自动推导实际 CPython recipe，不完成 G1/G2。
Feature190 原始 executable owner 是已记录验收的
基础能力，真实 sealed CPython 与它的组合仍待验收。

## P0/P1：当前开发与集成项

| 优先级 / 功能 | 基线现状与剩余工作 | 结束条件 |
| --- | --- | --- |
| P0：scheduler 晚期 prepared 接线 | 已实现显式启用的 immutable post-execution supplier → 原 handoff pin → transaction prepared observer → DRS/BRS first-pin；首次 record/reference 在后续边界持续复验。DRS bridge 已适配实际 controller 返回的 canonical record。规格见 Feature191 `late-prepared-scheduler-join.md`。 | PR87 最终来源 CI/审计已通过；真实 runtime 验收仍在下表。普通 native path 保持兼容，取消、缺失、漂移和 callback failure 保留既有 unknown/obligation。 |
| P1：本地 OpenEvolve/Shinka result exporter | 已实现 `read_python_producer_adapter_export`，复用现有 bounded wrapper/SQLite/source readers 和 common adapter verifier；原始 evidence 与独立 pins 在 source I/O 前验证。规格见 Feature191 `local-python-producer-export.md`。 | PR87 最终来源 CI/审计已通过；不把 producer score 当官方 verdict，不据此宣称真实 project lifecycle。 |
| P0：受限构建执行机制 | 独立 `run_pinned_build` 接口执行另行 pinned recipe 的 configure/freeze/compile/link，保留 bounded logs、输出 pins 和失败记录；原 mock-only API 保持兼容。 | 当前 main 集成基线 CI/审计已通过。真实 source/signature/toolchain 和 CPython executable recipe 仍未冻结；工具执行完成不等于静态 image 或 installation 验收。 |
| P1：单 episode producer 组合 | `PythonProducerRSISolverGateway` 复用原 Python plan/input gate、native scheduler/claim/receipt 和 prepared handoff，要求同一 ledger、原 producer identity 与 controller proof。CLI native opt-in 在缺配置时前置拒绝。 | 当前 main 集成基线 CI/审计已通过。一个预先 staged context 只绑定一个 request/memory/launch；完整 DRS/BRS CLI 需要逐 episode 接线，不得直接复用为多 episode campaign。 |
| P0：controller 调用的逐 episode durable staging | 已开发 preparing → ready/unknown、create-only child input/launch/sidecar、一次临时 owner/CAS permit、原 request/memory/文件 pins 关联及只读恢复拒绝。规格见 Feature191 `per-episode-producer-launch.md`。 | 当前 main 集成基线 CI/审计已通过。默认 ready dispatch 与 BRS opt-in 仍拒绝。 |
| P0：显式 child claim 与 fresh preclaim | PR98 将 ready preview 重新验证后登记为原 native claim；checkpoint CAS 同事务、取消/截止时间与配置漂移门禁已接入。 | 最终来源完整 CI/独审通过且已合入；原 claim API 不自动授权执行。 |
| P0：显式单 child 闭环 | PR99 接通原 claim/running/scheduler/prepared/publication/mapper/verifier 与只读终态恢复。 | 最终来源完整 CI/独审通过且已合入；仅 inert/provider-free fixture，默认 staging-only。 |
| P0：同 workspace 多 episode DRS | 显式 append lineage 与独立只读历史 inspection 已写入当前隔离分支；原 owner/CAS/pins/预算门禁保持。 | 三个不同 child、M0→practice commit M1→target M1、历史恢复和中断矩阵尚待统一验收；all-rejected/BRS 仍开放。 |

以上开发项完成后仍不启用 production runtime。`rsi run` / `rsi resume` 的
OpenEvolve/Shinka 选项当前仍明确输出 `solver_execution=provider_free_fixture`；
它们不会启动真实 producer。

## P0/P1：依赖真实 source/toolchain/runtime 的验收项

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
Feature191 `project-runtime-profile.md`；它是尚未验收的设计，不能由当前 candidate
startup/codec 冻结模块列表推导实际 SDK 可用性。

## P2：明确后置

| 功能 | 进入与结束条件 |
| --- | --- |
| Remote evaluator、external worker authentication | 单独确定受支持的来源/身份协议及 evaluator 接口后，以真实外部 receipts 和验收证明接通。 |
| Multi-host ownership、distributed scheduler、service API、remote Shinka/Slurm | 单独确定多机 authority/recovery 和部署范围，再验收跨主机故障与请求结果；不作为当前本地 P0/P1 接线的前置条件。 |
| Model credentials、WebAgent comparison、model adaptation 与效果 campaign | 在 runtime/local producer 验收之后按独立研究或 campaign 范围执行，保留固定基线、预算、原始结果及回归证据。 |

## 验收账本：CI 与 raw/source/tree audit 分开

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
真实 runtime acceptance 是不同状态。下轮只推进表中具体剩余项；历史条目保留其来源。
