# Lunar Evolution 当前能力、剩余工作与终态验收

## 2026-09-27 当前判断

**原生自动多文件链路现在可以端到端回归。** 本轮统一离线入口的 **224 项全部通过**，
没有失败、错误或跳过：合同准备、候选生成、本地执行、独立评分、选优、父任务交付，以及
前后台一致性、等待输入、answer/resume、取消、真实超时进程与后代清理、强杀恢复和仓库外
安装。独立 CLI quickstart 的四候选得分为 1/2/6/7，交付 7 分候选，终态 resume 没有重复
请求或执行。以上使用 mock/subprocess/loopback 夹具，不增加真实模型成功样本。
后续新的真实验收沿用此前模型和支持的任务，由新登记绑定其精确材料；不复用旧槽。

可重复入口见 [142 quickstart](../specs/142-automatic-solve-lifecycle/quickstart.md)，本轮报告为
`.lunar-evolution/test-results/native-e2e-20260927-final/{native-e2e,runner}.xml`；runner 的
**46 项测试通过**。该入口只运行当前原生集成范围；本轮默认完整三阶段也已通过：当前
**7586 passed / 7 skipped**，历史 **2294 passed**，原始登记 **24 passed**，全部 0 失败/错误。
报告位于 `.lunar-evolution/test-results/native-e2e-release-20260927/`。

Feature 157 现在已有真实 controller-owned HTTP POST worker：请求经 broker 登记后使用
独立进程、同一绝对 deadline 和有界 IPC；只有确认终止并回收后才报告宿主超时执行成功。
成功响应可返回调用方，payload/response 不进入宿主 journal。它只覆盖主动经过 broker 的
请求，仍缺 producer 出口/credential 隔离、生产 journal 保护和 Feature 156 正式接线。
下方 9/25–9/26 的“尚无实际 transport”等表述是历史状态。

| 优先级/范围 | 仍需完成 | 验收终点 |
| --- | --- | --- |
| P0：原生链路发布 | 新真实验收 runner 和 task/input/evaluator/profile/8 项 holdout 材料，固定产品/模型/预算，独立新登记与唯一 attempt | 新真实模型生成、执行、独立评分、选优和父交付全部有绑定证据，cleanup 与 postrun 独立审计通过；139 历史 preparation 1/1、primary/joint 0/1 不变 |
| P1：外部 producer 生命周期 | 原生可信 bootstrap artifact、bootstrap/target 执行字节 handoff、Feature 156 共享登记/单一 deadline/清理/恢复及完整矩阵 | T158-04 与 T156 整体生命周期关闭；Python bootstrap fixture 不能替代生产入口 |
| P1：外部 producer 请求边界 | 完整出口覆盖、credential 隔离、受保护生产 journal、Feature 156 与崩溃恢复接线 | T157-05/06 与 T156-14 关闭，绕过 broker 和控制器崩溃均有实证 |
| 后续外部集成 | producer 输出自动进入 admission → execution/evaluation → population/archive → parent delivery，及真实框架 campaign | 新登记的外部 producer 全链路完成；已实现 staged publication 等局部能力不重复开发 |
| 可选扩展 | automatic solve 接入通用 WorkerService/递归 Worker API、更复杂输入和跨文件依赖、远端执行 | 先确定发布范围，再给相应用户入口与独立验收；这些不是当前原生 E2E 的前置条件 |

因此，当前可以验证和使用原生离线完整链路；**真实模型完整交付和外部 producer 生产链路
尚未完成验收，不能宣布全部功能生产可用**。以下保留各日期的历史记录；当前剩余项以本节
和 [156](../specs/156-producer-process-lifecycle/tasks.md)、
[157](../specs/157-producer-request-evidence/tasks.md)、
[158](../specs/158-trusted-producer-bootstrap/tasks.md) 的开放任务为准。

2026-09-26 补充：Feature 158 新增拟议正式 bootstrap 登记的只读跨记录校验，fixture
登记已改用独立文件名，fixture 清理也核对 OS 进程启动身份。这些改动收紧证据和清理边界，
尚未使 Feature 156 runner 启动平台字节绑定的 bootstrap，也未连通共享终态证据与恢复。
T158-04 仍开放；下述生产可用判断不变。

2026-09-26 更新：Feature 156 已有显式、授权的崩溃后 producer 进程组清理，默认恢复仍只读。
恢复回执只证明清理观测，执行结果保持 unknown；活跃控制器竞争、锁文件替换、登记或 OS
进程身份不匹配均不能获得清理授权。锁设备号/inode 已绑定到登记 digest 并在发信号前复核。
这尚未完成 Feature 156 整体生命周期验收。trusted bootstrap 正式接线、Feature 157
真实受控请求出口、外部 producer 自动接入 population/archive/delivery，以及新真实模型
完整交付成功样本仍缺失。因此当前仍不能宣布生产可用。

2026-09-25 更新：provider-free 原生多文件端到端链路仍可运行，Linux 外部 producer
启动链新增 sealed memfd 执行字节绑定并通过真实 Linux 替换攻击回归。宿主请求账本现可
逐条持久化并只读恢复，但尚无实际受控网络代理、超时取消和出口隔离；trusted bootstrap
仍是 fixture，崩溃后进程组清理也未完成。因此外部 producer 不能进入默认调度或宣称
生产可用。真实模型完整交付仍无新成功样本，Feature 139 历史结果不变。当前开发状态
以 [Feature 156 任务](../specs/156-producer-process-lifecycle/tasks.md) 和
[Feature 157 任务](../specs/157-producer-request-evidence/tasks.md) 为准。

2026-09-23 增量：142 的 provider-free native 多文件 quickstart、Phase C subprocess 生命周期
和 CLI/integration 复核均通过；四个候选得分 1/2/6/7，选择并交付 7 分候选，`solve --resume`
没有重复调用。146 递归 worker 的取消、恢复和父状态准入已通过本地及 Linux 三版本 CI；147
的离线六阶段结构观察器与保留目录字节审计、148 的 artifact/lifecycle 与 8 项 holdout 语义
审计，以及 149 的独立 cleanup-v1 receipt 均已实现并通过 provider-free 回归。它们不把结构
完整或摘要一致计为真实成功。Feature 139 唯一真实槽已完成但结果为 preparation `1/1`、
primary/joint `0/1`，所以当前发布重点是取得新的成功样本，而不是重跑旧槽。142 的 registration
manifest/seal 与只读 preflight 已实现并推送；新成功样本仍需新登记材料、唯一真实 attempt 和
postrun 审计；详见
[147 validation](../specs/147-acceptance-evidence-observer/validation.md) 和
[148 tasks](../specs/148-artifact-lifecycle-holdout-auditor/tasks.md)。

2026-09-21 最新增量：142 Phase C 的自动后台 solve/resume/answer 已实现，实际本地子进程
验收覆盖同父任务交付、待答退出、取消、强杀恢复和并发排他。启动成功单独报告
`launch_status: accepted`，策略仍从原任务恢复，接受过的答案不会因启动失败丢失。
本轮完整三阶段回归已通过：当前 6684 passed / 1 existing skipped、历史 2294 passed、
原始注册 24 passed，独立审查通过。产品 `ff1edcb` 的首次 Linux CI 在 3.11 的一项旧测试失败；
受控复现定位到测试连接 GC 竞态，仅测试修复 `ad89b50` 后，Python 3.11/3.12/3.13 的安装、
完整三阶段回归、报告保存和静态检查全部通过。产品与 tools 字节保持 `ff1edcb`，首次失败保留。
自动后台发布验收已收尾，精确结果见
[142 validation](../specs/142-automatic-solve-lifecycle/validation.md)。以下历史提交的计数
不替代本次验收；真实模型完整交付仍是剩余重点。143 T009 的前台 `delegate` consumer
已实现；`9213f01` 检查点为当前 6703 passed / 1 skipped、历史 2294 passed、注册 24 passed。
已补齐交付并发审计，重复观察者不会删除先前成功交付的证据；范围仍限定为单任务前台路径。

评估创建于 2026-09-16，2026-09-21 更新补充候选响应可靠性（144）与统一命名（145）。
当前产品统一使用 Lunar Evolution；包/命令、用户配置、默认 home 与后台入口同步迁移，
无旧身份兼容别名。历史封存资料和原测量测试改由[固定归档索引](history-archive.md)定位，
原始 hash、分数和 Git 历史不改写。全新安装和真实 detached mock 验收已通过，完整回归
产品 `3307fcc` 已推送，本机当前 6585 项通过、1 项原有跳过；历史 2294 项和固定注册 24 项
均通过，回归后的 188 个私有证据文件仍与原始清单完全一致。结果见
[145 validation](../specs/145-lunar-evolution-identity/validation.md)。该产品提交的 Linux CI
也已确认 Python 3.11、3.12、3.13 全部通过完整三阶段回归及静态检查。名称迁移不增加
真实模型成功样本，也不关闭下面列出的实现和发布验收缺口。

已推送的 142 历史产品
基线为 `65d9ae2`：Feature 142 Phase A
前台生命周期和 Phase B 进程取消/清理已完成。本机定向、兼容和双阶段全量回归均通过；
该历史提交的 Linux CI 曾失败；后续修复提交 `8e1e089` 已通过 Python 3.11/3.12/3.13
完整双阶段 CI 与静态检查，跨平台代码回归已关闭，具体证据见下文。
Feature 140 的持久候选生成回执已推送；Feature 141 的原生多文件 CLI 显式候选预算已由
`87d86d9` 推送，409 项聚焦测试、当时全量当前 8166 项和历史固定 24 项通过（当前 1 skipped）。
Feature 139 的原生证据链、worker 和只读 summary 已完成离线集成及独立复核；其检查点完整
双阶段为当前 8409 passed / 1 skipped / 24 deselected、固定历史 24 passed，overall exit0，
包含全部 363 项专项测试。Feature 142 Phase B 的最终双阶段结果为当前
`8636 passed / 1 skipped / 24 deselected`、冻结历史 `24 passed`，overall exit 0；报告位于
`.lunar/test-results/feature142-phase-b-20260921/`，Phase B 定向回归为 146 项。
Feature 139 的唯一真实 `attempt-001` 已完成，但未通过自动多文件完整交付验收：
preparation 为 `1/1`，primary/joint 为 `0/1`，没有 completed candidate 或父任务交付。
以下历史段落保留各次测量当时的判断，当前安排以本节的发布判断和剩余工作表为准。

## 2026-09-21 发布判断与剩余工作

当前具备可开发和本地使用的实现基础，尚不能宣称“所有功能可用、完整版本已验收”。
自动多文件的前台与后台链路已通过离线完整回归和 Linux CI，真实模型完整交付仍未成功；
143 已接通单任务前台 `delegate` consumer，交付并发审计已通过；AgentLoop 的 worker-tool
façade 与递归 WorkerService 生命周期已有 opt-in、provider-free 实现，但自动 solve 尚未接入
WorkerService，仍不属于该 `bounded slice`。不能把未接入的可选框架当作所有发布范围的前置条件。

| 优先级/范围 | 尚未完成 | 完成条件 |
| --- | --- | --- |
| P0：前台自动多文件验收 | 离线观察、语义审计、cleanup-v1、registration preflight 和旧槽真实失败样本均已保留；当前没有成功交付样本 | 新身份、新目录和固定产品/模型/预算下，生成、执行、独立评分、选择、父交付全部有绑定证据；单独报告准备、primary/joint 和留出结果 |
| P0：真实候选完成率 | 144 已补明确响应协议、消除通用总结指令冲突并保留细分失败诊断；真实成功率仍未确认 | 在新的固定条件验收中检验；保留严格解析和失败分母，不把离线 fixture 通过当作真实可靠性提升 |
| P1：更广泛并发多 Agent 的发布 | 143 T009 单任务前台 `delegate` consumer 已接线并通过交付并发审计；AgentLoop façade 与递归 WorkerService 已有 opt-in 实现，自动 solve 尚未接入，也没有真实模型效果验收 | 若纳入发布范围，再把 AgentLoop façade 与递归 worker 接入目标用户入口（包括自动 solve），并分别验证用户操作、结果回流、取消和恢复 |
| 后续能力 | OpenEvolve/Shinka 的自动外部 bundle admission、archive/交付接线、启动调度及真实框架验收 | Feature 150 已提供显式、provider-free 的 bundle grouping 和源文件校验，Feature 151 已将已校验 bundle 投影为 native `CandidateDraft`，Feature 152 已提供绑定本地 authority 的只读 admission plan，Feature 153 T153-01/T153-02 已提供 canonical batch journal 与 zero-write preflight 并写明 staged publication 的 SDD；执行、archive publication、delivery 和 launcher 仍须按该事务契约接入并在新独立登记中验证；不重跑 WebAgent |
| 后续扩展 | 更复杂输入、跨文件依赖、通用仓库/workflow 与远端运行 | 明确支持范围和代表性验收，不从一个双文件样例外推 |

公共 GitHub Actions 元数据确认 [run 35522272395](https://github.com/vchive/Lunar-Evolution/actions/runs/35522272395)
中的 Python 3.11 checkout、环境和依赖安装成功，`Run tests` 退出 1，静态检查未运行。
3.12/3.13 的取消原因明确为矩阵中 3.11 失败，不是两个版本各自验收失败。公开注释没有
失败测试名，日志要求登录，下载接口返回 403，且该次无上传报告；当时无法判定 current
还是 frozen123 阶段失败，也不能归因于冻结历史 guard。旧运行的这些限制不改变已经保留的
本机双阶段通过证据；后续通过新增诊断定位问题，进度如下。

随后 `c22bd37` 增加有界公开失败摘要、报告保存和独立矩阵运行，新诊断 run 三版本均报
96 项失败，首批定位到候选执行。受控本地复现确认 shell 的符号链接路径触发既有安全拒绝；
`93469e7` 已将四个正向 fixture 改成真实可执行路径，相关 164 项通过，产品安全约束不变。
该矩阵已确认候选执行失败消失，另暴露三项历史链单测依赖私人本机文件、一项虚拟环境
身份不匹配，以及 Python 3.12 的间歇性测试连接 GC 问题。后续仅在 CI 设置与测试 fixture 修复，
新增负测并保持原校验函数、真实历史记录不变。最终 `8e1e089` 的
[run 35526731156](https://github.com/vchive/Lunar-Evolution/actions/runs/35526731156) 已确认三个版本的
完整双阶段测试、报告保存和静态检查均成功，CI 发布检查已关闭。该结论不增加真实模型样本；
产品、测试和 CI 配置在后续验收文档同步中保持不变。详见
[143 validation](../specs/143-local-worker-lifecycle/validation.md)。

Feature 143 已修复审计发现的三项问题：每个 attempt 使用独立执行 adapter/runtime，第二个
服务不再误判活动 owner，已取消的排队任务不会进入 adapter。实际进程 observer 绑定精确
attempt；登记异常会停止对应执行，清理未确认时保留进程记录。跨服务关闭/恢复和迟到结果
也不会覆盖新的 attempt。Store migration 8 保留未知 owner 的旧记录；显式恢复需要确认
owner 已中断并完成清理。`send` 仍排队到显式 resume，与启动认领在同一事务消费。
共享回归 260 项通过；完整当前 8708 passed、1 skipped、24 deselected，冻结 24 passed。
完整证据见 [143 validation](../specs/143-local-worker-lifecycle/validation.md)。
T009 的实际用户入口已接入：前台 `delegate` 现在执行 claim → bind → start → wait →
result envelope → artifact handoff → evaluate → settle。`9213f01` 检查点的实现回归为当前
6703 passed / 1 skipped、历史 2294 passed、注册 24 passed，另有重复观察者交付回归通过；这仍是
provider-free 的实现验收，不能把它扩展为真实模型多 Agent 效果已完成。

Feature 144 延续候选生成链路，给多文件请求增加本次调用专用的 JSON 响应协议，明确
`experiment` 两个数组的形状和可省略性；普通任务、历史会话与外部旧 runtime 保持兼容。
严格 parser 未放宽，scratch 文件不能替代最终候选。失败回执保留有界阶段和来自已验证
异常类型的模型原因，修复三种运行时失败名称无法入库的问题；解析失败保留已观察的预算
消耗，旧调用诊断和外部自报原因不能冒充本次证据。离线有效样例实际执行并独立评分，
失败样例不进入下游；最终回归和证据范围见 [144 validation](../specs/144-candidate-response-reliability/validation.md)。
最终产品 `c6947fd` 的 Linux/Python 3.11、3.12、3.13 完整 CI 也已通过。
这些改动不增加真实模型样本，139 的 preparation 1/1、primary/joint 0/1 不变。

当前 CLI `delegate` 已走 durable worker lifecycle；AgentLoop 在 WorkerService attempt 内已有 opt-in
worker 工具 façade，普通任务的 `run_agent()`、142 前台自动多文件仍不依赖该 WorkerService；这些 worker 修复不改变
142 Phase A/B 的验收。142 Phase C 已接通独立后台协调进程；真实前台验收准备与 143 consumer
验收分轨完成本轮本地与 Linux CI 验证，
但在新真实验收登记时必须固定产品，不能运行途中换代码。143 T009 不阻塞 142。

本轮包含 worker 产品修复、AgentLoop façade、永久回归与 CI 诊断；没有 provider 请求或新增真实效果结果。
历史 139 的未勾选项是冻结的离线检查点；其唯一槽已经结束，不是待重跑任务。104/133 后续
均已实现，不能仍按最初“只写规格”状态算欠账。旧 002 已被 003 替代，094 的漏勾项已有实现
验收。冻结记录不为清理待办而重写。

Feature 142 沿用已有 SDD，不重起方案。`solve`、`solve --resume`、`resume` 与 `answer` 的新
automatic handoff 共用前台入口；显式 `--solve-wall-timeout` 给一次活动执行建立固定 deadline，
从合同 intake 覆盖到 preparation、候选生成/执行/独立评分、选择和父任务交付。阶段和请求只
收窄 operational timeout，不改变冻结 profile、plan、contract、receipt 或候选身份。策略持久化，
但耗时不跨 resume/answer 累计；合法继续是新的 active execution，终态或已耗尽 run 不可补充
预算。未指定该选项不会产生隐式 solve 时限，旧 handoff 保持原语义。

唯一 durable parent orchestration task 在合同接受后建立，普通 scheduler 不执行它；父任务在
child 与 verified delivery 完成前保持运行。跨进程 `flock` 与进程内 owner 防止同一 parent
并行继续，answer 在写入前取得锁。预算、取消和先有终态按 Store winner 收口，晚到成功或新
输出发布不能覆盖终态。`solve_execution` 只读公开 execution ID、策略及来源、固定阶段、状态
和 stopping reason，不报告实时 monotonic 剩余量或猜测远端 provider 状态。automatic
`--detach` 现通过继承锁与启动闸门接入同一执行入口；没有新增真实 campaign，Feature 139 的 `0/1` 不变。

Phase B 已完成严格父子链接上的取消传播，candidate/evaluator/probe/runtime 的实际 PID/PGID
登记，工作进程组优先清理，以及失败保留 ownership 和迟到响应拦截。详细证据见
[142 validation](../specs/142-automatic-solve-lifecycle/validation.md)。新前台真实验收的预算和
六阶段条件见 [real acceptance plan](../specs/142-automatic-solve-lifecycle/real-acceptance-plan.md)；
该计划尚未形成新的测量实现、冻结 manifest 与启动前检查记录。

Feature 136 已为单文件和 bundle 候选生成加入显式、不可变的每候选 tool-step budget 与
authority-bound identity，并将 runtime failure、空响应和 parser failure 投影为有界诊断。
完整候选只在 parser 接受后计为 completed；整批超预算仍原子拒绝。该功能仅通过本地 fixture
验证，没有重跑 Feature 134，也没有真实 provider 或 campaign 结果。Feature 137 还修正了
预算失败后晚到取消会把 blocked task 改成 cancelled 的终态竞争，保证 failed 优先级保持。
最初盘点基于 `af4f8d8`（Feature 107）；
随后已完成多文件独立评测、原生 population、Agent 生成、普通 solve 自动准备和父任务交付。
首批 `c977eb4` 真实验收已完成：两例均在合同编译失败，尚未形成有效多文件交付。
随后 114 隔离合同编译并补齐 schema，115 新验收仍为 0/2：一例合同通过后 evaluator
请求超时，另一例合同请求超时。尚无真实多文件交付。
116 已区分依赖等待与用户待答，并为自动准备增加可查询失败记录及显式恢复提示；
这是离线验证的状态/恢复修复，不改变真实验收结果。
117 随后独立登记 600 秒单调用/3600 秒每题预算，结果仍为 0/2：一例 evaluator 请求
超时，另一例合同返回 Markdown JSON 代码块被拒绝。116 的失败状态/诊断已真实生效，
但没有冻结 evaluator 或交付，完整链路效果仍未验收。
118 已离线修复完整 JSON 代码块的入口兼容，并引入显式约束验证范围。生成 evaluator
在请求前拒绝尚无独立检查能力的 source/execution 要求，保留合同并给出具体诊断；
这不是新增源码/执行行为验证器，113/115/117 的真实结果不变。
119 随后接入精确的最少 Python 源码文件数检查，独立源码证据参与评测、选优与父任务
交付；不支持的行为要求仍提前说明。自动离线流程已拒绝单文件高分候选并交付合规双文件
结果，当前版本真实多文件有效交付仍未验收。

## Feature 120 真实验收结果

Feature 120 在已推送登记 `f3b575c` 上按支持范围运行两题，结果 **0/2**。两题合同编译分别耗时约44秒和118秒，随后 evaluator preparation 请求都在600秒 `open_response` 超时；无 evaluator、候选、交付或 holdout，已知用量16,161 tokens，超时消费/费用未知。详见 [120 report](history-archive.md)。

Feature 121 随后离线补齐 evaluator compiler/auditor 的完整响应/报告格式、源码限制和
合成测试数据规则；新增51项测试通过，最终全仓 **6049 passed, 1 skipped**，保持解析、
调用与恢复协议。原120请求从冻结源码
重建且哈希匹配，没有重复历史/合同。请求大小不证明超时原因，121没有真实模型结果，
不能据此更新多文件有效率。见 [121 validation](../specs/121-evaluator-prompt-protocol/validation.md)。

Feature 122 为有界 HTTP 请求补充最后本地里程碑、第几次 HTTP 交换和经过毫秒数，
分别记录进入连接、连接返回、请求写入调用返回和响应头返回（含中间重定向）等已观察点，
不保证失败时仍处于该阶段。
连接仍合并 DNS/TCP/代理隧道/TLS，写入返回不证明远端接收或模型执行。新详细失败使用
subject schema5，历史1–4和粗 phase/status 保留；请求参数和时限不变。新增151项测试和
445项相关回归通过，最终全仓 **6200 passed, 1 skipped**；恢复与历史字节复验通过。
这为下一次独立登记的小型 evaluator 准备诊断提供工具，没有新的真实模型测量，
113/115/117/120仍各自0/2。见 [122 validation](../specs/122-transport-milestone-observation/validation.md)。

Feature 123 随后先推送独立登记再执行一项小型合成evaluator准备诊断。唯一compiler请求
在242.848秒HTTP200返回（20831tokens、费用未知），随后本地自测拒绝；freeze/joint均0/1，
没有auditor或8项holdout执行。静态检查确认生成源码把input descriptor的target误认成path，
使有效probe提前被判无效。下一步补齐snapshot request的实际嵌套结构和本地一致性检查。
这个诊断没有solver/多文件交付，不证明原120超时根因或真实闭环已成功。见
[123 report](history-archive.md)。

Feature 124 已补齐共享snapshot请求示例：runtime inputs[]使用target，contract/profile/probe
中的path分别解释，outputs[].path直接读取，不重复前缀。元数据和任务内容明确区分，
两种生成角色各保留一份contract/profile。8项新测试在成功冻结流程捕获6次预检，另验证
错误字段被拒绝，并完成2次生产评测，覆盖嵌套/零字节输入与可选输出缺失。88项相关回归和112终态恢复
通过。全仓另暴露24项历史登记测试要求旧产品字节，现由显式双阶段入口在固定快照执行，
当前回归仍用当前代码；18项隔离/失败传播测试通过，CI已接线。最终当前代码
**6304 passed/1 skipped**，固定历史快照的**24项全部通过**，整体exit0。见
[124 validation](../specs/124-snapshot-request-protocol/validation.md)。这是本地协议修复，
尚无新的真实模型结果；下一步单独登记修复后的准备诊断，123的0/1保持不变。

Feature 125 已完成该独立诊断：compiler通过原生自测并进入auditor，两请求HTTP200，
合计36499tokens；本地audit准备校验失败，freeze/joint仍0/1，0/8holdout执行。静态检查
发现evaluator和其3个自测把JSON输入误当整数；合同与5个audit输入是含limit的对象，
evaluator的整根类型检查会拒绝有效对象。独立audit阻止了错误冻结。下一步让合成输入复用
真实输入既有格式准入，并补准确本地阶段诊断；不从描述字段推断通用schema，不修补旧响应。
见[125 report](history-archive.md)。这仍未完成真实
多文件交付，不构成124因果收益；123与125分母各自独立，均0/1。

Feature 126 已让合成输入和真实画像共用格式解析：compiler/audit整组输入在第一个probe
执行前准入，两种调用模式和无效输出探针均覆盖。JSON标量、坏CSV等会提前失败；
不要求私有行数/类型统计匹配，不将fields描述当schema。共享提示同步，旧冻结bundle
保持只读恢复，不重新执行或准入历史probe。81项新测试、240项相关回归、112终态恢复
和独立审查通过；最终当前代码6526 passed/1 skipped，历史固定快照24 passed，整体exit0。
全仓与历史核验见
[126 validation](../specs/126-synthetic-input-format/validation.md)。本轮没有真实模型调用，
不改变旧完成率；下一步补准确本地准备阶段/原因，再独立登记真实诊断。

## 当前判断

Feature 135 已让无 ModelProfile 的普通 Agent-loop 请求看到剩余工具步数和有限墙钟剩余时间，
并为整批超限拒绝提供类型化证据；profiled/isolated 行为与 Feature 134 历史证据保持不变。
这解决了“模型不知道还剩多少工具调用”的可观察性缺口，但没有提高工具上限、自动重试或
证明真实生成一定完成。下一步仍应按 SDD 设计并离线验证每候选显式预算与完成诊断，再决定
任何新真实测量的独立登记条件。

Feature 127 已为compiler/auditor响应准入及本地preflight提供固定原因和数字位置，自动
准备记录schema2/local_failure，JSON/文本status可见；旧schema1和runtime恢复保持。
位置字段拒绝bool/超界，详情复验parent/attempt/start和阶段关系，坏详情降级，取消/终态/
输入漂移/已准备结果优先。仅描述本地失败检查，不暴露生成内容、不授予重试或评分权限。
提示、解析器、冻结身份未改；244项新测试通过，最终当前代码6770 passed/1 skipped，历史
固定快照24 passed，双阶段exit0。离线验证见
[127 validation](../specs/127-evaluator-preparation-diagnostics/validation.md)。

Feature 128 已在固定产品b951857、先push登记38c323c后完成新的唯一小型诊断：compiler/
auditor均HTTP200，3项自测与5项独立探针通过，冻结1/1，8项预声明holdout全部精确匹配，
联合1/1。耗时507.148秒、记录用量完整43630tokens、费用未知、清理通过。209项测量测试与
325项相关回归通过，63份保留证据和全部固定pins复验通过。见
[128 report](history-archive.md)。这次没有solver或
多文件交付，也不证明通用评测正确性或126/127因果改善；8项整数检查不完整覆盖bool/float。
Feature129随后独立登记08624f5并push，固定同一产品运行小型真实自动多文件任务。唯一
合同请求45.509秒HTTP200，4076tokens；响应顶层仅contract、缺少status=compiled，原生
parser拒绝，未进入evaluator或候选。primary/preparation/joint均0/1，0/8holdout执行，
quality/gap为null；总47.339秒、exit1、清理通过。183项新测量测试和353项相关回归通过，
16份证据复验匹配。见[129 report](history-archive.md)。
仍未完成真实多文件交付；下一步补完整合同响应封装示例及离线检查，保留严格字段验证。
现有提示已描述status规则，不能归因于规则缺失，也不能据此证明提示修复必有效；旧槽不重开。

Feature130已在离线提示中加入两种完整、生产parser可接受的JSON封装示例，并明确只复制
shape、不复制任务事实。生产parser和contract shape校验未改，缺status的contract-only响应
仍按原错误拒绝。99项聚焦、104项相关回归、112 quickstart及全仓双阶段验证通过：当前
7168 passed/1 skipped/24 deselected，固定旧产品24 passed。没有真实请求，129仍为0/1；
后续实测必须以新Feature独立登记并先push，不能把本轮当作成功率或真实闭环证据。

Feature131固定产品`c730483`，先push登记`1993f11`后执行与129相同任务、provider、预算、
population和seed的唯一槽。contract compiler在25.237秒HTTP200返回，已知3656tokens，
原生合同验证通过；129的封装失败在这个同任务样本中没有复现，但不能据此归因于130。
evaluator compiler随后在等待响应头时于600.004秒`transport_timeout`，没有HTTP状态、响应
正文或已知用量；该里程碑不能区分provider排队、模型生成或其他远端延迟。总用量因此为
null。primary/preparation/joint均0/1，0/8 holdout执行，没有evaluator、candidate或delivery，
quality/gap为null；清理和21份证据库存复验通过。见
[131 report](history-archive.md)。原始transport台账中的
首请求HTTP200未进入公开`results.json`投影；CLI/worker已失败且runner pid/pgid为空，但
SQLite父run仍为`running`、任务为1 ready/3 waiting/1 succeeded。两项均未造成成功误判或
残留进程；当时分别列为安全HTTP状态投影和持久终态一致性后续项。Feature132复核后确认
后者是116的恢复契约，不能把父run改成终态failed。

Feature132补齐自动准备模型请求的安全诊断链路：精确类型的请求失败通过compiler/auditor
边界进入schema3事件，普通JSON/text status能查看reason、已观察HTTP状态、阶段/耗时/
时限及最后传输里程碑。详情严格绑定唯一紧邻start和parent/attempt，坏详情降级，取消、
终态、输入漂移与已完成准备优先；旧schema1/2和显式恢复保持。进一步复核116设计确认
父run的running是为保留合同恢复而刻意保留的durable状态，effective status已为failed；
上段131提出的“持久终态一致性”应据此澄清，不能直接把父任务永久失败。历史报告未改。
本轮不改变请求时限、模型参数或提示，不证明远端生成速度或成功率提高；验证见
[132 validation](../specs/132-preparation-request-diagnostics/validation.md)。

Feature133已完成独立 preparation 请求与总墙钟预算。新 compiled solve 持久化两项预算及
来源，resume/answer必须匹配原策略；旧 handoff 保留请求回退及 legacy-unbounded 总墙钟。
一次准备在持久化 start 后使用同一单调时钟 deadline，模型请求和本地预检按剩余时间收紧；
观察到期后不能发布成功准备事件或创建 child。已有有界本地操作可能留下材料，但材料须
经显式恢复验证。候选生成/执行和冻结 evaluator 仍由既有 `--timeout` 控制，preparation
值不进入冻结 profile。取消、终态和完整性检查优先，父任务 persisted running/effective
failed 恢复语义保持；这还不是全链路总预算或运行中取消编排。
84项CLI、41项deadline及276项相关集成回归通过；双阶段全仓为7661 passed/1 skipped/
24 deselected与固定历史24 passed，最后的布尔预算绑定修正另经169项诊断回归通过。
见[133 validation](../specs/133-preparation-budgets/validation.md)。这些离线验证不证明模型
生成更快或真实闭环已经成功。

Feature134已在推送登记`358f738`后，以固定产品`15710bd`完成一个新的真实多文件槽。
任务、provider、GLM-5.2和population seed沿用131，普通请求/候选600秒，preparation请求
900秒、总墙钟1860秒，campaign仍为2400秒/20请求/160000观测tokens。测量增加持久策略
校验、类型化请求失败与安全HTTP状态投影。结果为preparation 1/1、holdout 8/8，primary/
joint 0/1；没有父任务交付，官方quality/gap均null。11次请求均HTTP200，完整用量98714
tokens（34088input/64626output），费用未知；896.396秒，native/process exit均1，清理
通过。父任务持久succeeded表示intake完成；失败的evolution child使CLI对外状态failed，
符合现有投影规则。三次生成都在最终候选前受限于登记的max_steps=4工具预算：前两次在
4+2>4、第三次在3+2>4时拒绝下一批工具，已有11次工具执行均成功。没有可准入候选，
evaluated/valid candidates均0，child以offspring_batch_failed结束；尚未进入候选执行、
独立评分或交付。HTTP成功不代表候选生成完成。
compiler/auditor分别346.070/124.757秒，均低于旧600秒时限，因此不构成增加预算的因果
收益。262项测量测试和全量双阶段7924 passed/1 skipped/24 deselected、固定历史24 passed
通过。见[134 report](history-archive.md)。
本次真实请求都成功；类型化preparation请求失败与墙钟失败分支仅由离线fixture验证。

Lunar 已有可运行的本地 Agent 和完整的单文件 population 演化链路。多文件链路也已接通
生成、独立执行与评分、Candidate/receipt/archive、下一代选择、terminal resume 和完整
源码/已评分输出交付。用户可通过 `evolve-bundle` 或普通 `solve --evolve --bundle-profile`
运行这条路径，也可用 `solve --evolve --multi-file` 自动编译、审查、冻结 evaluator/profile。
普通入口支持父任务交付、澄清回答和终态恢复。自动准备保留原输入格式和探针容量限制；
自动后台及当前版本真实任务稳定性、演化收益仍待完成或验收。

Feature 111 的最终基线为 **5277 passed, 1 skipped**；Feature 112 的最新验证见
[112 validation](../specs/112-automatic-bundle-evaluator/validation.md)。测试通过证明
覆盖的实现行为，不代表有效解率或相对 WebAgent 的效果。完成度按下述闭环验收判断。
Feature 114 修复后的全仓结果为 **5517 passed, 1 skipped**，详见
[114 validation](../specs/114-isolated-contract-intake/validation.md)；之后 115 已独立测量，
结果见下方真实证据。116 的产品修复验证见
[116 validation](../specs/116-preparation-recovery-state/validation.md)：最终全仓
**5636 passed, 1 skipped**，新增 69 项状态/恢复测试及本地完整交付验证通过。
118 新增 134 项格式/能力/CLI 测试，最终全仓 **5818 passed, 1 skipped**；详见
[118 validation](../specs/118-contract-protocol-capabilities/validation.md)。
119 新增 94 项源码检查、便携证据和恢复测试，最终全仓 **5912 passed, 1 skipped**；见
[119 validation](../specs/119-source-file-verification/validation.md)。

| 能力 | 实际状态 | 验证层次 |
| --- | --- | --- |
| 本地 Agent / Controller | 工具循环、任务调度、预算、SQLite、恢复、验收和交付已有实现与接线 | 自动化测试；较早普通流程有真实有效解 |
| 单文件 population | 生成、独立评估、receipt、archive/选择/迁移、checkpoint/resume 与交付已集成 | 代码和离线 fixture；当前版本收益仍待实测 |
| 多文件候选 | command/Agent/native runtime 生成 → bundle → 执行/独立评测 → receipt/archive/population → 父任务交付/terminal resume 已完成 | 普通 intake、完整父代上下文、helper-only 改进、有效性选优、迁移、失败保留、完整交付与不重跑 fixture |
| 自动 evaluator/profile | 自动 compiler/auditor、输出探针、独立 preparation 请求/墙钟预算与冻结恢复已接通；源码文件数另做确定性检查；其他 source/execution 提前报不支持 | 128及134真实准备通过，各自8/8留出；134完整交付仍为0/1 |
| 自动 solve 前台生命周期 | 一次活动执行的共享 deadline、durable parent orchestration、统一入口、排他继续、只读状态和实际进程取消/清理已实现 | Feature 142 Phase A/B 定向与最终双阶段离线回归通过；自动 detach 和新的真实完整交付尚未验收 |
| 显式 worker API | 有独立 worker/attempt、owner 活性、六项操作、进程清理和结果引用；前台单任务 `delegate` 已迁入；WorkerService 内有 opt-in AgentLoop worker-tool façade 与递归生命周期 | `9213f01` 检查点为当前 6703 passed / 1 skipped、历史 2294 passed、注册 24 passed；重复观察者交付回归已通过；自动 solve 尚未接入这些 worker API，真实多 Agent 效果仍未验收 |
| OpenEvolve | 显式 subprocess adapter、Lunar 本地重评及结果接入已有实现；Feature 150 提供 provider-free 多文件分组/校验，Feature 151 提供 native `CandidateDraft` 投影，Feature 152 提供 authority-bound admission plan，Feature 153 T153-01/T153-02 提供 canonical publication journal 与 preflight | 本地 fixture；尚无真实 OpenEvolve 搜索效果验证，也未接入自动 external admission、archive/交付或 launcher |
| ShinkaEvolve | SQLite 结果导出和 CLI population warm-start 已实现；Feature 150 提供 provider-free 多文件分组/校验，Feature 151 提供 native `CandidateDraft` 投影，Feature 152 提供 authority-bound admission plan，Feature 153 T153-01/T153-02 提供 canonical publication journal 与 preflight | 本地 fixture；尚无 Shinka launcher/调度、自动 external admission 或完整 archive/交付实现 |
| 固定条件比较 | task、comparison plan、result、evidence binding 已实现 | 协议测试；尚无这些新协议下的真实框架对照 |
| 远端演化 | lifecycle 协议和 completed material bridge 已实现 | 无内置真实 transport/client；默认本地路线不依赖它 |

代码接点：`src/lunar_evolution/controller.py`、`evolution.py`、`producer_handoff.py`、
`candidate_execution_evidence.py`、`candidate_evaluation.py`、`bundle_evolution.py`、`agent_bundle_generation.py`、
`bundle_delivery.py`、`solve_bundle.py`、`automatic_solve_bundle.py`、`bundle_parent_delivery.py`、`remote_evolution.py`。

## 版本闭环的四个里程碑

| 顺序 | 工作 | 验收条件 |
| --- | --- | --- |
| 1 | 多文件 exact evaluator 与输出契约：已完成本地实现与验证 | evaluator 实现与契约固定，成功 execution record 关联评测时输出快照；坏输出直接无效，失败进程拒绝；评测不重跑候选 |
| 2 | 多文件进入演化与最终交付：原生本地闭环已完成，外部 producer 的自动接线待补 | Candidate/receipt/archive/lineage 已表达 bundle；command generator 和 controller 已接通；helper 模块任务完成生成、评分、下一代选择与可复核交付；Feature 150 已能把显式 producer 多文件组投影为已校验 bundle，Feature 151 已能投影为 native `CandidateDraft`，Feature 152 已能绑定 admission plan，Feature 153 已定义 publication transaction，但自动执行、archive publication、delivery 和 launcher 尚未接入 |
| 3 | 统一用户入口与恢复：自动准备、preparation 预算、共享活动墙钟、父编排与交付、terminal resume 和实际进程取消/清理已实现 | parent 输入/profile 绑定与 publication journal 已接通；支持范围内无需手写 profile/harness；自动后台和更大输入格式/探针容量继续待补 |
| 4 | 当前版本真实验收 | 按本次发布声明的支持路径，使用明确模型、输入、预算和 evaluator 验证；保留失败分母，报告有效解率、分数、耗时和已知用量。外部 producer 仅在该能力纳入发布时单独验收 |

第 4 项应先用小规模端到端样例贯穿开发，再在实现冻结后形成正式测量。不能等到所有
可选框架接完才验证产品效果。普通流程仅沿用 Feature 069 已有的 Lunar 分数作为参考基线；
不重跑 WebAgent，也不为深度演化安排 WebAgent 对比。不重开旧失败槽、不改写历史分数；
新的真实测量使用独立登记与固定条件。

## 下一项实现需要解决的具体问题

自动准备 → 双文件生成 → 执行 → 独立评测 → 选优 → 交付现已通过本地进程样例。
Feature134已通过真实准备和8项留出，但三次生成均触及登记的每候选工具预算，没有完成
候选或父任务交付。Feature136 已离线完成显式候选预算与完成诊断，Feature137 已离线
完成 run 墙钟传播和取消竞态收口；准备成功不能替代完整交付验收。

Feature 138 已完成公开 transport status 投影，以及 preparation 失败时
persisted/effective/preparation 状态和显式恢复准入的稳定契约。它没有改变父任务的恢复
语义，没有回写 Feature 131/134，也没有产生新的真实效果证据；聚焦 recovery/request/
wall/capability/local-diagnostics 套件全部通过（含 malformed-stage 回归），状态投影 4 项
通过；完整当前回归为 7963 passed、1 skipped、24 deselected，冻结 Feature 123 阶段 24
passed。

Feature 140 的 durable candidate generation receipt 已推送，完成声明须绑定原生 Store
event、run/task/budget/candidate identity 和源码 bundle digest；瞬态 diagnostic 不再代替
持久生成证据。Feature 141 已把显式 `--candidate-generation-max-steps` 接到原生自动
多文件 solve 的预算持久化、继续运行匹配和生成请求；409 项聚焦测试通过，完整双阶段
当前 8166 passed / 1 skipped / 24 deselected、固定历史 24 passed，产品 `87d86d9` 已推送。
12 步是 Feature 139 拟登记的显式值，不是产品默认值。见
[140 validation](../specs/140-candidate-generation-receipt/validation.md) 和
[141 validation](../specs/141-native-multifile-cli-budget/validation.md)。这些均不是新真实测量。

Feature 139 已完成原生六阶段证据链、worker/supervision、注册 inventory、实际 retained
summary 与唯一真实槽。[预登记独立复核](../specs/139-real-multifile-closure/preregistration-audit.md)
已关闭 B001–B011 和请求/阶段时间关联缺口。离线 CLI 夹具完成 5 次请求、2 个 completed
candidates、8 项 holdout 及父任务交付，质量 3/3；缺失证据、超预算及 holdout_gate 失败均
不得获得成功。随后真实 `attempt-001` 在 3000 秒登记上限内用时 811.740448 秒，17 次请求均
HTTP 200，已知用量 135344 tokens；preparation `1/1`，两个候选生成回执为 `worker_failed`
与 `malformed_candidate`，completed/evaluated/valid candidates 均为 0，primary/joint 均
为 `0/1`，未进入执行、独立评分、选择、交付或 holdout。native/process exit 均为 1，cleanup
通过。结果不是预算耗尽，也不证明当前模型的自动多文件交付成功；完整报告见
`../specs/139-real-multifile-closure/postrun/report.md`。

[Feature 142](../specs/142-automatic-solve-lifecycle/spec.md) 已继续既有 SDD 完成 Phase A/B：
共享 active-execution deadline、durable parent orchestration、统一 continuation、终态处理、
只读 `solve_execution` 和实际进程取消/ownership 清理。定向与最终双阶段全量回归已通过，
产品 `65d9ae2` 已推送。该历史检查点之后，Phase C 已实现启动/认领/退出和后台入口，
answer 启动失败恢复与并发争抢也已通过定向验收，当前完整验证状态见本文顶部。
新的真实前台验收仍待完成；预算不是跨 resume 累计的任务 lifetime 上限。

1. 113/115/117/120 各自为0/2。118/119已修复合同兼容和支持范围内的源码检查，
   121/122补齐生成协议和传输观测；123小型准备诊断收到响应后本地失败，为独立0/1。
   124修复request字段说明缺口，125新独立诊断通过自测但被audit挡住：生成代码和自测
   同时误读输入根结构，最终0/1。126/127已统一格式准入并补本地失败诊断，128独立小型
   准备实测达到冻结1/1、留出8/8。129新闭环尝试因contract响应缺status成为0/1；130已
   离线补完整封装示例。131的合同通过，但evaluator compiler等待响应头600.004秒后超时，
   仍为0/1且未进入候选或交付。132已保留请求失败详情和明确超时边界，父run的running
   经复核是116恢复契约。133已完成独立preparation请求/总墙钟策略，134已增加HTTP状态
   投影并完成新的唯一真实槽：准备1/1、8/8holdout，但primary/joint仍0/1。只读证据确认
   三次生成都被max_steps=4工具预算阻断；136/137 已离线完成候选预算、完成诊断、run
   墙钟传播和取消竞态，不改变旧guard语义。138 已完成状态投影/恢复契约和离线验证，
   Feature 139 的唯一真实槽已完成且为 `0/1`；任何后续真实运行都须另行独立登记，不能
   重开或修复旧槽。
   历史远端耗时原因仍未知；
   不补旧槽、不改失败分母，也不把本地协议验证当成模型成功率或质量已提高。
2. 父任务交付、artifact 预算和 output journal 恢复已接通；自动模式恢复只需完整任务
   workspace/Store，不需外部 profile 路径。显式 profile 模式仍须提供匹配资源。142 已补一次
   活动执行的共享墙钟、父任务编排和运行中实际进程取消/清理，自动后台仍待完成；未知现场
   不自动重跑，终态恢复不增加候选或交付副本。
3. Feature 140/141 已补持久生成回执、CLI 预算并完成验证推送；Feature 139 的真实槽已
   完成但没有 completed candidate 或交付。生命周期继续既有 142 SDD；候选完成可靠性的
   后续产品工作应独立明确规格，提高严格最终响应协议的可完成性并保留 typed worker failure；
   失败分母保持为1，不重开旧槽。
4. 在 Feature 150/151/152/153 T153-01/T153-02 的显式 bundle、native `CandidateDraft`、
   authority-bound plan、journal 与 zero-write preflight 结果之上，单独定义外部 bundle
   admission transaction、archive publication、delivery 和
   launcher 边界，使 OpenEvolve/Shinka 输出进入同一完整源码路径，再用独立登记的小规模
   任务验证当前模型和真实 producer 效果。该准备能力本身不产生效果或 parity 结论。

Feature 108 的快照明确是评测时观察：107 completion 仍不包含执行退出时输出。inspect
可以在原 workspace 改动后复验保留快照；它检查本地一致性。Feature 109 的 archive 登记
还复验完整源码、执行与 evaluator 关联，交付使用已评分的保留输出快照，不重跑选中候选。
远端调度、通用 repository/workflow 和训练系统仍为后置扩展。

## 真实效果证据

- [069 普通/分阶段测量](history-archive.md)：普通流程
  GLM-5.2 的两例均有效，钣金 `0.999999`、邮政 `1.0185`。每例仅一次，产品源码固定
  `80f5af1`；它证明这两个任务上的交付能力，不是当前 HEAD 的效果或整体 parity。
- [082 分阶段测量](history-archive.md)：两例均通过
  Master 计划并进入 Build，最终有效 `0/2`，没有完成的 subject/harness 回执。后续基础
  设施修复不能代替新的真实验收。
- [113 当前版本验收](history-archive.md)：`c977eb4`
  的两例 GLM-5.2 自动多文件入口均在合同编译失败，有效 **0/2**，质量 null，已知用量
  15958 tokens。没有进入 evaluator/候选生成，不构成这些后续阶段的效果证据。
- [115 修复后验收](history-archive.md)：`5e2568f`
  完成 0/2，一例合同编译成功后 evaluator 请求超时，另一例合同请求超时。已知用量小计
  8625 tokens，超时消费未知；没有交付或可审计的冻结 evaluator。
- [117 延长时限验收](history-archive.md)：`9a26a73`
  完成 0/2，evaluator 请求在 600 秒超时，另一题合同原始响应含 Markdown 代码块而被
  拒绝。三请求、两响应，已知用量小计 11309 tokens，超时消费未知；没有 evaluator/交付。
- [131 同任务复查](history-archive.md)：`c730483`
  完成0/1；合同在25.237秒HTTP200返回并通过验证，evaluator compiler在等待响应头时于
  600.004秒超时。仅首请求3656tokens已知，总用量null；没有evaluator、候选、交付或
  holdout。封装失败未复现不构成130的因果证据，也没有当前版本真实多文件闭环成功。
- [134 新预算验收](history-archive.md)：固定产品
  `15710bd`，登记`358f738`先推送。准备1/1、8/8holdout，完整交付/联合仍0/1，quality/gap
  null。11次请求均HTTP200，完整98714tokens，费用未知；896.396秒、native/process exit1、
  清理通过。三次生成均触及登记工具预算，evaluated/valid candidates为0，尚无候选执行或
  交付。两项准备请求均低于旧600秒时限，不证明预算增加造成了准备成功。
- Feature 084–112 的融合与证据工作主要由本地 fixture 验证。尚无当前多文件链路或真实
  OpenEvolve/Shinka 搜索带来的增益结论。

普通任务交付继续作为默认使用路径；分阶段编排和演化的稳定性、收益分别验证。

## 最终应交付的系统

一个独立、本地、可由用户或其他 Agent 调用的算法任务系统。用户给出目标、数据和预算，
默认普通求解，按需启动本地演化；原生 population 与外部 producer 共用候选执行、独立
评分、receipt、archive、恢复和交付流程。单文件和多文件候选都能交付可重现代码、结构化
输出、独立评测报告、来源及预算记录，失败和未知状态也能解释与复验。

```text
目标 / 数据 / 预算
        ↓
普通求解；按需启用原生 population 或外部 producer
        ↓
单文件 / 多文件候选 → 有界执行 → 输出绑定与独立 exact evaluator
                                      ↓
                                receipt / archive
                                      ↓
                          下一代选择或最终可验证交付
```

预算、取消、持久状态和恢复贯穿全链路。每次发布明确支持范围，再要求对应里程碑的实现与
验收通过；未纳入的外部 producer 不阻塞原生前台版本。使用者无需理解底层 digest、inode
或逐条组装执行流程。

远端服务/GPU、DGM repository 候选、ADAS/EvoAgentX workflow graph、训练/RL 候选和更多
算法移植是后续可选扩展，不是这一版本完成的前提。本地 bounded runner 仍不是通用沙箱；
依赖/环境真实性及更强资源隔离需在扩大运行范围前按实际需求处理。
