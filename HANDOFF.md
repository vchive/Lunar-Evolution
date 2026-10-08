# Lunar Evolution 交接记录

## 2026-10-08 Linux native IPC control SDD

PR14 head2409206/run37703503332已完成三版14阶段原证据及root独立复核，合入main为
697e73e0b8f8cdd10b9922f3d60390ab6f53dbfc，tree2648f8c与tested source一致。
Python3.12 archived原2294项有1项已知历史measurement线程失败；按既有有限规则完整
retry一次2294/0failure，原失败与retry均保留，不能称全程无retry。main13 postmerge
run37704101297也独立完成三版首轮13阶段，0failure/error/retry。

PR15两轮首次失败均保留：e48ac34/run37707855913为1个monkeypatch fixture setup错误；
4974538/run37708266284前十个native阶段通过，trusted adapters的2个observer仍捕获旧v1
入口而失败，实际target正常exit0。fbd982e/tree486ea847更新到实际平台control观察点，
保留精确read grants/no-directory/host-file拒绝/argv不变断言，本地16项通过；新的完整
run37709205439仍待最终核验。本节不把失败run或Darwinskip升级为Linux通过。

Feature182独立codex/native-ipc-egress在该修复tree上增加Linux default/formal selector
native-bootstrap-linux-ipc-control-v1。旧拒绝顺序保留，grant-only在budget/input/nonce/
spawn前固定ipc_control_required。真实C header拒绝SysV shared memory/message queue/
semaphore全family、i386ipc/time64和遗漏的sendmmsg/recvmsg/recvmmsg；intersecting filter
只允许精确full-domain AF_UNIX socketpair。ABI literal原表独立核对覆盖x64/ARM64/i386，
只有实际native CI执行才是平台验收。v2 held grants、FD closure、subreaper/drain、original
lifeline/deadline/registration/handoff/broker/receipt/publication schema均不变。

新增private0600 IPC parent-owned baseline/filtered/v2 sealed native negatives，SCM_RIGHTS
传入传出direct-header fixture、普通pipe/file/socketpair/fork/thread及broker/FDclosure
positives。专门ipc-control XML纳入三版原始保存。当前本地Darwin结果及final Linux CI以
specs/182-native-ipc-control/validation.md和本轮PR/ignoredreports为准；独立review与exact
head CI/merge仍待完成，不借PR15/其他head结果。

此slice只关闭已识别SysV/ancillary路径，不是完整egress/information-flow证明。P0仍有
POSIXmq/其他kernel routes、broker有效redirect/proxy目的地及bootstrap death/pause后独立
停止。P1 immutable runtime/load、archive/loader/import completeness、versioned delivery、
实际Python pipe fixture、真实OpenEvolve/Shinka adapters与生产RSI CLI仍开放。P2多机
ownership/服务化/分布式scheduler后置。只用local inert/C/fixture/provider-free和既有CI；
不读.env/密钥，不跑模型、WebAgent、远程/公司evaluator或真实campaign，保留他人修改。

## 2026-10-08 Original native grant integration SDD

PR13已合入main7172885d56d18cd310d6c5152baee71c62d6a7a3，tested source c660609、
tree1d8ca3f68e643d3e048d54d53288e70fe9d5e7cd；三版十三阶段39raw XML/日志及actual
merge parents/tree两次独立复核通过。PR12 postmerge37698866147也独立通过。PR14
Feature180 held-owner exact2409206/run37703503332完整三版CI仍推进，未追认为合入；
实际后续状态以PR及ignored reports为准。

独立codex/native-grant-objects从Feature180 exacthead延续Feature181全链路。新Linux
formal/default descriptor native-bootstrap-linux-grant-objects-v1，旧fd-control在budget/
input/nonce/spawn前拒绝，其余旧拒绝顺序不变。Host首次work/output acquisition持有
至cleanup/receipt/capture结束；仅held batch下创建missing writable组件，original input
manifest workspace/batch/input parents期待值不增加grants。原config/request/memory
bytes/mode0400/nlink1/size/time/hash由held-parent temporaryreader复验，不刷新pins。

有界privatecontrolv2只继承leaf FDs，C独立检查完整originalgraph/role/identity与static/
dynamicFD分离，Landlock用原FD、CWD用fchdir，child两阶段清理grant/temporary/extras，
保留既有seccomp/inputmutation/lifeline/deadline/subreaper/drain。v1直接fixture、Darwin与
historical只读load/recovery scope保持；原nonce/deadline/registration/handoff/receipt/
broker/publication schemas不变。observed ancestor object与read/write冲突独立拒绝；不
声明任意unobserved bindmount alias完整性、namespace/content freeze或atomic mkdir+FD。

本地验证、独立审查及初次失败材料列于specs181/validation.md；Linux真实执行必须由本轮
finalhead Ubuntu三版CI证明，不把Darwin skips、前PR通过或read-only DTO当enforcement。
Final source CI/merge仍开放。完整egress、bootstrapdeath/pause后的独立停止仍是P0；P1
immutable runtime/loader/archive/import/versioned delivery、nativePythonpipe与真实
OpenEvolve/Shinka Pythonadapters/productionRSICLI仍开放；P2多机服务/ownership后置。
只用local inert/provider-free C/filesystem/pipe/loopback及既有GitHubCI，不读.env/密钥，
不运行模型、WebAgent、远程/公司evaluator或真实campaign，保留他人修改。

## 2026-10-08 Held producer grant anchors SDD

PR12已合入main：head3016339、merge3b9d7583eda707f8e620fcc09637211570f5fd93，
tree d6b6f8653ba9d0607b80a292b6148c735a98db5e。完整三版十二阶段首轮通过、raw XML/
日志及actual tested merge parents/tree两项独立核验。PR11中间postmerge run37697722824
被main推进取消，材料保留且未追认为通过。PR13 source c660609三版native专项通过，
完整run37698559519及raw审计仍推进；实际merge与后续postmerge状态以PR/ignoredreports为准。

独立 codex/native-grant-anchors 从PR13 exacthead延续Feature180，仅新增host held-grant
owner API，不修改C/control/formal selectors/attempt/recovery。原始root/祖先/leaf descriptors
保留至context退出，no-follow parent-relative links与dev/inode/kind复验，不刷新原期望。
protected-file必须带original identity并保持nlink1；read-only directory与write subtree两向
overlap、不同路径同对象alias、role/expected冲突拒绝。合法write+CWD合并成一个anchor。
资源/DTO有界，borrowedFD误关闭/不同对象复用拒绝且cleanup不误关unrelatedFD。partialopen/
success/error退出清理保持原bodyexception；detachedmanifest scope仅host-held-grant-anchors，
execution_enforced=false，无FDnumbers，不转化为launch/recovery/publication权。

focused95项全部通过（原89项已包含，不相加）；旧policy5cases为4passed/1platformskip。
Ruff/compileall/diff、workflowXML接线、693exports通过；独立review及另95项复核通过（有
重叠不相加）；文档收窄为dev/inode/type不同的FD复用才检测/不误关，same-objectreopen/
FDgeneration不在borrow契约内，OScleanupfailure保持拒绝/besteffort。finalhead三版CI/
merge待完成。只用local inert filesystem，不执行producer。本轮不是Linux grant enforcement。

P0 grant对象绑定仍需完整后续接线：work/output首次创建/检查即held、原inputmanifest
期望/bytes验证、privatecontrolv2+parentbindings/C reservedFD校验、Landlock原FD、heldcwd、
exec前两阶段FD清理及新formalcapabilitygate。不得只接host然后保留C pathreopen，却宣布P0
关闭。完整egress、bootstrapdeath/pause独立停止仍开放；P1 immutable runtime/loader/
archive/import/versioneddelivery、nativePythonpipe、真实adapters/productionRSICLI仍开放。
P2多机ownership/服务化/分布式调度后置。不读.env/密钥，不运行模型、WebAgent、远程/
公司evaluator或真实campaign，保留他人修改。下方pending文字保留为历史提交时状态。

## 2026-10-08 Linux target descriptor-control SDD

PR10 postmerge main run37691786270已全三版首轮通过；独立raw九阶段XML、日志摘要/SHA、
case/skip inventory与actualcheckout e17608eb/tree83e86e8两次复核通过，无重试。
PR11 exacthead e56140a/run37691648336三版十一阶段全部首轮通过，两次原始独立审计，无
failure/error/retry；合入main为db5f17113265cf7b9b174bbc516d9b303438215a，tree5ff1b113
与testedsource一致。PR12 exacthead3016339/run37694796475三版checks全success，原始
完整审计/merge仍推进；本节不会把前一PR证据追认为后一PR通过。

独立 `codex/native-fd-control` 从PR12 exacthead延续Feature179。新增Linux default/formal
selector native-bootstrap-linux-fd-control-v1；旧fd-handoff-only在budget/input/nonce/spawn前
固定fd_control_required，其余旧拒绝顺序不变。historical load/recovery保持原readonlyscope。
原control/frame/subreaper/guardian/deadline/broker/receipt/publication协议保持不变。

真实header增加intersecting fcntl/fcntl64 command allowlist与ioctl request allowlist：允许
dup/inheritance/status/nonasync SETFL、POSIX/largefile/OFD locks及GETLEASE/GETPIPE_SZ/
GET_SEALS；只允许FIONREAD/FIONBIO/FIOCLEX/FIONCLEX ioctl。拒绝O_ASYNC、ownership/
notification/lease/seal/resize及unknowncontrol，检查完整request/command/SETFLflags高位。
本地private blockedSIGIOreceiver/anonymouspipe基线、filteredroute、普通IO/locks与sealed
native brokercomposition已写入Linuxtests，Ubuntu实际执行仍待finalheadCI，不把Darwinskip
当Linux证据。支持的i386路径需额外原生验收，x64CI明确skip相关cases。

本地Darwincomposition147cases=82passed/65skips/0failure/error；其中新58cases均skip，
其余7为原有Linuxcase。补强后的finalgates94cases=36passed/58skips，全部0failure/error。
review补齐i386flags64负测、FIONBIO不能armasync、实际filter下sealedGET_SEALS以及异常
路径的私有未reap后代清理；成功reap不盲目signal旧PID/PGID。Ruff/compileall/diff通过。
初次collection因pytest reservedrequest
变量失败的XML保留/tmp/lunar179-first-local.xml，已改名后验证；suite之间有重叠不能相加。
独立review已通过；完整finalhead三版CI与mainmerge仍待完成，以实际PR/ignoredreport为准。

P0仍开放grant-object/path/inode/overlap、完整egress与bootstrap death/pause后的独立停止。
P1仍为immutable runtime/load protection、archive/loader/import completeness、versioned
delivery、Python pipe fixture、实际OpenEvolve/Shinka adapter与生产RSI CLI。P2多机服务后置。
只用本地inert/provider-freefixtures与既有GitHubCI，不读.env/密钥，不运行真实模型、
WebAgent、远程/公司evaluator或真实campaign，保留他人修改。

## 2026-10-08 Linux native target FD handoff SDD

PR #10 已合入 main：head1d87ba685327a585ea02b6b25f6bfe6cb2891d37，merge
`e17608eb35efea408d78134f44ac197ac632956b`，tree83e86e8683888cb4eea15aecb40f50eaae57a274。
最终run37685452481三版九阶段全部通过、无重试；各版current10521/32skip，完整原始XML/
日志与tested merge parents/tree经独立复核。main postmerge run37691786270仍单独审计。

PR #11 继承该exact175，最终修复head `e56140a8156ad1b463f3ff0c5cf1cc5a19e24f05`，
tree5ff1b1138ec683d20348153172b78f84e9afab3e；run37691648336完整三版CI/merge待核验。
初始000d540/run37690178144由实际scalar/aggregate验证work-budget修复取代，保留原始
证据，不追认为最终head成功。新177+旧171专项361passed/0skip/failure/error，独立复核同样361。

独立 `codex/native-fd-handoff` 从PR11 exacthead延续Feature178。新Linux default/formal
selector为native-bootstrap-linux-fd-handoff-v1，旧版本在budget/input/nonce/spawn前拒绝，
旧load/recovery保持原scope。子进程有限close_range keep集至UINT_MAX，不用RLIMIT/proc census，
保留hoststdio、必要targetFD及broker双端；exec-error writer checked CLOEXEC。保留sealed
shebang targetFD继承语义。broker以strictnumbers/reserved/FIFO/PIPEFS/direction/O_PATH/
distinctinode拒绝错误端点；fresh来源仍属于既有trustedhost，不升级外部来源认证。
新受控拒绝明确报告error及Linux target_start_failed，Darwin保留原negativeframe顺序。
guardian/deadline/drain/control/frame/receipt/publication协议不变，历史证据不升级。

本地Darwin lifecycle等195cases为92passed/103skip，最终75Linux FDcases全部skip；修正旧
9个fault覆盖后的84cases为5passed/79skip。原scheduler/broker/OpenEvolve/nativefailure/
RSIgateway/controller组合153passed/0skip/failure/error；Ruff/compileall/diff、YAML与684
exports通过。独立审查关闭highFD未真正lowerRLIMIT、旧stdioFD提前拦截原fault路径两项
夹具问题；首轮编译与Darwinframe expectation失败原XML仍保留。各suite有重叠不能相加。
Linux真实enforcement及本轮finalhead三版完整CI/merge仍需独立核验，不能借PR10/11结果。

P0仍开放grant-object/path/inode/overlap、allowedFD/ioctl/完整egress及bootstrap death/pause后
独立停止监督。P1仍为immutable runtime/load protection、archive/loader/import completeness、
versioned delivery、Python inheritedpipefixture、实际OpenEvolve/Shinka adapters和生产RSI CLI。
P2多机ownership/服务化/分布式调度后置。继续只用local inert/C/filesystem/pipe/loopback/
provider-free tests及既有GitHub CI，不读.env/密钥，不运行模型、WebAgent、远程/公司evaluator
或真实campaign，保留他人修改。实际merge状态读取各PR与ignored report。

## 2026-10-08 Native input mutation and closed runtime tree SDD

独立分支 `codex/native-runtime-closure` 从 Feature175 exact head `1d87ba6` 延续两项
互不扩权的切片；Feature175 最终 CI/merge 状态以 PR #10 原始 checks 与 merge 记录为准。

Feature176 新 Linux build/formal attempt 使用 `native-bootstrap-linux-input-mutation-v1`，
旧 subreaper descriptor 在预算/nonce/spawn 前拒绝；旧只读 load/recovery 保留原 scope。
原 child-supervision/control/guardian 协议不变。C boundary 实际查询 Landlock ABI>=3，
保留 REFER/TRUNCATE 常量与 write-dir TRUNCATE，bound read 启用全进程 ownership/time/
xattr/chmod deny，包括新 xattr-at、旧 i386/time64 入口。正常 work/output create/read/
write/truncate 继续允许，bound input 存在时 output metadata mutation 也拒绝。
本地 Darwin expanded focus81 passed/211 skips；新增150项均 Linux skip，不能当执行证据。

Feature177 新独立 closed-tree build/parse/verify API 绑定原 declared manifest、target 和
独立 tree SHA，有限 no-follow 目录扫描包括所有文件、目录与 empty membership，首尾 bytes/
stat/成员复验，拒绝未声明文件、link/special/alias、drift 和超限。Feature171 v1 wire 与原
unlisted-file 行为不变。序列化前 strict tuple/count/nested DTO 检查拒绝被改写对象的自定义
迭代/len/index；原 v1 ancestor pins 也有独立边界。DTO、embedded wire 与 caller target 的
scalar 长度在 Path/encode/enum validation 前检查，累计 child edges 在成员遍历前限8192。
新151+旧210 inert inventory tests 共361通过，无skip/failure/error；原 native/strategy/RSI
组合73项通过。各 suite 有重叠，不相加。
scope 仅 `closed-filesystem-layout`，execution/load protection/archive/loader completeness
均 false；不增加 read grants、不执行 Python、不产生 launch/admission authority。

共享 exports 与 CI 原始 XML 已接线。本轮最终 head 仍需独立三版完整 CI 后按既有授权
合入 main；源文档 pending 为提交时状态，后续实际状态读取该 PR 与 ignored report。
完整 FD/grant-object/ioctl/egress 闭包、bootstrap death/pause 后独立停止仍是 P0；P1 下一步
为真实 load protection、versioned delivery、Python inherited-pipe fixture、真实 OpenEvolve/
Shinka adapters 和 RSI CLI 生产 solver。P2 多机 ownership/服务化/分布式调度仍后置。
只用本地 inert/C/fixture/provider-free tests 和既有 GitHub CI，不运行模型、WebAgent、远程/
公司 evaluator 或真实 campaign，不读取/修改 `.env` 与密钥，保留他人修改。

## 2026-10-08 PR #9 merged; known native failure settlement SDD

PR #9 已合入 main：head `acfa5bc7e8c3890efa928588460be27529e2fe00`，merge
`4fa526c3b2adedb85231bc178ede32e26c505306`。最终 CI `37678220566` 三版全部通过、无重试。
各版 descendants47/1skip、deadline358/1skip、runtime240/1skip、adapters173、native403/
6skips、current10364/32skips、archive2294、frozen24，均0failure/error。原始XML、日志摘要/
SHA与跨版inventory独立核对；Actions PR merge `eaa2f663` 与head、实际main的tree一致。
首轮8个夹具编译失败仍保留，不追认为成功。PR8 postmerge main run37675779160也独立
完成三版七阶段首轮通过。下方历史pending状态已被这些记录取代。

当前独立分支 `codex/native-known-failure` 从该main实现Feature175：正式原生nonzero/
cancelled终态重新读原consumption-v2 deadline/registration/handoff/cleanup/stream和原broker
byte/inode pins后返回distinct process-only failure；success-only入口默认行为不变。
显式同ledger failure wiring持久化独立canonical create-only failure provenance，冻结原
publishingFD digest与完整started claim(created_at)。gateway映射failed/cancelled、强制只读
reader重放，提供inspect/restore；controller以原fingerprints、historical memory、checkpoint/
episode CAS和单次evidence budget reservation登记；写入前复验controller CAS及SQLite事务内原完整claim，四种crash gap不重launch、不刷新deadline。

本地最终五模块157项及已有claim5项全部通过（合成162项）（包括真实C exit7、host accepted-start取消、DRS/BRS及crash/
drift/CAS负测），原成功与已有controller/scheduler/producer组合179项通过，Ruff/compileall/
diff通过。独立审查已关闭persist-return原digest丢失、checkpoint身份与callback CAS窗口。
本分支最终完整三版CI与merge尚待独立完成，不能借PR9结果关闭Feature175。

缺终态unknown、terminal后首次failure provenance前丢失原broker pin的attempt仍quarantine；
不推断abandoned/timed_out，不覆盖immutable unknown，不授予新execute/signal/publication/
memory权。当前process terminal仍v1，v2要求属于带原deadline anchor的consumption。
下一P0仍为完整本地filesystem/FD/egress闭包和bootstrap death/pause后的独立停止监督。
P1 sealed Python/import inventory、versioned delivery、本地Python pipe broker、真实项目
adapters和RSI CLI生产solver仍开放；P2多机ownership/服务化/分布式调度后置。
只用本地inert/C/bootstrap/fixture/provider-free tests和既有GitHub CI，不访问模型、WebAgent、
远程/公司evaluator、真实campaign或.env/密钥，保留他人修改。

## 2026-10-08 PR #8 merged; Linux descendants drain SDD

PR #8 已合入 main：tested head `f870cb95c10825e49129e50629731adb3a773595`，merge
`d3f4fbf0ae531d3299ae6736382867d60fee1cc4`。最终 run `37669528518` 的 Ubuntu
Python3.11/3.12/3.13 七阶段全部首轮通过、无重试：各版 deadline358/1skip、runtime240/
1skip、adapters173、native403/6skips、current10317/31skips、archive2294、frozen24，均
0failure/error。原始XML独立核验，main tree等于tested tree。postmerge main run
`37675779160` 在本次更新时仍运行，不能冒称通过；下方Feature173 pending为历史状态。

当前从该tested tree在独立worktree延续 `codex/native-descendants-drain` / Feature174：
Linux bootstrap 在target fork前verify subreaper与waitable SIGCHLD，direct child退出后保留
原guardian，使用 `waitpid(-1, __WALL | WNOHANG)` 回收直到ECHILD，仍受原lifeline及absolute
deadline约束。新默认Linuxdescriptor与正式 `--child-supervision linux-subreaper-v1` 明确
绑定；旧Linuxdescriptor在预算持久化/nonce/spawn前拒绝，但旧只读recovery仍保留原scope。
所有新Linuxbinary fixture入口同样自然drain，缺guardian时不声称bounded监督。

v1控制/帧/process_only terminal不扩authority，不从generic passed/EOF或descriptoralone
追认tree-drain。common terminal-write与guardian join-tail复验也加固Darwin收尾，但Darwin
没有subreaper/drain能力。bootstrap自身终止/暂停（包括cleanup SIGTERM、SIGKILL/SIGSTOP）、
完整containment/egress仍开放。
本轮focused/static和实际Linux final-headCI/merge分别记录在Feature174 validation；本地
Darwin skip不能证明Linux执行。不要把PR8证据追认为Feature174通过。

下一P0为可信failed/cancelled settlement bridge与完整containment；abandoned处置需独立
协议，不能从unknown/清理成功合成失败。P1仍为sealed Python runtime/import inventory、
versioned runtime delivery、Python inherited-pipe broker fixture、真实OpenEvolve/Shinka
adapters和RSI CLI生产solver。P2多机ownership/服务化/分布式调度继续后置。

只用本地inert/C/bootstrap/fixture/loopback/provider-free evaluator，不运行模型、WebAgent、
远程/公司evaluator或真实campaign，不读取/修改.env与密钥。并行改动不得覆盖他人工作。

## 2026-10-08 PR #7 merged; original deadline anchor SDD

PR #7 已合入 main：tested head `16fb8ac0b0f00233a8aee60208fc5a9ba767b966`，merge
`009691a13d2fd99ee141659216f1e7f13eaff63b`。最终 CI `37660700817` Ubuntu3.11/3.12/3.13
全部首轮通过、无重试；各版 runtime240/1 skip、trusted173、native403/6 skips、current10108/
31 skips、archive2294、frozen24 均0 failure/error。原始XML独立核对，合入后的main tree与
tested head一致。Feature171/172 对各自限定范围完成，不能追认为完整runtime或containment。

当前从该main延续 `codex/native-deadline-anchor` / Feature173：同一publishing FD持有到
create-only deadline fsync与original bytes/inode/stat指纹冻结；native consumption v2两份
claim保存原deadline binding，并沿原registration/handoff digest链传递。正式gate、cleanup/
evidence/terminal/output与只读recovery复验；missing-terminal explicit cleanup每个signal前
复验，继续使用原absolute deadline。v2 recovery receipt仍为unknown，不重启、不重评、不发布
候选。旧v1 complete terminal保留只读边界；旧v1 unknown不得获得新清理authority。

本轮规格、代码和测试验证见 specs/173-native-deadline-anchor/。本分支独立完整CI/merge
尚需完成；PR7证据不代表Feature173通过。部分发表证据保留，不能补claim或重建预算。
未更改C control/guardian协议、候选admission/commit或read grants。

下一P0仍为post-direct-target descendants监督、完整containment/egress、可信failure/
abandoned settlement bridge。P1仍为sealed Python runtime与完整import inventory、versioned
native runtime binding、Python inherited-pipe broker fixture、实际OpenEvolve/Shinka adapters
及RSI CLI生产solver。P2多机ownership/服务化/分布式调度继续后置。

只运行本地inert/C/bootstrap/fixture/loopback/provider-free evaluator，不运行真实模型、
WebAgent、远程/公司evaluator或真实campaign，不读取或修改.env/密钥。

## 2026-10-08 PR #6 merged; runtime inventory and Linux target control

PR #6 已合入 main：tested head `25035895751061abce6d0c1a166363e29704cd79`，merge commit
`b3b2f132c2843cddf93f347e01182bba92bc714a`。最终 run `37651610902` 的 Ubuntu3.11/3.12/3.13
完整 current 各9868项/0 failure/error/30 skips，frozen24、trusted173、native403/6 skips通过。
archived2294 在3.12/3.13首轮通过；3.11仅已知 preparation-ceiling 调度节点失败，按原严格
规则完整重试一次通过，首次XML保留；current没有重试。下方PR6待CI文字保留为历史。

新分支 `codex/local-runtime-preflight` 从该main延续两项SDD：Feature171独立declared-file
Python runtime inventory/preflight；Feature172收窄Linux target的session/group/namespace/
signal/process-memory/io_uring及alternate syscall入口。两者分别有focused测试与明确边界；
本地inventory210 passed；联合runtime/native/strategy385项为351 passed/34 Darwin skips，
最终Linux-only收窄增加queued-signals/pidfd_getfd后，control/architecture专项1 passed/29 skips。
Ruff/compileall/diff、公开exports和文档syntax通过；该1项执行真实unsupported-ABI分支，
不代表Linuxseccomp执行。最终head完整CI及merge须另行核验，不能借用PR6证据。

Runtime target ABI和launcher政策仅声明；库存不枚举未列imports、不seal writablefiles，
不授予native read paths、不改RSI/producer markers、不执行Python项目。Linux deny-list
不等于完整containment/egress，也不修复bootstrap退休后descendants监督。
P0另确认missing-terminal unknown恢复仍需原deadline bytes/digest/inode独立anchor；可信
failure/abandoned settlement需独立证据bridge，不从缺回执合成成功或重试。
后续P1：完整immutable runtime/import inventory、versioned launch binding、本地Python
pipebroker fixture、实际OpenEvolve/Shinka adapters与RSI CLI生产接线。P2多机服务后置。

继续只用本地inert文件/C/bootstrap/fixture/loopback/provider-free evaluator，不运行真实
模型、WebAgent、远程/公司evaluator或真实campaign，不读取或修改.env/密钥。

## 2026-10-07 PR #5 merged; OpenEvolve trusted local composition

PR #5 已合入 `main`：tested head `221540ffaca41cedf284011a5c860f09b52fa4a5`，
merge commit `83e1f4b50f2aaa0981d19d77342cf363faeaee44`。PR 完整三版 Ubuntu CI
run `37635168343` 均成功。main post-merge run `37641635284` 最近核对 3.11/3.13
成功，3.12 仍运行，尚未确认整轮完成。下方旧分支“待 CI/合入”文字保留为历史。

本轮 `codex/openevolve-trusted-launch` 延续 SDD Feature160/169，新增切片 Feature170。
现有 `OpenEvolveStrategy` 已接入显式 process-local `trusted_native_execution`，默认 legacy
配置 JSON 不变。冻结完整 config/contract bytes/inode，并由原 intent/attestation/bootstrap
绑定；native attempt/receipt/recovery 均复验精确只读路径。RSI 与 producer-input marker
本轮互斥，未扩大 RSI read grants。

实际链路为 companion `.producer-runs/openevolve/` create-only claim → 正式 native lifecycle
与 broker → 唯一单文件 generic envelope → 一次独立本地 exact seed admission → 原 atomic
OpenEvolve seed commit → completion ack。native execution 与 generic seed dependency/env
分别保存，外部分数只作 provenance。完成后直接校验 retained local receipt 与全套发布证据，
不重新评测。started/unknown/缺 ack 不重启、不刷新预算、不重评、不重提交；移除 injection
也不能降级 legacy Popen。原总预算保守映射，父预算收窄；active owner loss/cancel/timeout
清理原 worker。发布前 callback 漂移拒绝，commit critical region 保留既成成功。

本地联合 focused 568 passed；最终 integration 198 passed，constructor/legacy 联合272 passed
（包含最终 strategy 44项、预算/发布修正与 seed recovery 拒绝），均无
skip/failure/error，详细 JUnit 和模块验证见 Feature170 validation。Ruff/compileall/diff
检查通过；此源提交时新 head 仍需完整 CI 后按既有授权合入，之后实际 CI/合并状态以该 PR
checks 与 merge 记录为准。不能追认 PR #5 CI 为本轮通过。

下一缺口仍是实际 Python OpenEvolve/Shinka 的 interpreter/loader/stdlib/packages/source/
resources trust inventory、SDK broker 接线与生产 adapter；RSI CLI 仍仅 fixture choices。
本轮 C fixture 证明 strategy 组合，不代表真实 Python 项目或 campaign 可用。
P0 完整 containment/egress、bootstrap 后 descendants 与可信 unknown settlement 仍开放。
P2 多机 ownership/微服务/分布式调度后置。

仍只运行本地 C/bootstrap、fixture/loopback/provider-free evaluator；不运行真实模型、
WebAgent、远程/公司 evaluator 或真实 campaign，不读取或修改 `.env`/密钥。

PR #6（Feature170）首 head `bb1a4b3` CI run `37647462556` 的 Python3.13 完整 current
保留9867项/1 failure/30 skips：已有 ownership 测试 `select.select` 遇到FD>=1024，触发
FD_SETSIZE ValueError。新增173项、原native403项、archive2294和frozen24均无failure。
current 没有整轮重试。read-only 审查表明新测试执行顺序在该节点之后、focused/current独立
进程、新模块导入无FD增长；目前不支持把此失效归因于新接线泄漏。
readiness 改为 DefaultSelector，保留10s与所有实际lock交接断言，额外真实高FD stdout验证。
纠正后ownership+native联合80 passed，静态检查通过；新 head 仍须完整独立矩阵后合入。

## 2026-10-07 Worker terminal authority and regression evidence

PR #4 已合入 `main`，merge commit `2b8d05e9eaec7a944be8caa4e20e3e5210547ff7`。
该 PR Ubuntu Python 3.11/3.12/3.13 完整 CI（run `37297809715`）和 main 合入后
CI（run `37302911373`）均通过。下方日期更早的未合入/未授权描述是历史记录。

当前 `codex/worker-terminal-evidence` 从该 main 开发两个纠正切片：

- 统一 worker verifier 原先把 bootstrap handshake `passed` 当 completed，证据不充分。
  现在必须独立核验 native process terminal、原始 deadline 和 cleanup sidecar，严格
  绑定 registration/owner/task/launch/digest；cleanup `alive_after` 必须 false。正常 exit0
  才 completed，nonzero/cancelled 为 failed，握手通过但缺终态/预算/清理仍 unknown。
  纯 record 校验复用到真实 native recovery；recovery 继续检查 current boot、文件、
  RSI inputs 和 stream sidecar。process-only classification 不授予发布或 learning 权限。
- current suite 不再整轮失败重试。immutable archive 只允许 exact known scheduling node
  在完整 2294 项、仅一个 failure、无 error/skip 时重试一次；首次 XML 不覆盖，第二份
  独立 `archived.retry1.xml`，每次 exit/count/hash 保留并上传。普通 spawn fixture 使用
  现实启动预算，显式 0.05 秒 hard-timeout 测试和生产 deadline 不变。

本分支 focused/static 验证与完整 CI 状态见 Feature169 validation；新 head 尚须独立
通过完整 CI 后按既有用户授权合入。不要把 PR #4 的结果追认为本分支通过。

P1 下一实质缺口：现有 OpenEvolveStrategy 仍直接 Popen、Shinka 只有 retained-source
exporter、RSI CLI 的 solver choices 仍是 fixture。外部 project/runtime trust profile
目前是声明字段，没有 host interpreter/package/import inventory 验证，不能声称真实项目
来源认证/生产 campaign 接通。后续优先改现有 launcher 的显式 trusted 路径，先以本地 C
producer 证明 launch→receipt→admission→exact replay；Python runtime manifest 独立设计。
P2 多机 ownership/微服务/远程 evaluator 后置。

本轮只运行本地 C/bootstrap、fixture/loopback/provider-free tests，不运行 WebAgent、真实
模型、远程/公司 evaluator 或 OpenEvolve/Shinka campaign，不读取或修改 `.env`/密钥。

## 2026-10-02 Main merged; native original-deadline guard

PR #2 已合入 `main`，merge commit 为 `9e71d40944b3f083f6ae2f8ebec5f941194b0634`。
该最终 head 的 Ubuntu Python 3.11/3.12/3.13 完整 CI 全部成功（run `36976747523`），
本地完整发布回归为 **11,777 passed、17 skipped、0 failures/errors**。下方 PR #2
pre-merge/未合入描述是历史记录。

本轮从实际 `origin/main` 开启 `codex/native-deadline-guard`，延续 Feature 156/157。
正式 attempt 在 preflight/attestation 前，将已冻结 intent/parent/RSI deadline 一次保守映射
为 native absolute nanoseconds；bootstrap 和 broker 共用，不在 gate/接收/retry 时续预算。
Darwin 用 `mach_absolute_time` 整数 timebase，Linux 用 `CLOCK_MONOTONIC`。guardian 在
control read 前启动，管道异常/EOF 或到期时仅停止自己原 session/group；child 在 exec
前重查。控制器暂停但 writer 仍打开也不能延长运行。旧 runtime 拒绝新 formal argv；
不传 deadline 的旧接口仅供直接 fixture。缺少 durable terminal 仍是 unknown，只读恢复
不执行、不发信号、不改字节/inode，也不合成成功或取消回执。

联合 focused 回归 **252 项：243 passed、9 平台 skip、0 failures/errors**，JUnit
`/private/tmp/lunar-native-deadline-combined-20261002.xml`；新增 deadline 模块27项全部通过。
Ruff `src tests tools`、compileall 和 diff check 通过。完整发布回归和新 head 三版 CI
须独立完成后再合入；当前 focused 不能代替它们。

该监督仍只覆盖 bootstrap 存活期。direct target 退出后的 descendants 需独立退出/清理
握手；bootstrap 自身被暂停、恶意 signal/session/namespace、完整 egress、cross-boot
reconcile、外部项目 ownership/真实 campaign 仍开放。T156-05/06/09 和 T160-35 不整体关闭。
并行 P1 审查确认下一切片为 scheduler-backed receipt provider + 同次输入/launch/plan/
candidate/evaluation/publication provenance sidecar；每 episode 必须使用独立预绑定
intent/attestation/journal，不能将旧 `not_bound` retained evidence 追认为 RSI 请求成果。
controller 还需显式交付 approved memory 和稳定 gateway fingerprint，不能直接把双参数
facade 塞入现有单参数 `PracticeEpisodeRunner`。

本轮仅运行本地 C/bootstrap/fixture/loopback，不运行 WebAgent、远程 evaluator、公司平台、
真实模型或 OpenEvolve/Shinka campaign，也不读取或修改 `.env`/密钥。

## 2026-10-02 PR #2 gateway facade and pre-merge fixes

当前工作分支为 `codex/rsi-native-worker-recovery`。PR #2 已按用户“直至合入 main”的明确
授权转为 Ready for review；下方 Draft 和未授权说明是历史状态。`7ab62ed` CI 的三版测试
阶段通过，但 Static checks 因本次新增 `__init__.py` 导出顺序失败；`2c01189` 修复后 Ubuntu
Python 3.11/3.12/3.13 完整 CI 全部成功（run `36971547726`）。后续修改仍须以新 head 为准。

新增 `NativeRSISolverGateway` facade：显式注入纯只读 `plan_factory` 和受信
`receipt_provider`，组合 request/memory/plan 校验、native episode claim、唯一候选选择、
receipt 映射与 durable result publication。重复调用仍重建并校验 plan，但不再次调用
provider。合并前复查同时补齐 claim 并发窗口：竞争者的 started claim 阻止调用，竞争者
已发布的 terminal result 只读重放；`RSILearningError` 按其现有字符串契约处理。

固定代码的全部 RSI 回归 **1,179 passed、0 skipped/failures/errors**，JUnit
`/private/tmp/lunar-pr2-rsi-final.xml`；其中 gateway/claim 并发 focus 为17项。完整 Ruff
`src tests tools`、compileall 和 diff check 通过。新提交需重新通过三版 CI 后再合入。

这不是完整 native RSI E2E：facade 尚未直接调用 `run_native_trusted_producer`，未读取并证明
同一 plan/run/launch 的 native artifact provenance，也没有 controller、deadline/cancel
接线。T160-35 保持开放，不能将手造 receipt fixture 描述为真实 solver/campaign 验收。
P0 trusted lifecycle/完整 egress/外部 ownership 和 P2 官方 evaluator/真实 campaign/计费
计量仍按原规格继续。本轮继续仅使用本地 fixture，不访问真实模型、远程 evaluator 或密钥。

## 2026-10-02 Native RSI composition seams

按用户授权继续推进 PR #2，当前 head 为 `3af6f89`，仍未合入 `main`。本轮完成并推送三项
provider-free composition seam：

- `NativeRSIExecutionPlan`：冻结完整 `SolverRequest`/memory digest、launch/attestation/
  bootstrap/input manifest、selector/evaluator fingerprints 和原始 deadline，支持严格
  canonical replay 与 drift refusal。
- `RSILedger` native episode claim：attestation 前 create-only claim，绑定 episode/request/
  plan digest；started 或 unknown 只进入 recovery，绝不二次 launch；完整 terminal result
  可幂等发布和只读恢复。
- `rsi_native_candidate`：校验 request/contract/evaluator/environment/memory 全部 pins，只选
  一个 admitted candidate；execution completed、独立 evaluation pass、publication published
  三类证据全部匹配后才构造 `SolverResult`。

联合本地回归 **229 项，220 passed、9 平台 skip、0 failures/errors**，JUnit
`/private/tmp/lunar-native-p1-final-20261002.xml`；Ruff、compileall、`git diff main --check`
通过。当前仍未把这些 seam 接到真实 native scheduler：完整 `NativeRSISolverGateway.run`、
真实 candidate/evaluator receipt 读取、controller resume/reconcile、完整 egress 和外部
worker ownership 仍开放。PR #2 新 head 的 Ubuntu Python 3.11/3.12/3.13 CI 必须独立通过后
才能合入；本地 fixture 结果不代表真实模型或 campaign 验收。

## 2026-10-02 Native controller lifeline and RSI launch-input binding

继续在 `codex/rsi-native-worker-recovery` 推进 Feature 157/160。本轮完成两个本地安全边界：

- 正式 native attempt 给 trusted bootstrap 一个匿名 controller lifeline。控制器异常死亡时，
  guardian 只停止自己仍持有的原始 session/process group；target 不继承 lifeline。live
  owner-checked cleanup 期间 writer 保持打开。缺失 terminal 仍为 `unknown`/
  `recovery_required`，不会合成成功或取消回执。
- RSI launch 在消费 attestation 前绑定完整 canonical `SolverRequest` 和 approved frozen
  `MemorySnapshot`，并绑定 manifest、原始 intent/attestation/bootstrap 与文件 inode/hash。
  输入仅以两个精确只读路径交给 native target，gate 释放和 receipt/recovery 前重验；原始
  `deadline_unix` 只映射一次并收窄 native attempt。Linux 对有只读输入的 profile 同时拒绝
  chmod 系统调用，避免 target 改写输入权限。
- provider-free 合并回归 14 个模块：**280 项，271 passed、9 平台 skip、0 failures/errors**，
  JUnit `/private/tmp/lunar-input-lifeline-final-20261002.xml`。Ruff、compileall、
  `git diff main --check` 通过。回归使用本地 C/bootstrap、fixture 和 loopback；没有调用
  WebAgent、远程 evaluator、公司平台或真实模型。

这不是可发布的 native RSI SolverGateway：episode claim、native receipt 到 `SolverResult` 的
可信映射、独立 verifier/evaluator 结果、controller resume/reconcile 仍未组合。也未解决
完整 egress、恶意 namespace/signal containment、bootstrap 退出后的 deadline enforcement、
machine restart recovery、外部 worker 来源/ownership 和真实 campaign。上述限制不得用 fixture
成功推断为已验收。新 head 的 Ubuntu 3.11/3.12/3.13 CI 仍须由 PR #2 独立通过；本段本地结果
不能代替 CI。PR #2 不得在没有新的用户授权时合入 main。

推送后的 Ubuntu CI 首轮发现 Linux Landlock 对跨目录 `rename/link` 的拒绝可返回 `EXDEV`；
native input fixture 原先只接受 `EACCES/EPERM`，因此误报 3 个版本失败。测试拒绝谓词已补齐
`EXDEV`，本地 native-input/lifeline/permission focused 回归为 **86 项，84 passed、2 skip**，
Ruff、compileall 和 diff check 通过；修复已单独提交，需以新 head CI 为准。

## 2026-10-02 Retained native evidence and controller-death broker regression

延续 Feature 160/157，工作分支仍为 `codex/rsi-native-worker-recovery`，PR #2 为 draft，
未合入 `main`。提交前复核 head `8c4b4de` 的 Ubuntu run `36886879470`，Python3.11/3.12/
3.13 完整 current/archived/frozen CI均成功；该结果不能替代本轮新 head 的独立完整验证。

- P1：新增 `read_native_retained_candidate` 与 immutable `NativeRetainedCandidateEvidence`，
  显式指定 candidate 和 published journal/formal producer receipt 摘要，复验原 launch
  intent/attestation/bootstrap/contract/evaluator/runner/dependency/environment。读取链复用
  strict native recovery、publication recovery、archive integrity 和 portable bundle bytes，
  材料复制后再次校验。bundle/entrypoint、producer/candidate execution、completion、
  evaluation receipt/result、publication receipt 分字段保留。38项实际本地 native fixture
  通过，含 prepared/all-rejected/unknown 拒绝、来源/材料/中途漂移和重复不改文件。
  原 native launch 没有 RSI episode/memory/完整 SolverRequest，故该 API 不返回 SolverResult，
  不追认 memory 使用，不启动/评测/发布，不授予 RSI 晋级；正式 gateway 仍须启动前绑定。
  当前 archive/state 必须仍精确匹配原发布后态，历史 population 读取另需协议。
- P0：现有 HTTP lifeline 已能在控制器死亡后停止实际 worker，无需再造 guardian。本轮补
  真实独立 controller + broker + fsynced journal 的6项组合回归：请求前/blocked headers 时
  仅 SIGKILL controller PID，worker absent/Z、连接关闭；无终态确认的 admission 仍 active/
  unknown。恢复原 inode/hash/bytes/budget，不写、不发信号、不启动或重试。新6项在
  Python3.11/3.12 各 passed（复用3.13的pure-Python test依赖，不代表独立完整环境矩阵），
  3.13相关focus34 passed。本地 orphan stop 不等于由恢复进程 reap，也不证明 provider outcome。

最终固定源码/测试组合 **1,923 unique cases：1,919 passed / 4 Darwin平台skip / 0 failed/
errors，exit0，260.168秒**；JUnit
`/private/tmp/lunar-retained-recovery-combined-20261002.xml`。覆盖全部 RSI/native trusted/
producer/controller transport/bootstrap/ownership/acceptance matrix；不是完整 current/
archived/frozen runner。Ruff(src/tests/tools)、compileall、whole-branch diff check，以及9段
指南Python示例语法/3个公开导出检查均通过。CI early stage已加入两组新测试，最终 head
Ubuntu三版完整回归仍需独立通过。

新增契约：Feature160 `native-retained-evidence.md`、Feature157
`controller-death-contract.md`；指南 `docs/rsi-local-runtime.md` 4.2。T160-33仅关闭已发布证据
读取；T160-13、T157-05/06整体保持开放。下一重点是完整 RSI launch request 前置绑定和
真实 solver gateway、native controller crash ownership/reconcile、外部project trust/runtime/
default registration、完整egress，以及官方evaluator/真实campaign验收。只读trusted local
证据不提供远程认证、历史删除/rollback保护或原子filesystem lease。

本轮只运行本地 C/bootstrap/loopback 与 provider-free fixture；没有运行 WebAgent、远程
evaluator/公司平台、真实模型或 OpenEvolve/Shinka campaign，没有读取/修改 `.env`/密钥。

## 2026-10-01 Main merged; durable solver handoff and active broker cancellation

PR #1 已按用户明确授权合入 `main`，merge commit 为
`01db0aaa58af3832db45df1e2b276d5101034cd6`，保留原分支88条提交。
最终 PR head `fe0246a` 的 Ubuntu Python 3.11/3.12/3.13 完整 current/archived/frozen CI
全部成功，run `36875156874`。下方 draft/未合入/等待该 head CI 的段落是历史记录，
不能作为当前状态。生产发布和真实效果验收仍未完成。

本轮从实际 `origin/main` 新开 `codex/rsi-native-worker-recovery`，延续 Feature 160/157：

- `DurableSolverGateway` 为受信本地 gateway 增加全局 episode claim，固定完整请求、scope、
  gateway/run 实际指纹与 ledger inode。started 先持久化，完整结果后才返回；重复完成记录
  不执行或追加应用记录。`restore_result` 显式补登已有完整结果，接通原 controller resume；
  DRS/BRS 原预算不重复扣、冻结 wave 部分恢复不合并。只有 started 时停止；显式对账仅允许
  failed/timed_out/cancelled/abandoned，拒绝 completed/unknown。不是外部 worker 认证。
- 修复真实 active broker cancellation 缺口：原代码在请求中取消 target 后仍等 provider
  response/request timeout，本地阻塞3秒复现取消返回2.996秒。现在 native main 设置 stop
  Event，broker 在原 admission deadline 下轮询，确认 exact HTTP worker cancelled 后回收。
  用户 callback 不在 broker 线程调用；pipe FD 仍由 broker 独占。丢确认保留 active/unknown；
  两种路径都无 formal success receipt/候选发布，重复恢复无新进程/I/O。

局部契约：Feature 160 `durable-adapter.md`，Feature 157 `active-cancellation-contract.md`；
本地用法见 `docs/rsi-local-runtime.md`。单元54项、controller组合3项已通过；broker重点69项
在Python3.11/3.12/3.13各通过。初次组合1878项为1874 passed/4平台skip，无failure/error，
217.278秒；该轮期间broker最后补了observer耗时计入剩余预算，最终稳定树组合报告另行记录。
最终固定源码/测试组合为1879项：1875 passed / 4 Darwin平台skip / 0 failure/error，
exit 0，211.727秒，报告 `/tmp/lunar-worker-recovery-final-20261001.xml`。覆盖完整 RSI、
native trusted、producer、controller transport、bootstrap、ownership 与 acceptance matrix；
不是完整 current/archived/frozen runner。最终 Ruff(src/tests/tools)、compileall、whole-branch
diff check通过，8个本地指南Python示例语法有效。新增测试已放入Ubuntu早期检查；本轮最终
head完整Ubuntu三版CI须独立通过，不能沿用PR #1绿灯。

继续保持只用本地 fixture，不运行 WebAgent、真实模型、远程 evaluator、公司平台或实际
OpenEvolve/Shinka campaign，不读取或修改 `.env`/密钥。T160-13、T157-05/06 等整体任务仍
开放：外部来源/ownership/独立可信成功对账、controller死亡后的活跃transport恢复、完整
egress、真实project trust/runtime/default registration、官方evaluator与实际campaign验收。
保留 native publication → RSI 的只读已发布结果投影为后续 P1；本轮没有实现该桥接。

## 2026-10-01 Final-head local validation and remaining Ubuntu audit failure

`36899fe` 的完整、固定源码本地 current 回归已独立通过：9,230 unique cases，
9,215 passed / 15 Darwin/filesystem skips / 0 failed/errors，exit 0，924.505 秒。
JUnit `/tmp/lunar-current-clean-head-36899fe-20261001.xml`；不是初跑与 focused 的拼接。
同 head wheel 的170运行时文件和 sdist 的504源码/测试文件逐字节匹配；隔离安装后的
mock DRS/BRS、inspect 和不新增账本的终态重放均通过。证据
`/tmp/lunar-package-verification-36899fe-20261001.json`、
`/tmp/lunar-installed-wheel-36899fe-20261001-validation.json`。

Ubuntu run `36855386837` 在 Python 3.12/3.13 完整成功；3.11 current 唯一失败为
`test_native_campaign_audits_all_candidates_and_is_read_only`，报告 preparation_success=1/1，
status=failed。原失败必须保留，PR #1 仍为 draft，尚未合入 main。完整 annotations 在
`/tmp/lunar-linux-ci-36899fe-annotations-20261001.json`。
正式 acceptance runner 已在审计前 `_quiesce_native_database`，而 fixture 缺少这个步骤且
在 before inventory 前又通过 Store.list_events 重新开启 WAL。受控 Python 3.11 GC
交错已复现：原库 WAL/SHM 删除、DB 字节变化，candidate2/holdout8 均通过但审计以
audit_inventory_changed 拒绝；fixture 已复用正式 quiesce gate，并增加正反交错回归。
原 CI 的省略报告不足以重建全部原字段；不能把受控复现改称原调用的完整 trace。
CI 的早期 native focus 现在包括 campaign audit，用于提前暴露该边界。
该 fixture 完整7项在 managed Python 3.11/3.12/3.13 均通过，强制GC正例仍要求全文件字节
不变；反例必须保留 inventory_changed。生产 auditor 未改，未知/身份/预算 gate 未放宽。
报告 `/tmp/lunar-campaign-quiesce-py311-20261001.xml` 与 `py312`/`py313` 同名报告。
最后仍需本修复 head 的完整 Ubuntu 三版 CI，不能用 parent head 的两版绿灯代替。

## 2026-10-01 Ubuntu cancellation cleanup correction

PR #1 的 `0c5cc3a` Ubuntu run `36846543906` 实际出现 7 项取消/超时清理失败；3.13
current 9,195 cases、30 platform skips、0 errors，archived 2,294 与 frozen 24 均通过。
原失败保留，不能称该 head 合入就绪。Linux zombie 的 `/proc` owner identity 仍可读取，
而旧 cleanup 没有在 TERM/KILL 后回收 live caller 的直接子进程，killpg0 因此保持 alive。

修复增加可选 `reap_child` 非阻塞 hook；live producer/native launcher 传原始 Popen.poll，
每次 group probe 前回收，不用返回值授予 cleanup/kill 权限，不改变原绝对 deadline，
恢复路径没有原 child handle 所以不传 hook。活 descendants、归属漂移、hook 异常仍拒绝。
更快 cleanup 暴露 native cleanup reserve 提前停止后的 scheduler 分类错误；明确 wall_timeout
现在按原始 tighter caller budget 传播 typed budget exception，独立更紧的 intent limit 保持
native timeout code，unknown 不变为可发布。

本地 producer 79 passed / 2 Linux skip；related 84 passed；native timeout 五套件 105 passed；
最终 ownership/scheduler units 68 passed；3.11/3.12 hook focus 各 5 passed。Ruff、compileall、
YAML 和 whole-branch diff check 均通过。CI 增加 full runner 前的 native cleanup focus 和
artifact；仍需新 PR head 三版 Ubuntu current/archived/frozen 全部成功，尚未合入 main。
详细证据和保留的失败见 Feature 156 `main-integration-validation.md`。

上述修复 `87ea0ce` 的 early Ubuntu focus（run `36851401335`）把失败缩至三版同一项
active cancellation E2E。目标的 marker 可以早于 host 接受 target_started frame；仅看该
文件立即取消时，控制器按契约保留 unknown，不能写 verified cancelled terminal。
E2E 现在精确等原 accept_frame 成功验证目标启动，再结合实际 marker 取消，全部原断言
保留；新增确定性“marker 已写但 start frame 未被 host 接受”回归，确认只保留 unknown。
E2E 13 与该负例 1 均 passed，没有生产行为放宽或新增等待预算。最新 wheel 源码/资源
170 文件逐字节匹配，安装后 mock DRS/BRS、inspect 与不重复落盘的 terminal replay 均通过，
证据 `/tmp/lunar-installed-wheel-cleanup-20261001-validation.json`；仍需新 head Ubuntu 完整矩阵。

`aa66d89` 的 early Linux cleanup 在 3.11/3.12 通过；3.13 只出现时间断言的浮点减法
精度失败（133.55416034799998 - 125.554160348 ≠ 整数 8）。现在精确验证原 deadline 加法
构造，不使用宽松容差或改变预算；负例同步也等待 marker 完整字节以固定目标写入与取消
顺序。最终 attempt/E2E focused 51 passed / 0 skip，Ruff、compileall、diff check 通过。

`121ba4e` early cleanup 在 Linux 3.11/3.13 通过；3.12 暴露 cancellation composition 的
真实预算漂移：原25秒通过 deadline-start 重算变成24.999999999999986，prepared deadline
的 budget/journal 指纹与原 control 恢复不一致。现同 deadline 的组合精确保留原 allowance，
更窄 parent 仍收窄，不放宽 journal gate。新增11项浮点边界/原始 budget pin 恢复回归，
五套件含全部 E2E 119 passed / 0 skip；静态检查通过。接下来以新 head 的完整 Ubuntu
current/archived/frozen 三版结果为准，原失败证据继续保留。

## 2026-10-01 Main integration and cross-platform corrections

已创建并关联 [PR #1](https://github.com/vchive/Lunar-Evolution/pull/1)，base 为实际主分支
`main`，head 为 `codex/feature-156-producer-lifecycle`。开始时 `origin/main` 是 head 的祖先，
0 behind / 81 ahead；merge-tree 无冲突。PR 暂为 draft，未合入主分支；Ubuntu Python
3.11/3.12/3.13 的当前、历史和冻结回归仍是合入门槛。PR CI 增加取消旧提交运行的配置。

并行审查修复 deterministic draft 目录的 active replacement 窗口，创建/chmod/fsync 改为
held no-follow descriptor，复核 parent/run/children inode；新增 7 条替换/私有/create-only
测试。Linux bootstrap 的匿名 zero-link target FD 必须具有全部 4 项 seals，普通 unlinked
文件和 incomplete seals 拒绝；Landlock regular read path 不再使用目录专用 READ_DIR。
Linux C fixtures 使用 static 编译，不扩大生产 runtime allowlist；新增 9 条 native/isolation
回归，其中 8 条在本机 Darwin 跳过，必须由 Ubuntu 执行。

旧 main CI 的 handoff 测试把全局 os.stat 禁用到自身 rglob/pytest JUnit 阶段；现在仅在
handoff 调用内禁用，3.11/3.12 focused 各 100 passed。cooperative producer 的 Linux test
现在精确要求 gate + sealed executable 两个 FD。整个分支 diff 的 3 处文档空白已修复。

本轮 required runner 的 archived 2,294 与 frozen 24 均通过；starting current 9,179 cases
为 9,171 passed / 7 platform skips / 1 preparation preflight failure，overall exit 1；该未改
node 和整个 preparation file 后续分别 1/48 passed。组合 focused 183 cases 的一个 native
loopback request 保留 admitted-only journal，target exit 12；独立重跑通过，scheduler fixture
把 request budget 从 1 调到 5 秒，native wall 仍为 12 秒。不得把这些失败报告改称全量绿灯。
完整诊断、报告路径与合入/发布边界见 Feature 156 `main-integration-validation.md`。

最终 E2E 13 passed / 17.75s；逐 node-ID 核对最终 9,195 current cases 全覆盖，最新结果为
9,180 passed / 15 Darwin platform skips / 0 failed/errors，无遗漏/额外节点。原失败完整
runner/focused 报告仍保留，这是 starting full run + final focused reconciliation，不是
immutable final-tree 单次零失败运行。Ubuntu PR head 矩阵必须独立通过后才可合入。

## 2026-10-01 Shared budget, governed generations and local producer completion

延续现有 SDD，并行完成本轮可本地验收的 P0/P1/P2 实现。当前代码和本节优先于下方旧缺口：

- P0：`ParentRunBudget` 把 learning 与 holdout/evaluator/unknown-retry 合账。原计划/绝对
  deadline 不刷新，事件先持久再调用；parent→child charge 中断幂等。外层 generation 对账
  也独立扣 unknown 预算。跨库、删除/换绑/未扣费 external receipt 和终态恢复均拒绝。
- P0：controller generation marker 绑定独立 admission checkpoint、原 candidate/source proof
  以及实际 approved/active admission heads；改写 controller checkpoint 的 memory/status/
  terminal 字段不能绕过准入。之后 revoked 的历史结果可只读诊断，但不授权新 solver。
- P1：`RSIGovernanceCoordinator` 冻结 generation、parent、逐项 source/继承 lineage、manifest、
  runner 与原 parent budget；配置后自动 post-practice holdout 和整代准入。同一 DRS/BRS run
  可跨多代；rejected 保留 parent，unknown 阻止整 run 且不重发调用。
- P1：`generation_revalidate_before_dispatch=True` 可选地在每个新 episode 前自动复检一次，
  固定 request digest ID、共享预算，失败 quarantine，unknown 显式恢复，before-run 完成
  重放不再调用/扣费。BRS controller 准备验证，worker 只读复用，避免 parent-lock 争用。
- P1：完整 Actor clean-room evidence create-only sidecar + first-call claim。未知 claim 不
  重跑 evaluator，完整 pins/decision/raw verdict 可恢复并显式喂给 admission；controller DRS
  完整落盘、retry/memory 与终态不重复 spawn 均通过本地 fixture。
- P1：实际本地 native bootstrap + C target + loopback broker 经过正式 receipt/strict output/
  native candidate/evaluator/archive/population/delivery/只读恢复。新增父 deadline、active
  cancellation、receipt 后中断、partial-commit unknown 和精确 published replay fixture。
  候选和 evaluator 现在在现有轮询中检查 caller guard、先清理进程组再传播取消/预算错误；
  cancellation-only/shared-wall/独立 publication guard 均接通，commit 临界区保留。
- P2：显式跨 solver translation 只输出 provenance-bound unresolved draft；repeat-pass
  confidence 提供 bounded bool observations、Wilson marginal interval 和完整 pin 恢复。
  二者不授予 active memory 权限，不替代真实 campaign raw receipts。

API/恢复顺序和可运行本地示例见 `docs/rsi-local-runtime.md`。局部契约：
`shared-parent-budget.md`、`generation-governance.md`、`controller-generation-governance.md`、
`controller-dispatch-revalidation.md`、`actor-evidence-persistence.md`、`memory-translation.md`、
`noise-confidence.md`，均位于 Feature 160；producer 证据见 Feature 156
`local-native-scheduler-validation.md`。

本轮没有运行 WebAgent、远程 evaluator、公司平台、真实模型或真实 OpenEvolve/Shinka campaign，
没有读取/修改密钥。剩余重点是正式官方 evaluator/模型效果验收、外部 project launch trust/
runtime allowlist/default project registration、worker 来源/ownership/可信 unknown completion、
完整跨平台及 active transport crash/bypass 矩阵。trusted local SQLite 不提供历史删除/rollback
防护或远程原子 lease；模型训练仍为独立轨道，后台/分布式 scheduler 不在当前本地主线。

工作分支仍为 `codex/feature-156-producer-lifecycle`，推送不等于合入 main/master。不要覆盖
未提交工作。实现提交 `3a2dcde`（RSI）和 `74afaf7`（producer）已推送该分支。
最终本地 current-tree 清单 **9,179 cases** 全部有执行结果：**9,172 passed / 0 failed /
0 errors / 7 skipped**。六项需要本机不具备的 Linux sealed-memfd/runner，一项要求独立大小写
文件别名；改动的本地 RSI/native scheduler 用例无 skip。完整 run 9,178 cases 加最终新增
publication guard 单条，逐 node-ID 核对无遗漏，合计 910.579 秒；aggregate JUnit
`/tmp/lunar-current-final-inventory-20261001.xml`。这不是 archived/frozen snapshot runner 的重跑。
最终 Ruff（src/tests/tools）、compileall 和 diff check 均通过；详情见 Feature 160
`validation.md`。

## 2026-10-01 P0/P1/P2 execution and local runtime composition

延续 Feature 160 与 producer lifecycle SDD，本轮优先级清单见
`specs/160-rsi-learning-mode/priority-execution.md`。开始时工作区干净，之后并行完成如下增量：

- P0：native caller cancellation/parent deadline 在 attempt、receipt、output、publication 的
  新阶段持续检查；保留 intent 的 native-attempt-only timeout 和 publication commit 临界区。
  transfer schema v3 绑定 manifest/input、policy、memory 和 raw trials，默认要求 unseen 全部
  pass 且无 pass-rate regression。原始跨任务/no-memory 污染标记不能靠重算 report digest 删除。
- P0：`rsi_regression_campaign.py` 提供 controller-ledger-backed holdout。每 trial 持久
  reservation → started → completed，transfer/evaluator 原子预留，未知调用必须显式
  evidence-bound reconcile；unknown-retry 预留幂等，原绝对 deadline 不刷新，最多 1024 trials。
  approval reason 升级到 `controller_transfer_promotion_v2:<digest>`，绑定 actual manifest、
  policy、parent、components/external pins 和 planned budget；legacy v1 批准不自动激活。
  完成报告按治理库/收据缓存；nested caller pins 冻结并在 trial 边界检查。
- P1：`AgentLoopCleanRoomVerifier` 显式接入 controller verifier 协议。候选和依赖用
  bounded/no-follow 读取，拒绝文件/目录替换；分别校验 Actor manifest SHA 和 clean-room
  raw artifact SHA，冻结 public input，再用独立 spawn 重验。DRS practice → memory → retry
  和 terminal resume fixture 已通过；完成 callback 不重复 evaluator。
- P1：`GovernedMemorySnapshotGate` 通过 `memory_admission_gate=` 接入 controller：新 intent
  和 solver dispatch 前要求 exact frozen snapshot 的全部 admissions 为 active 且来源、
  scope、compatibility、item/verifier/holdout evidence 匹配；revoked 拒绝整份快照。
  治理读取后重新检查 deadline；gate 配置绑定 run fingerprint，完成记录仍可只读重放。
- P2：`rsi usage PATH [--run-id ... --episode-id ... --adapter-stage ...] --json` 只读诊断，
  在 home/SQLite 初始化前处理，不建锁或目录；输出 nullable totals、未知 receipt 数、
  stage breakdown 和明确标记的成本估算。缺失/损坏不解释成零用量。

本轮组合回归 **890 passed / 0 failed / 0 skipped in 49.42s**，含 **773 RSI cases** 与
117 producer/native cases，JUnit `/tmp/lunar-priority-regression-20261001.xml`。之后仅新增
嵌套 pin alias、malformed-memory intent 和 legacy-v1 approval 三条回归，campaign/promotion
focused **43 passed in 0.84s**，JUnit `/tmp/lunar-rsi-campaign-final-20261001.xml`。
最终 `ruff check src tests`、compileall 与 diff check 通过。没有运行 WebAgent、远程
evaluator、公司平台、真实模型或真实 OpenEvolve/Shinka campaign，也没有读取/修改密钥配置。

未完成的重点必须保留：

1. P0 接线：holdout 使用同一 RSI budget schema，但 campaign budget 尚未从 parent DRS/BRS
   已消耗预算扣减；仍需 shared parent/run budget 与自动 holdout/quarantine 调度。
2. P1：governance gate 消费一个 frozen generation。practice commit 后的新 snapshot 必须
   re-admit + 新 run；同 run 跨代自动治理仍未完成。gate 只验证 trusted local latest heads，
   不防数据库历史删除/rollback，也不提供横跨远程 solver 的原子 lease。
3. P1：完整 Actor clean-room evidence 自动持久化/admission、真实官方 evaluator、外部 worker
   来源/ownership、可信 unknown→passed completion，以及完整 producer recovery/transport/
   scheduler 和真实 campaign。T153-06/06b/07、T156-05/06/09/11/12/14、T157-05/06、
   T158-04、T159-05 的完整验收仍开放，supporting fixture 不替代生产完成。
4. P2：跨 solver memory 翻译、噪声 confidence policy 与共享控制原语；模型训练仍是独立轨道。

当前工作分支仍为 `codex/feature-156-producer-lifecycle`，推送该分支不等于合入 main/master。
不要覆盖未提交修改；继续开发先读本节、priority-execution、tasks 和局部 SDD。

## 2026-10-01 RSI curriculum policy, quarantine and durable promotion identity

本轮继续现有 Feature 160，未扩大到真实 producer/evaluator。已提交的 `2be9651` 增加失败
transfer report → governance revoke 边界，`3507df3` 增加显式 `FailureBoundaryPolicy`：
未覆盖 capability/prerequisite 优先、hard-negative 阈值、单 cluster 预算与 novelty。新选择
记录 diagnosis/policy digest，恢复重演 cluster、task、reason、coverage 和预算；ledger digest
绑定完整 policy，controller checkpoint 持久化 policy，legacy 无 policy 仅按默认 v1 和旧摘要
公式验证。contract 见 `specs/160-rsi-learning-mode/curriculum-policy.md`。

独立审查后进一步收紧晋级和撤销：caller fingerprint 不得替换 controller 观测 pins；
revoked/pre-shadow admission 在 runner 前拒绝；每次 trial 前后和最终写入前复核组件。
controller approval 在同次 governance CAS 中，把观测组件与 external pins digest 写入
`reason=controller_transfer_promotion:<sha256>`，所有 approved/active replay 都检查该绑定。
新 controller 可复用原批准收据而不重跑 runner，但组件漂移或 legacy 无绑定记录会停止。
direct promotion adapter 保持显式本地 API；这里不是外部来源认证或 Python/OS sandbox。
quarantine 的 revoke reason 绑定 rejected report digest，手工撤销/不同报告不得冒充同一次
重放；撤销后 admission 不可检索，但没有修改 immutable `RSIMemoryStore`。

最终本地 RSI 回归 **584 passed / 0 failed / 0 skipped in 6.17s**，JUnit 报告
`/tmp/lunar-rsi-release-20261001-v2.xml`；focused promotion/governance/transfer **51 passed**，
curriculum/resume **33 passed**；`ruff check src tests`、compileall 和 diff check 通过。
本轮更新 tasks、validation、stage-gap、curriculum-policy 与 memory-promotion 规格。
T160-13 的 provider-free policy 子项已关闭，真实 adapter/worker 来源、ownership 和可信
unknown 完成证据仍开放。下一步仍是受控默认 holdout/quarantine 调度、真实 Actor/evaluator
artifact handoff，以及 Feature 156/157/158 的正式 producer 生命周期接线；不运行 WebAgent、
远程 evaluator、公司平台或真实 OpenEvolve/Shinka campaign。当前工作在
`codex/feature-156-producer-lifecycle`，不等于已合入 master/main。

## 2026-10-01 RSI clean-room admission and controller promotion composition

Feature 160 新增两条本地 provider-free 组合边界。`CleanRoomAdmissionGate`（见
`src/lunar_evolution/rsi_cleanroom_admission.py`）只接受 outcome 为 `pass` 且 episode、source、
dependency、task input、evaluator provenance 与调用方 pins 完全一致的
`CleanRoomVerdict`，以幂等方式把 governance admission 从 `observed` 推进到 `verified`。
它不修改只读 `RSIMemoryStore`，不直接推进 candidate/shadow，也不提供外部 evaluator 或
worker 真实性证明。

`RSILearningController.promote_transfer_regression()`（见
`src/lunar_evolution/rsi_controller.py`）是显式 opt-in 的 controller 组合入口：冻结当前
snapshot 和传入的 parent snapshot，运行本地 `TransferRegressionSuite`，检查
solver/verifier/curriculum/target-judge fingerprint、snapshot/parent digest 与 governance
CAS，再交给 `MemoryPromotionAdapter` 执行 `shadow -> approved`，可选继续
`approved -> active`。同一 controller 对已完成 promotion 只读重放，不重复 runner 或
governance revision；入口不会自动调度 holdout、调用真实 evaluator、修改 memory store 或
接入 OpenEvolve/Shinka campaign。`activate=True` 仍保留 approved revision，失败、漂移和
rejected report 均 fail-closed。

本轮文档同步更新 `specs/160-rsi-learning-mode/stage-gap-report.md`、`tasks.md`、
`validation.md` 和 `memory-promotion.md`。实现仍属于本地 fixture 边界；提交前必须运行
controller-promotion、memory-promotion、transfer-regression、clean-room admission/clean-room
focused tests，以及 Ruff、compileall、`git diff --check`。不要把这些结果描述成真实模型、
官方 evaluator、外部 producer 或 WebAgent 验收；当前分支也不等于已合入 `master`。

## 2026-10-01 Broker journal recovery and scheduler boundary hardening

当前 feature 分支已推送 `2248cf7`、`816c283` 和 `2a9f16d`。scheduler 在消耗一次性
attestation 前拒绝 NaN、无穷大和其他非法 `parent_deadline`，并保留 cancellation/deadline
向 native attempt 的原样传播。Feature 157 broker 增加只读
`recover_producer_broker_observation()`：它在调用方 deadline 内重放 controller-owned journal，
绑定 journal digest、字节数以及打开文件的 device/inode，拒绝 same-content replacement、
partial append、非法 descriptor handoff 和无效 HTTP 状态；活动或超时请求保持
`recovery_required`，不会重开 journal、重试 provider 请求或恢复 producer。

本轮 focused broker/request/native scheduler 回归、Ruff、compileall 和 diff check 均通过。
这些是 T157-05/T157-06 的 supporting evidence，仍未完成完整 egress coverage、跨进程生产
scheduler/launcher、Feature 156 正式生命周期接线和真实 OpenEvolve/Shinka campaign；当前仍只
使用本地 fixture，不运行 WebAgent、远程 evaluator 或公司评测平台。

## 2026-10-01 Native trusted scheduler and read-only recovery supporting slice

新增 `src/lunar_evolution/native_trusted_scheduler.py`，提供两个明确的本地 supporting
入口：`run_native_trusted_producer()` 按一次性顺序串起 native trusted attempt、正式
`execution-receipt.json` 持久化、严格同尝试 output preparation，并在显式传入 strategy 时
调用 Feature 153 publication transaction；publication journal 绑定同一 journal/run/task
身份和 `native_execution_receipt_sha256`。未传 strategy 时只返回 prepared 结果，不隐式发布。

`recover_native_trusted_producer()` 是只读恢复入口：只重新验证原 launch/attestation、正式
receipt 和 output evidence，不重新启动进程、不消费第二次 attestation、不刷新预算，也不
发布 population。缺失、漂移或不完整证据均 fail-closed；恢复结果只有在 receipt digest 与
strict output projection 一致时才返回。

`tests/test_native_trusted_scheduler.py` 的 provider-free focused regression **6 passed**，
覆盖顺序、输入 gate、显式 publication 绑定、不完整 attempt 拒绝、只读 recovery 和 receipt
binding drift。测试通过 boundary doubles 验证调度边界，不能替代真实 native bootstrap、host
observed request transport、跨进程 crash recovery 或 OpenEvolve/Shinka campaign 验收。
因此这是 Feature 153/156/158 的 supporting slice；正式 launcher/scheduler 生产接线、
unknown/interruption recovery、Feature 157 controller-owned transport、完整生命周期验收和
真实 campaign 仍保持开放。当前仍只运行本地 fixture/provider-free 回归。

## 2026-10-01 Formal native execution receipt to publication journal

Feature 156/157/158 的 native trusted evidence 现在已有正式收据闭环：在 terminal、并发有界
stream、稳定 envelope、host broker coverage、target execution binding、durable deadline 和
owner-checked cleanup 全部复核通过后，create-only `execution-receipt.json` 才会持久化；重复
调用只读复用完全相同的 canonical bytes，漂移、冲突、symlink、非 regular 文件或不完整证据
均 fail-closed。Feature 153 的 publication transaction 可通过
`native_execution_receipt_sha256` 接收该收据摘要，在写入 `journal.prepared.json` 之前读取并
校验同一 batch 下的正式收据、任务身份、成功终态、gate release、cleanup 和 broker coverage，
并把摘要写入 canonical publication journal。未提供该可选字段的 legacy journal 保持原有字节
兼容性。

这条链已经有 provider-free focused regression，覆盖有效 receipt 的 journal round-trip 以及
缺失、格式错误、自摘要篡改、失败终态和错误任务身份的零写入拒绝。它只证明“正式执行收据
→发布 journal”的持久边界，不等于完整 receipt schema 在发布边界重新投影，也不等于 trusted
bootstrap 的生产 runner、crash-safe broker recovery、scheduler/default producer entrypoint 或
真实 OpenEvolve/Shinka campaign 已完成。后续仍需完成 T153-06f、T156-05/06/09/12/14、
T157-05/06、T158-04 的生产接线与真实 campaign 验收；当前仍不运行 WebAgent 或远程 evaluator。

## 2026-10-01 Native trusted stream, envelope, cleanup, and receipt projection

Feature 158/156 的 native trusted supporting slice 已继续推进。native bootstrap 现在以非阻塞
并发管道读取 stdout/stderr，按每个流的 `output_max_bytes` 限制生成
`native-trusted-stream-capture.json`，并把 `stream_capture_sha256` 绑定到 process-only
terminal；恢复会校验流状态、摘要、边界和同一 launch/registration/deadline。输出 capture
现在记录 envelope 的 `identity_before`、`identity_after`、`read_status=stable`，broker
记录绑定 canonical host journal identity、摘要、大小和 admitted-count coverage。

owner-checked cleanup 现在生成 create-only `native-trusted-cleanup.json`，terminal 绑定
`cleanup_sha256`，恢复重新验证 cleanup sidecar，不能借 sidecar 自己的摘要伪造另一种 cleanup
结果。`native_trusted_receipt.py` 的严格 projection 只有在 terminal、bounded streams、stable
envelope、完整 broker coverage、target execution binding 和 cleanup 全部闭合时，才构造
Feature 156 `ProducerExecutionReceipt`。新增的
`persist_native_trusted_execution_receipt` 在同一严格检查之后，以 exclusive bounded
fsync/atomic no-follow 方式 create-only 写正式 `execution-receipt.json`，随后 bounded reread
并复核 canonical self-digest；完全一致的已存在 receipt 只读幂等重放，冲突、篡改、symlink、
非 regular 文件或 evidence 漂移 fail-closed。该持久化仍不会开启 population admission 或
publication，后续发布事务继续独立负责放行。

本轮已推送的增量包括 `fba0cf3`、`fcf9f87`、`fa46ba2`、`af5e5c5` 和本分支的 receipt/cleanup
实现。focused native attempt/output/stream/cleanup/receipt fixtures、Ruff、compileall 和
diff check 通过；未运行 WebAgent、远程 evaluator、真实 OpenEvolve/Shinka campaign。T158-04
仍未完全关闭：formal receipt 持久化、Feature 157 production journal 接线、publication
transaction、scheduler/default producer entrypoint 和真实 campaign 仍在后续范围。

## 2026-09-30 Native trusted durable attempt deadline

native trusted attempt 现在在消费 attestation 前，把本次尝试的有效 monotonic 起点和
`min(intent deadline, parent deadline)` 写入同一 batch 的
`native-trusted-attempt-deadline.json`，带当前 OS boot id 和自摘要。文件采用独占写入，
重复 launch 不会分配新的预算；恢复时必须验证 launch/intent/boot/摘要，恢复 cleanup
把原始绝对 deadline 传给 owner-checked cleanup，因此崩溃后的显式 recovery 不会刷新或扩大
原始墙钟预算。新增 focused 回归覆盖 sidecar 绑定、恢复 deadline 传递、篡改拒绝；native
trusted attempt suite **27 passed**。这仍是 Feature 158 T158-04 的 supporting slice，
尚未接入正式 Feature 156 execution receipt、发布事务或 scheduler。

## 2026-09-30 Native trusted control propagation audit

Feature 156 的 cooperative runner 已有 `cancelled` 回调和同一 monotonic 时钟域的
`parent_deadline` 组合（取 intent 与 parent 的较小值），并在捕获、leader wait 和清理阶段保留
`cancelled`/`unknown` 终态。此次文档审计把相同边界明确写入 Feature 158：native trusted
attempt 接入时必须在 spawn 前、登记后、bootstrap/target frame wait 和 leader wait 观察回调，
所有等待、cleanup 与 receipt 写入共用有效 deadline；回调异常、非法返回值、deadline 到期或
清理不确定都保持 fail-closed。

native trusted attempt 已接入 `cancelled`/`parent_deadline` 接口和 fail-closed 语义；selector、
broker、frame、leader wait 都使用短轮询，且为 owner-checked cleanup 预留同一 deadline 内的
收尾窗口。native-attempt focused suite **24 passed**，覆盖 active cancellation、cleanup
uncertainty、parent deadline 提前终止和非法控制输入；Ruff、compileall、diff check 通过。
acceptance matrix 的 L158-05 已更新为 `supporting-only`。这条 supporting-only/production
integration 边界不能由 cooperative L156-12 的离线证据代替；仍需与 Feature 156/157 的正式
registration、broker、terminal receipt 和 recovery 生命周期一起验收。

随后补齐 native trusted 的已验证取消持久化：目标已启动、owner-checked cleanup 成功且取消
回调为真时，写入同一 process-only terminal schema（`process_status=cancelled`、`exit_code=null`），
绑定原 handoff 与 unknown-or-passed bootstrap evidence；只读 recovery 幂等返回，cleanup
uncertainty、callback error、deadline expiry 和 pre-gate cancellation 不会伪造 cancelled 终态。
新增 tamper/recovery/no-terminal 回归，native trusted focused suite **26 passed**。这仍是
supporting-only 证据，不等于 Feature 156 正式 execution receipt、broker 或 post-crash 生产接线。

## 2026-09-30 RSI/producer 本地闭环增量

已推送 `31f0098`（RSI）和 `d1ae8bc`（producer）。RSI 新增 spawn 进程级 clean-room verifier：
私有 JSON IPC、结果大小限制、硬超时 terminate/kill、异常隔离、fingerprint/工作区篡改
fail-closed；新增 provider-free 用量账本的严格 JSON/CAS/hash-chain、估算成本和按指标
fail-closed 预算摘要。`RSILearningController` 可选注入 usage ledger，solver 调用记录确定性
event ID 与本地 monotonic wall time；恢复时缺少 sidecar 会登记未知时长，不伪造成本或精确时长。
当前 RSI 本地组合 **523 passed**，未运行 WebAgent、远程 evaluator 或公司平台。

Feature 153 新增同一 OS boot 内的 durable monotonic deadline：在 prepared intent 前写入
`execution.deadline.json`，绑定 journal digest、boot、clock、inode 和原始 deadline，重启后
只能恢复同一 deadline；锁替换和写入中的身份漂移 fail-closed。producer bundle 回归 **208
passed**，全量相关选择此前 **1328 passed / 2 skipped**；未运行真实 producer campaign。

当前仍开放：真实 Actor/官方 evaluator 和 artifact handoff、usage provider billing/GPU truth、
完整 unknown/interruption recovery、evolved/seeded/repeated population admission、
launcher/scheduler 接线和真实 OpenEvolve/Shinka campaign。Feature 153 transaction 尚未自动
把该取消回调接到外部 producer 生命周期。

随后补齐 Feature 156 cooperative runner 的运行中取消窄切片：`run_producer_process`/
`ProducerProcessRunner.run` 接受 process-local `cancelled` 回调，在启动前、登记后、非阻塞
capture 循环和 leader wait 中观察；owner-checked cleanup 成功时写入一次 `cancelled` 终态，
清理不确定保留 `unknown`，回调异常或非布尔值在 spawn 前 fail-closed。新增本地 fixture
覆盖 active cancellation、cleanup uncertainty 和回调错误，producer-process/lifecycle
专项 **81 passed、2 skipped**。随后增加同一 monotonic 时钟域的可选 `parent_deadline`，runner
与 intent deadline 取较小值，并覆盖窄预算终止和非法 deadline fail-closed。当前专项为
**83 passed、2 skipped**。这不等于 Feature 153 transaction 已自动接入该回调，也不关闭
trusted bootstrap、host-observed request、post-crash recovery、launcher/scheduler 或真实
campaign 边界。

## 2026-09-30 RSI callback 显式对账与 unknown transfer 处置

继续 Feature 160 阶段 1，补齐上一轮留下的本地恢复接口。新增 `rsi_callbacks.py`，
DRS/BRS verifier、target judge、curriculum 在调用前写 started，校验结果后写 completed。
调用内部中断会隔离整条 run；已持久化结果只读复用。`reconcile_callback` 绑定原输入、当前
组件、结果和本地观察证据，先持久化一次 unknown-retry 预留，再收录结果；两个步骤之间
再次中断可幂等恢复。过 deadline 只允许登记已发生的结果，不放宽后续工作期限。

Frozen transfer 保留 v1 journal，增加 callback 对账；原 unknown receipt 的 worker 已显式
settle 为 failed/cancelled/timed_out/abandoned 后，可用 `reconcile_receipt` 在同一事务内
追加 failed revision 和 checkpoint。旧收据、原始 unknown result 均保留，精确重放不再
调用 callback 或扣预算。没有 unknown→passed 的推断或证据补造。

CLI 支持 `rsi inspect RUN_ID --callback-id ID` 和 `rsi run CONTRACT --run-id ID
--reconcile-callback ID --expected-checkpoint-sha256 SHA --callback-result RESULT.json
--callback-evidence EVIDENCE.json`。后者只登记结果，返回 reconciled，另行运行原命令续跑。
新 run 固定 callback protocol marker；旧非终态缺 started 协议且存在执行证据时停在
`rsi_callback_migration_required`，旧终态仍可只读重放，避免升级后重复旧 callback。

本地 RSI 全组合 **438 passed / 0 failed / 0 skipped**，报告
`/tmp/lunar-rsi-callback-release01.xml`；Ruff、compileall、diff check 通过。
仅导出准备提交的源码独立验证，同样 **438 passed**（`/tmp/lunar-rsi-callback-index.xml`）；
Ruff、编译和所有公开 API 导入检查通过，不依赖工作区的未提交 producer 文件。
未运行真实模型、WebAgent、远程 evaluator、公司评测或 producer campaign。
契约及接口见 `specs/160-rsi-learning-mode/callback-recovery.md`。

剩余：真实外部来源认证、进程 ownership/heartbeat/cleanup、旧不确定记录的证据迁移、
unknown transfer 的可信成功证据协议，以及后续 clean-room verifier、memory governance、
holdout 收益回归、真实 solver 接线和用量/成本统计。当前对账是 local trusted evidence，
不代表生产 exactly-once。工作区 producer 文件和其导出仍保留未提交；不要 `git add .`。

## 2026-09-30 RSI 持久计划续跑与中断回归

继续 Feature 160 阶段 1，纠正此前把基础 resume/replay 等同于完整可恢复控制流的结论。
DRS/BRS 现在共用持久 v2 plan、launch intent、决策、执行证据、memory 和预算 checkpoint；
首次启动及恢复持有同一运行锁。已知结果复用后可继续原计划中尚未发起的 episode；缺少结果
的已发起请求保持隔离，不重复调用 solver。BRS 整波冻结父快照、统一预留预算并按 ordinal 合并。

显式 unknown→failed/cancelled 对账可恢复控制流，原始 unknown 或缺失的 result 保持原样；
run 对账绑定 episode journal 并消耗持久 unknown-retry 预算。恢复重算当前组件配置/代码指纹，
拒绝旧 observed 指纹掩盖漂移，检查预算历史不能回退和 execution 各层身份一致性。
已完成 journal 在 run head 更新前中断时，恢复不会因后来超时而改判。

Frozen transfer 使用独立 namespace、锁和 journal，复用已落盘结果、验证/判定与收据；
宽松 judge 不能让失败或 unknown 通过。DRS/BRS 重复 CLI 运行复用学习和 transfer 结果。
本地 RSI 组合 **289 passed / 0 failed**，JUnit：`/tmp/lunar-rsi-final-combined02.xml`；
Ruff、compileall、diff check 通过。没有运行真实模型、WebAgent、远程 evaluator 或 producer campaign。

独立导出暂存区源码再次 **289 passed**（`/tmp/lunar-rsi-index-validation.xml`），公开 API
全部可导入。检查发现旧提交 `38086ac` 提前导出了未提交的 producer 模块；本轮提交修正
该导出清单，工作区中的 producer 文件及其新导出保持原样，作为未提交工作留给对应开发线。

仍开放：真实进程 ownership/heartbeat/cleanup 与 unknown 观测；transfer callback 已启动但结果
未落盘时的显式对账入口、已发布 unknown transfer 收据的后续处置；DRS/BRS 本地确定性
verifier/curriculum/judge 的调用内部中断与真实外部 callback 不重复执行保证。clean-room
verifier、memory governance、holdout 收益回归、真实 solver adapter、嵌套递归与用量/成本统计
仍按阶段报告推进。阶段 1 不笼统标记全部完成。本轮只提交 RSI 文件，保留未提交的 producer 工作。

## 2026-09-29 Shinka 共享运行预算与全拒绝终态

在独立分支 `codex/shinka-native-publication` 继续 Feature 153，不扩展或提交 RSI。
事务新增 caller-owned `SolveExecutionControl`，复用同一个运行时钟，组合更紧的父级预算，
在候选、暂存、获得发布锁及提交前检查。锁等待支持取消/到期退出；超时、取消保留明确类型。
提交越过持久 unknown marker 后完成原有提交协议，避免已发布却被误报超时。
预算摘要由实际执行/评估/墙钟限额生成，重试不能通过省略 control 或复制旧摘要来放宽政策。

全拒绝批次现在写入独立拒绝收据及 `all_rejected/committed` 终态 journal，archive/state
保持原字节。只读检查从原始 native evidence 重建完整收据，拒绝仅重算便携摘要的篡改。
精确重试只检查终态，不再运行候选或评分；部分落盘或证据缺失保留现场并要求恢复。
该终态目前覆盖执行成功后本地评估 validity=0，不把未知/超时/非零执行当作已完成拒绝。

隔离树最终组合回归 **510 passed / 0 failed / 0 skipped**，JUnit 位于
`/tmp/lunar-shinka-20260929-controls.xml`；全树 Ruff、compileall、diff check 通过。
未运行真实模型、WebAgent、远程 evaluator 或真实 OpenEvolve/Shinka campaign。

仍开放：跨进程剩余墙钟持久化、运行中子进程即时取消、完整 unknown/中断恢复、演化后/有 seed/
多次 producer 导入、launcher/scheduler 接线、真实 producer campaign 和全量三阶段 release
runner。P1 完整生产验收尚未完成。主工作区继续保留并行 RSI 改动；选择性同步本轮 Shinka
文件，不要用整目录覆盖或 `git add .`。

## 2026-09-29 Shinka 原生离线发布链路

继续现有 Feature 153，保留并行 RSI 工作，未扩展其实现。Shinka SQLite fixture 已打通
导出、分组、原生隔离草稿执行/独立评分、原子发布、archive/state 回读、种群 resume 和交付包
读取校验。生产者分数不作为 Lunar 分数；低分但有效的候选可入库，同时由原生选择规则控制
活动种群。事务仅接受 iteration=0、running、无 offspring/seed/既有 producer admission 的种群。

执行前新增 `journal.prepared.json`，冻结完整任务、预算、来源与 archive 前缀；草稿证据绑定
该摘要。相同请求中断重试复用已完成证据，不重新执行或评分；修改任务/预算、缺少或篡改 intent
均拒绝。stage/commit/recovery 独立校验该绑定，删除证据描述不能绕过。最终独立分支回归：
319 项导入/种群/演化、44 项发布/恢复/事务通过；另一个先行证据组合为 64 项通过（集合重叠，
不累加）。Ruff、compileall、diff check 通过。没有运行 WebAgent、远程 evaluator 或真实模型/producer。

共享 HEAD `0504739` 中 RSI adapter 测试依赖尚未提交的 RSI 模块，因此发布使用独立 worktree
`/tmp/lunar-shinka-publication-20260929`、分支 `codex/shinka-native-publication`，基于 `f012b20`，
只包含 Shinka/native 改动；原工作区及 RSI 文件原样保留。后续请避免把这些已发布改动重复实现。

仍未完成：事务总墙钟/取消、all-rejected 持久终态、完整 unknown/中断恢复、更晚演化窗口导入、
launcher/scheduler 接线及真实 OpenEvolve/Shinka 验收。详见 Feature 153 tasks/validation；
本轮完成的是可回归的本地接入切片，不代表 P1 整体完成。

## 2026-09-28 ShinkaEvolve 离线接入与 RSI 并行状态

ShinkaEvolve 当前已接入为**离线 SQLite 导入器**：Lunar 可只读解析 Shinka 结果、导出候选，
再通过本地 warm-start/bundle transaction 路径评测和发布。Feature 153 的 mixed/all-rejected
以及发布后 `resume()` 回归已通过；当前事务边界只支持尚未开始 offspring 轮次的初始种群，
带有既有演化历史或 seed admission 的种群会 fail-closed（`producer_bundle_transaction_population_history_unsupported`）。
这不等于完整 Shinka 生产接线：尚未自动启动 Shinka、接入调度器或运行真实 Shinka campaign，
也未调用 WebAgent 或远程评测。

RSI（Feature 160）由并行工作流推进，现有 provider-free 本地 MVP、调研/规格/任务文档和
fixture 回归保持不变；本条交接不扩大 RSI 的真实 provider、LLM curriculum 或远程评测范围。

## 2026-09-28 开源 producer 接线与发布边界

“外部 producer”仅指 OpenEvolve、ShinkaEvolve 等开源演化器，不存在需要用户提供的私有
producer 服务或专用命令。OpenEvolve 现有显式本地单候选 wrapper；ShinkaEvolve 现有 SQLite
结果的离线导出/导入。用户的模型密钥在私有 `.env`，不得输出或提交；Feature 142 的真实模型
验收已经通过，无需重复跑该登记，也不运行 WebAgent。

本轮已推送 `9c1fedb`：批次 staging 在任何写入前重验完整 preflight receipt 及 archive
record count。已推送 `35850fb`：真实验收 revalidation 从已提交材料重建留存证据，拒绝同时
伪造材料和 admission 摘要。原生 broker 线程的管道所有权及墙钟 join 已收紧；相关原生
专项回归和线程异常严格检查通过。当前 `publication_eligible=false`，因为多文件流水线
评测时直接写目标 archive、分配顺序 ID，证据留在 `evolution/bundle-attempts`，不能直接
接到 Feature 153 的零写入、确定性 ID、原子批次发布。后续必须先完成隔离草稿评测、原位
执行证据的完整绑定和发布收据、完整请求出口及真实 OpenEvolve/ShinkaEvolve 独立验收，
方可声明 P1 完成。

## 2026-09-28 P1 同次捕获接入候选准备

原生多文件候选的只读准备增加显式 `require_same_attempt_capture` 严格路径：准备前后都恢复并
复核原尝试内持久化的输出收据和宿主请求日志，结果带收据摘要；broker 不完整或 producer 声明
的请求数与宿主记录不一致时拒绝。真实本地两文件 fixture 在有、无 broker 两种模式下通过，
输出或日志篡改后的严格准备会拒绝。旧的只读检查入口仍可用于支持性诊断，不能被当作发布许可。
输出、原生尝试、请求传输/证据、生命周期矩阵及隔离组合回归 **90 passed**；Ruff、compileall、
diff check 通过。全仓回归因测试规模较大中止，未将其记为通过。

当前 `publication_eligible` 仍为 false。Feature 157/158 的完整请求出口覆盖、候选本地执行
评分与原子发布、调度接线以及 OpenEvolve/ShinkaEvolve 的真实生产验收继续开放。本轮未调用
真实开源 producer 或新的模型 campaign。

## 2026-09-28 P1 原生输出与请求日志同次捕获

外部 producer 指 OpenEvolve、ShinkaEvolve 等开源候选生成器，不需要用户提供私有命令。
当前 OpenEvolve 的显式 wrapper 只接单候选，Shinka 的 SQLite exporter 是离线导入；
二者均未完成可信外部进程的全自动生产验收。

原生 trusted runner 现在在原尝试墙钟截止前，稳定读取 envelope 和所有声明的候选源文件，
把字节摘要、文件身份及进程终态摘要绑定到独占持久收据。使用宿主 broker 时，关闭后的
请求 journal 会在同一截止前重放校验；journal 身份、字节摘要、大小、请求数及声明请求数
是否一致也进入收据。恢复检查输出和 journal 是否改变。受控双文件 fixture 覆盖有无
broker 的成功链及源文件、journal 篡改；过期 deadline 不创建收据。
相关 native output/attempt、请求、生命周期及隔离回归 **87 passed**；Ruff、compileall、
diff check 通过。

这只是 P1 的证据切片：收据仍标记 `publication_eligible=false`，broker 覆盖仅为
`brokered_requests_only`。Feature 157/158 的全出口约束及请求执行证明、候选执行评分和
发布事务、调度及真实开源项目验收继续开放，T159-05 不勾选。未调用真实开源 producer、
provider 或新的 campaign。

## 2026-09-28 Feature 142 真实模型验收通过

第二套独立登记 `native-142-20260928-02` 固定产品 `94f6e0e`，登记提交 `3f877fe`，
在 clean remote `main` 上运行唯一一次 `glm-5.2` 尝试，退出码 0。共 9 次模型请求
（上限 20），观测 token 95,545（上限 160,000，usage 已知）。父任务 ID 为
`248522b8cd934e61a94c4b2de2cbc090`。不能在此登记下再启动或重试。

发布审计为 `verified`：准备、主目标、联合目标均 **1/1**，8 个固定 holdout 全通过；
2 个候选均完成生成、执行与评分。进程退出后，单独调用只读审计验证器核对了结果/报告摘要
及完整 campaign inventory；重新从登记、数据库和父任务 ID 生成的独立审计与发布报告
完全一致，审计过程未调用模型、执行评测或修改 campaign。证据位于
`.lunar/acceptance-campaigns-20260928/native-142-20260928-02` 及相邻 `-audit` 目录。
Feature 142 T040 对该固定任务和模型已完成。这是一次真实样本，不代表普遍成功率，
也不能代替 P1 外部 producer 验收。

首次失败登记 `native-142-20260928-01` 及其审计仍原样保留。P1 的宿主请求出口、
输出包验证、调度/发布链路仍在开发，当前不得宣称外部 producer 可发布。

## 2026-09-28 首次真实模型验收及修复

用户已在私有 `.env` 配置模型 endpoint/key；不要打印或提交。已从 clean remote `main`
进行一次新登记的真实 `glm-5.2` 验收：产品 pin `6089942`、登记提交 `49f00a4`，
campaign 为 `.lunar/acceptance-campaigns-20260928/native-142-20260928-01`。
一次性尝试已消耗，模型请求 3 次，观测 token 41,467，退出码 1。准备阶段的固定诊断为
`auditor_response / response_invalid`、不可恢复；preparation、primary、joint 均为 **0/1**，
没有进入候选生成和交付。不能在此登记下重试，也不能改写留存证据。

原生报告因准备 hook 未调用而缺少 parent ID；只读数据库复核确认父任务存在，但准备失败。
已发布的独立审计 inventory 在 SQLite 随后 checkpoint 后与现场不一致，原审计目录也保留不动。
当前代码补充了失败时的父任务 ID 回退、inventory 发布前的 SQLite 静止检查，并把未执行的
八项 holdout 计为 missing。runner/audit 专项 **15 passed**、验收组合 **37 passed**、原生
离线 E2E **226/226**；这是离线回归，不是成功的真实
验收。T040 仍需修复后的代码合入 clean `main`、全新登记与 campaign，再执行一次真实模型
尝试及独立审计。P1 外部 producer 的共享 deadline、完整请求出口隔离、正式登记/恢复仍未完成。

## 2026-09-28 provider-free acceptance staging checkpoint

最新提交 `3273a2e` 已推送。`stage_acceptance_attempt` 将新 campaign admission、
launch-time revalidation、create-only 单次 attempt claim 和发布后的 retained claim/inventory
复核接成一个 controller-owned provider-free 入口；失败后不复用或修复已保留的 campaign root。
这只建立持久的 `attempt-started.json`，其中 `provider_started=false`、
`provider_call_made=false`；没有调用模型、外部 producer 或 evaluator。launch/attempt gate
聚焦回归 **50 passed**。在 `3273a2e` 上重新运行原生离线 E2E，**224 passed / 0 failed /
0 skipped**，报告位于 `.lunar-evolution/test-results/native-e2e-20260928-stage/native-e2e.xml`；
pytest 清理旧临时只读快照目录时另有警告，不影响该次测试结果。

Feature 142 仍开放：T038 需把这个入口接入正式唯一 native solve 调用及执行监督；T039
需把已发布的 observation binding 接入 campaign discovery 和正式 runner；T040 需在新登记、
clean `origin/main` 与固定材料下运行唯一真实模型 attempt，并完成独立六阶段 postrun/holdout
审计。Feature 156/157/158 的外部 producer 正式共享 deadline、执行字节绑定、登记/清理/恢复、请求出口与
凭据保护、trusted bootstrap 生命周期绑定及完整矩阵仍是另一条未完成的生产接线，不能由
上述 provider-free staging 回归代替。

## 2026-09-28 campaign revalidation、trusted handoff 与 producer lifecycle matrix checkpoint

最新已提交并推送的提交为 `91ba125`、`e13b375`、`1579d43`、`7a008e7`、`f4a788b`、
`4db6a97`。本轮继续保持
provider-free：没有创建真实 campaign、调用 provider、启动外部 producer、运行 WebAgent，
也没有消耗 Feature 139 的唯一旧槽（preparation **1/1**、primary/joint **0/1**）。

`revalidate_acceptance_campaign` 现在要求 admission JSON 使用 canonical 字节、无重复键、
无额外或缺失字段，并严格校验 registration/seal/root/parent/remote 绑定；文件 pin 只接受
规范的 `path/size/sha256`，拒绝 traversal、控制字符、`.git`、重复路径、symlink、hardlink、
非普通文件、非 `0600` retained 文件以及非私有 `materials/` 目录。既有 campaign root 只能
用于这次只读 revalidation，不能作为新 campaign 复用。

新增 trusted bootstrap process-registration handoff 的 strict parser/verifier：拒绝重复键、
非 canonical JSON、未知字段、字节或身份绑定漂移，校验 bootstrap/target 独立执行绑定、
PID/PGID、self-digest，并能重新绑定 launch、descriptor、intent、attestation、consumption
和 registration 源记录。该 handoff 仍是 provider-free 的持久证据边界，尚未授予生产运行权限。

新增 Feature 156/157/158 provider-free acceptance matrix 和 producer lifecycle attempt matrix，
把过程、请求 broker、HTTP transport、trusted bootstrap、尝试终态、replay、gate failure、
recovery 等证据与实际 fixture 对齐，并明确 `offline-verified`、`supporting-only` 和
`integration-open` 的区别；矩阵不会把本地 fixture 晋级为真实模型验收。

新增 provider-free single-attempt gate（`91ba125`）：只有未篡改的 revalidation `ready`
结果才能创建一次性的 `attempt-started.json`；该文件使用 create-only、`0600`、fsync，绑定
admission、root/parent inode 和摘要，并明确 `provider_started=false`、
`provider_call_made=false`。重复 claim、伪造 admission 或缺少 ready gate 均拒绝；这一步仍
没有启动 provider 或发起模型请求。

本轮验证结果：

- acceptance launch + trusted bootstrap handoff + producer process lifecycle matrix + lifecycle
  matrix：**54 passed / 0 failed / 0 skipped**（JUnit：`/tmp/lunar-handoff-junit-2026092802.xml`）；
- producer process 全套：**69 passed / 0 failed / 2 skipped**（共 71 项；JUnit：
  `/tmp/lunar-producer-process-2026092803.xml`）；
- 目标文件 Ruff 与 `git diff --check` 通过。

仍开放且不能宣称已完成：Feature 142 T038 正式唯一 launch runner、T039 runtime/observation
binding 与 campaign discovery 的正式接线、T040 唯一真实 model attempt 及独立六阶段
postrun/holdout audit；Feature 156 T156-05/06/09/12/14；Feature 157 T157-05/T157-06；
Feature 158 T158-04。后续真实验收仍必须从新的 registration、材料冻结、clean `origin/main`
准入和新的 campaign root 开始，并继续遵守一次 attempt、不可 replay/fallback/repair 的约束。

## 2026-09-28 observation binding and native E2E checkpoint

已提交并推送 `9a0bbe8`、`06ddf34`、`b50ab43`。新增可信 bootstrap 到 Feature 156 的
provider-free handoff receipt，并将八项 holdout 的 runtime binding 接入 retained observation
manifest：重新读取 parent、prepared event、bundle/profile、binding receipt 和全部 probe
文件，生成 `criteria_bound` manifest/binding；发布使用 `observation/` 子目录、create-only
文件、fsync、目录链复核，失败或 deadline 后保留现场且禁止复用。新增 observation 专项
5 项通过；acceptance/registration/audit/runtime/holdout/probe/bootstrap 组合回归通过。

在文件稳定后重新运行原生离线 E2E：**224 passed / 0 failed / 0 skipped**，JUnit 位于
`.lunar-evolution/test-results/native-e2e-20260928-final/native-e2e.xml`，提交为
`9a0bbe85b324ca2a5f0e6c270e5da9319d66ae67`。这是本地 provider-free 回归，不是模型验收。
当前仍未创建新 campaign、未调用 provider、外部 producer 或 WebAgent。T038 正式 launch
runner、T040 唯一真实 attempt/postrun audit，以及 Feature 156/157/158 生产生命周期接线
仍未完成；Feature 139 保持 preparation **1/1**、primary/joint **0/1**。

## 2026-09-27 `15b8113` native holdout/runtime-binding hardening

本轮已提交并推送 `15b8113`。准备绑定现在读取完整登记、实际 prepared parent、contract、
pipeline、冻结 evaluator bundle/profile 与准备事件，严格保持预登记 criteria/material
身份和现场生成的 contract/input-table/harness/profile 身份分离。它在独立 retained workspace
中一次执行固定八项 native snapshot holdout，保留原始 snapshot/expected、typed report、
canonical projection、实际 harness 摘要、双 exit、PID/PGID observer/release 与 cleanup
证据；cleanup 不确定不能晋级 passed。所有材料在创建 root 前校验；parent/root/ordinal/probe
目录由 no-follow DirectoryChain 持有并在 callback、执行前后复核，交换、symlink、取消、
deadline 或失败后的 root 均 fail-closed 且保留现场。绑定 receipt 为 create-only、fsync、
字节/inode/mode/link-count 可复核文件。

该提交的 holdout、runtime-binding、probe、native-bootstrap、isolation 五套专项共
**82 passed / 0 skipped**，耗时 5.33 秒；JUnit 为
`.lunar-evolution/test-results/checkpoint-15b8113-focused/focused.xml`。它包含真实本地
preparation 加八项 evaluator subprocess，以及 criteria/material/harness/input/task 漂移、
retained evidence 篡改、取消、deadline 和目录替换回归。该结果是 provider-free offline
证据，不是模型 acceptance。

本轮同时固化了 Darwin native bootstrap → isolated target supporting slice：目标在 gate
释放后执行，允许 workspace 写入，拒绝 workspace 外写入、controller secret 读取和网络
连接；C 端按验证过的 target path 执行，不能用不同 argv[0] 选取未验证字节。它仍未接入
Feature 156 正式 registration/attestation/deadline/cleanup/recovery 或 Feature 157 broker。

Feature 142 T039 仍开放：binding receipt 尚未接入 observation manifest/campaign discovery；
T038 仍需正式 launch runner，T040 仍需唯一真实 attempt 与独立 postrun 六阶段/holdout audit。
旧 Feature 139 槽保持 preparation **1/1**、primary/joint **0/1**，本轮未创建新 registration、
campaign，未调用 provider、外部 producer 或 WebAgent。15b8113 之前的 native E2E 224/224 与
三阶段回归报告继续保留，但不作为 15b8113 之后完整回归的声明。

## 2026-09-27 新真实验收的离线准入入口

Feature 142 T038a 已实现并验证。`prepare_acceptance_campaign` 对真实远端 main 做有界、
非交互核验，和 clean HEAD/本地 origin/main 对齐后，再次核验 20 份登记材料并原子独占新
campaign root。它保留登记、seal、preflight、远端观测和材料快照；回执发布前后重读文件，
核对字节、inode、模式、链接数和精确目录清单。根目录一旦创建，即使写入或同步失败也
保留并拒绝重试。此入口不调用 provider，不执行 solve，也不建立真实成功计数。

临时裸 Git origin 的准入专项 **30 passed**；登记/材料/准入合计 **108 passed**，相关
审计兼容 **161 passed**，原生离线 E2E **224 passed / 0 skipped**。Ruff、compileall、
SDD 前置与 diff 检查通过。后续 T038 runner 仍需在执行前复查远端和留存证据；T039 需将
预登记判据与 preparation 实际生成的合同、evaluator/profile 和八项 probe 结果分别绑定；
T040 才是唯一真实 attempt 与独立六阶段审计。现未生成新登记/真实 campaign、未调用
provider 或 WebAgent。外部 producer 的 Feature 156/157/158 生产接线仍开放。

T039 的身份映射必须独立保留：登记 task SHA 是原文，观察 manifest 的 task SHA 是生成
合同；登记 input SHA 是 limit.json 字节，观察 input SHA 是规范化 CandidateExecutionInput
数组；登记 evaluator/profile SHA 是判据，观察/prepared event SHA 是实际 harness/profile。
不能复制字段或削弱现有审计器来让它们相等。先用 validate_automatic_solve_bundle 核验
真实 prepared artifacts，再检验合同的唯一 input/output、两条 independent hard constraints、
source python_file_count minimum=2、maximize/no metrics/no soft/execution constraints/population，
并独立运行八项固定 probes。现 _snapshot_probe 只返回 report，缺少可持久复核的双 exit/
cleanup 证据，必须补真实观测后才能发布 passed holdout receipt，不得虚构 cleanup=verified。

## 2026-09-27 新真实验收材料与预检加固

用户确定沿用历史实际 `openai-compatible` / `glm-5.2` / `chat_completions` 模型及任务。
Feature 142 新增 20 份独立验收材料：原任务/输入精确字节、独立 evaluator/profile 判据、八组
实际 probe 的输入及预期结果。登记中的 evaluator 摘要是预登记判据，不是 preparation 现场
生成的 Python evaluator；未来 runner 必须同时绑定两层身份并独立核验。

登记预检现核对全部材料的工作区字节、摘要、大小与单一已提交 HEAD 的普通 Git blob，
拒绝 Git symlink 模式和预检期间提交/工作区变化；产品/材料上限 8 MiB，manifest/seal
仍为 128 KiB。专项 **78 passed**，原生离线 E2E **224 passed / 0 skipped**；Ruff、
compileall、SDD 前置与 diff 检查通过。真实启动仍缺远端 main 实际提交核验、
新 root 原子独占、runner、运行时评分器绑定及独立 postrun 审计。当前开发分支不满足
clean `HEAD == origin/main` 门槛；本轮没有启动 provider、campaign 或 WebAgent。

## 2026-09-27 原生自动多文件 E2E 回归入口与剩余发布工作

现可用 `.venv/bin/python tools/run_tests.py --suite native-e2e --junit-dir
.lunar-evolution/test-results/native-e2e` 重复验证原生自动多文件的完整离线链路。
新入口基于现有 runner，固定七个集成套件，核对当前 checkout 导入和精确收集/JUnit 数量，
覆盖前后台 CLI、loopback HTTP、合同准备、生成、执行、独立评分、父交付、answer/resume、
取消/真实超时与后代清理、强杀恢复和仓库外 wheel 安装。不会加载历史 worktree，默认
无 `--suite` 仍运行三阶段发布回归；跳过项单独报告，预检失败不会留下旧成功 JUnit。

本轮 native-e2e **224 passed / 0 failed / 0 skipped**，runner **46 passed**。独立
Feature 112 CLI quickstart 四候选得分 **1/2/6/7**，交付 **7**，终态 resume 没有重复调用。
完整三阶段发布回归 exit 0：当前 **7586 passed / 7 skipped**，归档历史 **2294 passed**，
冻结登记 **24 passed**，三阶段均 0 failed/errors。报告分别位于
`.lunar-evolution/test-results/native-e2e-20260927-final/` 与
`.lunar-evolution/test-results/native-e2e-release-20260927/`。Ruff、compileall、Specify
prerequisites、diff check 通过；见 Feature 142 validation 与系统 readiness 顶部。

剩余发布重点：新的原生真实模型成功交付样本。Feature 139 唯一旧槽仍是 preparation 1/1、
primary/joint 0/1，不得重开。新样本需独立 task/input/evaluator/profile/8 holdout 材料、
launch runner、新 manifest/seal/唯一 campaign root、clean origin/main preflight、真实 attempt
及 postrun 审计。当前开发分支的离线通过不满足该真实登记门槛。
用户已确定新验收沿用之前的模型和任务；具体 provider/model/API-mode 与材料字节仍需在
新 manifest 中从历史记录核定和冻结，不能直接运行旧 campaign。
外部 producer 线仍缺
T158-04 可信原生 bootstrap 的正式 handoff/共享生命周期、T157-05/06 的完整出口/credential
隔离和生产 journal 保护、T156-14 正式接线，以及产物进入 admission/evaluation/archive/
delivery 的自动链路。AgentLoop/递归 Worker API 接入 automatic solve 属于可选扩展，
不阻塞原生 E2E。本轮未调用真实 provider、外部 producer、WebAgent 或 campaign。

## 2026-09-27 Feature 157 brokered HTTP worker

新增 controller-owned 的 POSIX HTTP POST transport。每个 admission 使用独立的已有标准库
HTTP worker；父进程以 admission 的绝对 monotonic deadline 限制匿名 IPC 和等待，worker 的
网络调用共享该截止时间。输入和输出均有界，取消仅在对应 worker 收到 KILL 且完成回收后
确认。若 worker 在取消前已退出而终态尚未解析，保留不确定状态，不伪造已受控超时。
broker 的结果现在显式返回成功的本地响应；失败或超时不返回响应，payload 与 response
均不进入宿主 journal。新增 loopback HTTP、阻塞 headers/body、启动及 stdin 卡住、并发、
超大输出、取消回收与迟到解析专项。

这仅覆盖主动经过 broker 的 POST 请求。producer 仍可绕开 broker；生产 journal 目录
隔离、Feature 156 正式接线和真实 provider/campaign 验收未完成，T157-05/T157-06
仍开放，不能将 `request_timeout_enforced` 晋级为生产保证。
本轮全仓离线 pytest 通过（6 项平台相关测试跳过）；Feature 157 与 HTTP/进程相关
组合回归、Ruff、compileall 和 diff check 通过。未运行真实 provider、外部 producer、
WebAgent 或 campaign。

## 2026-09-27 Feature 157 broker 取消与并发账本加固

收紧 `ControllerOwnedRequestBroker`：只有取消被接受且 handle 返回 `cancelled`，才能标记
`host_timeout_enforced=true`；取消后返回 `completed`/`failed`、非法或不可哈希状态均保留
未确认超时语义。`wait` 异常和非法状态会尝试取消；没有确认 `cancelled` 时，admission
继续保持 active，崩溃恢复会将其列为 uncertain，即使 deadline 已到。`start` 失败或返回
无效 handle 同样不伪造终态。对独立的 ledger 超时记录，恢复也保守列入 uncertain，
因为截止时间本身不证明 I/O 停止。ledger 的容量、序号、终态与快照操作现在串行；
journal 追加、关闭和绑定也有互斥保护。
新增取消竞态、异常路径及并发哈希链回归。同步接口仍依赖未来实际 transport 自己兑现
`start`/`wait`/`cancel` 有界执行，当前没有真实 provider 出口隔离或 Feature 156 正式接线；
T157-05/T157-06 保持开放。

## 2026-09-26 Feature 157 controlled transport boundary

新增 `ControllerOwnedRequestBroker` 与 `ControllerRequestTransport`/handle 协议。broker
先通过 `HostRequestLedger` 登记，再把同一个 admission/deadline 交给受控 transport；只有
transport 明确确认取消并进入终态，才返回 `host_timeout_enforced=true`。只支持轮询、返回
非法状态、取消不确认或取消后不进入终态的 transport 均 fail-closed，并保留 timeout 不确定
语义。新增成功、deadline 取消确认、取消不确认和无取消句柄回归；模块从顶层 API 导出。
这仍是 provider-free transport boundary，不是实际 provider broker，也没有完成出口隔离、
受保护生产 journal 或 Feature 156 接线；T157-05/T157-06 继续开放。本轮未运行真实 provider、
外部 producer、WebAgent、scheduler 或 campaign。

## 2026-09-26 Darwin 快照原子拒绝覆盖

共享快照发布已从可覆盖的重命名改为原子 create-only 链接；普通 producer、bootstrap、target
三种角色即使在准备检查之后出现同名路径，也不能被新快照覆盖。临时硬链接在 immutable 校验前
移除；发布中途失败仍保留 unknown/恢复语义。三角色竞争注入专项通过。正式 Feature 158
接线仍需独占批次、原生 bootstrap、真实 target handoff 和共享登记/清理/恢复；T158-04 开放。
本轮未运行真实 provider、外部 producer、WebAgent 或 campaign。

## 2026-09-26 Feature 158 双端执行字节准备

新增未导出的 `prepare_trusted_executable_pair`：同一 launch、attestation 和绝对 deadline
下分别准备 bootstrap 与 target。Darwin 返回两份独立 immutable 快照；Linux 返回两份
sealed memfd 的路径与需继承的 FD，且在 context 内持续持有。已有同名角色快照会拒绝复用；
第二端准备失败不会产出 pair，并检查已返回快照的启动前清理结果，清理不确定时报错并保留现场。
若快照已发布但创建函数尚未返回，按角色路径检测并报告同一不确定状态，不擅自删除未知 inode。
成功的 Darwin 快照需由后续正式 runner 在确认终态后清理。
这只是 provider-free 字节准备，不验证安装 allowlist、不消费 attestation、不启动进程、
不发布登记或放行 gate。尚缺原生 bootstrap artifact、真实 target handoff、Feature 156
共享登记/清理/恢复接线和完整生产验收；T158-04 仍开放。本机 Darwin 专项已通过，
Linux sealed memfd 实跑用例在本机跳过，等待 Linux CI 验证。本轮未运行真实 provider、
外部 producer、WebAgent 或 campaign。

## 2026-09-26 Feature 158 target 执行绑定登记契约

正式 trusted-bootstrap 登记现在除 bootstrap 的 `execution_*` 外，还要求独立的 target
绑定模式、快照路径、SHA-256 和字节大小。Darwin target 必须使用
`.producer-snapshots/target`，Linux target 以 sealed memfd 模式登记且无路径；跨记录校验
会将 target 大小与已核验 attestation 对齐。重新计算登记摘要也不能绕过模式、路径、摘要或
大小校验。此处只收紧持久登记契约，尚无生产 pair preparer、原生 bootstrap 和实际 FD/快照
handoff，也未接入 Feature 156 生命周期；T158-04 仍开放。本轮未运行真实 provider、
外部 producer、WebAgent 或 campaign。Feature 156/157/158 与进程所有权组合回归、
Ruff、compileall 和 diff check 均通过。

## 2026-09-26 Feature 158 Darwin 双端快照路径预备

沿现有 SDD，Darwin 批次快照现区分 `.producer-snapshots/bootstrap` 与
`.producer-snapshots/target`；普通 Feature 156 producer 继续使用
`.producer-snapshots/executable`。正式 trusted-bootstrap 登记校验要求 bootstrap 路径，
因此旧 producer 路径不能充当 bootstrap 快照。这只是双端执行字节绑定的路径预备：
当前没有生产 pair preparer、原生可信 bootstrap artifact、独立绑定的 target exec，
也未接入 Feature 156 共享登记/清理/恢复和单一 deadline。T158-04 仍开放；
现有 `python -m` fixture 不能作为生产入口。本次变更未运行真实 provider、外部
producer、WebAgent 或 campaign。

## 2026-09-26 Feature 158 fixture 恢复组身份校验

只读 fixture 恢复现在也核对终态证据中的目标启动 PGID 与持久 bootstrap 登记 PGID；
证据中的组摘要及自摘要都重算后仍不能绕过，`passed` 和 `unknown` 均 fail-closed。
生产接线审查确认当前 `python -m` fixture 只 pin 源文件，却执行解释器及可变导入依赖；
目标启动仍按原路径重开。T158-04 的下一步是单独可信可执行 bootstrap artifact、
bootstrap 与 target 各自的执行字节绑定，以及 Feature 156 共享登记/清理/恢复接线。
Feature 156/157/158 与进程所有权组合回归 **223 passed、2 skipped**；Ruff、compileall
与 diff check 通过。
本轮未运行真实 provider、外部 producer、WebAgent 或 campaign。

## 2026-09-26 Feature 158 目标进程组证据绑定

沿现有 SDD，trusted bootstrap 终态证据现保留目标启动帧观测的 PID/PGID，并校验二者与原
`target_group_identity` 摘要一致。正式跨记录校验和只读持久观察会拒绝目标启动 PGID 与
bootstrap 登记 PGID 不同的证据，即使其摘要已重算。旧证据缺少新增字段时严格拒绝，
不做隐式升级。此校验只覆盖启动瞬间的组身份；目标之后是否脱组仍未证明。
Feature 156/157/158 与进程所有权组合回归 **221 passed、2 skipped**；Ruff、compileall
与 diff check 通过。
Feature 156 正式 runner 尚未接入生产 bootstrap，T158-04 仍开放。本轮未运行真实
provider、外部 producer、WebAgent 或 campaign。

## 2026-09-26 Feature 158 登记契约与 fixture 清理授权

沿现有 SDD 增加 Feature 156 正式登记的只读可信 bootstrap 校验器：拟议登记必须精确绑定
launch/intent/attestation、bootstrap descriptor 与目标摘要、PID/PGID、OS 启动身份、恢复锁
device/inode，以及平台对应的执行字节摘要；重新计算登记自摘要的篡改也无法绕过跨记录绑定。
当前 runner 仍未生成该扩展登记，也未通过该校验器释放 gate。Feature 158 fixture 的登记文件
改名为 `trusted-bootstrap-registration.json`，避免与正式 runner 的同名不同协议登记混淆。
fixture 清理现在按 OS 启动身份复核进程所有权；身份漂移或运行中身份不可读取时拒绝发送信号。

合并专项回归 **142 passed、2 skipped**，Ruff、compileall 与 diff check 通过。T158-04 仍开放：
真实平台字节绑定的 bootstrap 启动、共享正式登记/终态证据/恢复和单一 deadline 尚未接线。
本轮没有调用 provider、外部 producer、WebAgent、scheduler 或真实 campaign。

## 2026-09-26 Feature 158 launch identity adapter

沿现有 Feature 158/156 SDD 增加 `build_trusted_bootstrap_launch`：它从已核验的 Feature 154
launch intent 与一次性 attestation 构造严格绑定的 trusted-bootstrap launch，固定映射
launch/journal/run/parent/task、intent/attestation、目标可执行文件摘要、bootstrap descriptor
摘要与单一 gate nonce。`fixture-only`、非当前平台的执行模式、attestation 摘要或字段漂移均在
入口拒绝。新增 focused 回归覆盖 fixture 晋级拒绝、正常字段绑定和 attestation 篡改；bootstrap
与 runtime 专项 **31 passed**，Ruff、compileall、diff check 通过。

这只是生产接线所需的身份边界，不是 Feature 156 生命周期接入：当前 runner 仍未启动真实
platform-bound Lunar-owned bootstrap，登记/清理/recovery 仍未共享 bootstrap evidence，T158-04
继续开放。未启动 provider、外部 producer、WebAgent、scheduler 或真实 campaign。

## 2026-09-26 Feature 156 崩溃后清理与锁身份

外部 producer 的显式恢复现在可在登记链、一次性 nonce claim、OS 进程启动身份和原生命周期锁
全部匹配时，尝试清理仍存活的进程组。默认恢复继续只读；清理另写 create-only、fsync 的
recovery receipt，执行结果始终为 unknown，不据此发布或重启。活跃控制器持锁时恢复拒绝；
锁文件设备号/inode 已绑定进登记 digest，路径被替换后不能借新锁清理旧进程，每次信号前
也复核锁路径。旧登记缺少锁身份时不能授权清理。

专项进程生命周期回归、Ruff、compileall 与 diff check 已通过；完整三阶段离线回归
为当前 7453 passed / 6 skipped、历史归档 2294 passed、固定注册 24 passed，均无失败。
trusted bootstrap 正式接线、Feature 157 实际请求 broker/超时取消/出口隔离、外部 producer
到 population/archive/delivery 的自动接线、新真实模型完整交付验收仍未完成；不能宣称生产可用。
本轮未启动 provider、外部 producer、WebAgent 或真实 campaign。

## 2026-09-25 Linux 执行字节绑定与宿主请求日志

沿 Feature 156/157 SDD，Linux producer runner 现在把已核验的可执行字节复制到 sealed
memfd，并在 `Popen` 完成前持有、继承该描述符；登记和终态回执记录
`linux-sealed-memfd` 及字节摘要。真实 Linux 上的 runner 专项 **46 passed、2 skipped**，
覆盖最终校验后替换源路径仍运行已封印字节，以及平台能力缺失时启动前拒绝。
Darwin 继续使用 immutable snapshot，其他平台仍为 prototype，Feature 156 整体
T156-11 不因 Linux 子项完成而关闭。

Feature 157 新增 controller-owned 请求计数/单调计时账本，以及逐条 fsync、哈希串联的
有界请求日志和只读恢复；崩溃时未结束的请求保持不确定。它只证明经过该入口的请求，
尚无实际 outbound broker、I/O 超时取消、producer 出口隔离或 Feature 156 正式接线，
因此 T157-05/06 与 T156-14 保持开放。两项实现均未调用 provider、外部 producer、
WebAgent、scheduler 或真实 campaign。

当前主要未完成项：Feature 156 的崩溃后授权清理与终态恢复回执、trusted bootstrap
正式接入和完整生命周期矩阵；Feature 157 的实际受控 transport；外部 producer 到
population/archive/delivery 的自动接线；以及新的真实模型完整交付验收。

## 2026-09-25 Feature 156 owner identity 登记收窄

沿现有 SDD 为 provider-free producer 登记增加 OS 观测的进程启动身份，并绑定到终态回执：
Darwin 使用 `libproc` 的微秒级启动时间，Linux 使用 boot ID 与 `/proc` start tick。
运行中清理先核对该身份；身份漂移会拒绝授权。登记完成后若墙钟已经到期，工作门保持关闭。
身份不可读时，只有原子进程已回收且该 PID 已不存在，才允许继续清理残留进程组；
同 PID/PGID 已被复用也会拒绝。恢复检查验证身份字段与回执链，仍只读，不执行崩溃后的
进程组清理。本轮 Feature 156/157/158 专项 **133 passed**，最终代码的全仓离线回归、
Ruff、compileall 与 diff check 通过。

T156-06 仍未完成：恢复时缺少可授权的 post-crash cleanup 和终态 recovery receipt。非 Darwin
执行字节绑定、trusted bootstrap 正式接入、host-observed request evidence 及完整 T156 矩阵
仍待后续。未调用 provider、外部 producer、WebAgent、scheduler 或真实 campaign。

## 2026-09-25 Feature 156 capture evidence and deadline tightening

继续现有 Feature 156 SDD，修复两个 provider-free 生命周期证据边界：当单次 stdout/stderr
读取跨过输出上限时，回执现在只对上限内前缀计算 SHA-256，同时保留 `limit+1` 饱和字节数和
截断状态；进程等待的剩余时间统一零下限，墙钟到期后不会额外获得 10ms 等待。新增跨界摘要和
截止时间单元测试，Feature 156/进程所有权/trusted bootstrap 专项回归 **96 passed**，Ruff、
compileall 通过。本轮未调用 provider、外部 producer、WebAgent、scheduler 或真实 campaign。

Feature 156 仍未完成：持久化 owner identity 还不能支持 controller crash 后的安全恢复清理，
非 Darwin 仍是 pathname-bound prototype，trusted bootstrap 仍为 fixture-only，Feature 157
host-observed request evidence 尚未接入；因此没有勾选 T156-05/T156-06/T156-09/T156-11/
T156-11b/T156-12/T156-14。

## 2026-09-24 Feature 156 producer 本地进程生命周期（开发中）

沿 Feature 154/155 的 SDD 新增 provider-free 本地 runner：一次性 nonce 在 workspace 范围内
原子消费，合作式 producer 在持久化 PID/PGID 登记前被工作门阻塞；执行使用固定的非敏感环境、
独立进程组和有界 stdout/stderr，终态写入带 digest 的执行回执。只读恢复核验登记与终态，不
自动重启。结果文件和恢复记录现在通过持有的 no-follow 目录描述符读取；墙钟截止时间从准备
开始计算，并覆盖结果文件读取。专项 **24 passed**，含跨批次 nonce、请求超额、工作门顺序、
写入失败、目录替换、重复 JSON 键和回执缺失。专项最终 **26 passed**；最终源码全仓离线
回归 **7329 passed、1 skipped**。Ruff、compileall 与 diff check 通过。

Feature 156 **未完成，也未接入默认调度**。可执行文件在最后一次核验与 `Popen` 按路径重开
之间仍可被替换；任意外部 producer 不一定遵守工作门；请求级超时尚无可信逐请求证据；主
进程先退出而后代仍活着时清理可能保持 unknown。后续需要解决这些边界及 capture/signal
故障注入后，才能连接外部 producer 和接受真实 campaign 验收。本轮没有调用 provider、
WebAgent、evaluator 或真实 campaign。

## 2026-09-24 Feature 154/155 producer launch boundary and evidence handoff

继续沿现有 SDD 完成两条 provider-free slice，并已通过项目 `.venv` 的完整回归。
Feature 154 新增声明式 `ProducerLaunchIntent`、一次性 exact-match
`ProducerLaunchAttestation` 和只读 `preflight_producer_launch`：启动意图绑定预留
`journal_id`、run/parent-task/task、完整 `CandidateIntegrityAuthority`、producer 身份、
可执行文件字节及 device/inode/mtime/ctime、argv、系统派生输出路径，以及独立的
request/max-request/output/wall-clock 预算。preflight 要求调用方显式提供 authority 与三元
身份，返回 `preflight_passed` 观察结果；它不启动进程、不写 Store/文件、不消费 plan/journal，
也不把观察结果当执行或发布授权。一次性 attestation 只为后续真实 PID/PGID 登记保留，必须
精确匹配 parent/child/task、intent、执行文件字节和 inode/时间指纹。

Feature 155 新增 `ProducerBundleExecutionReceipt`、`ProducerBundleEvaluationReceipt` 和
只读 `build_producer_bundle_publication_artifact`。它重新检查已经保留的 native plan、admission、
execution、cleanup、evaluation 和 source bytes，将成功且 cleanup verified 的多文件候选投影为
Feature 153 可发布 artifact；execution/evaluation receipt 作为 canonical sidecar 写入 staged
candidate，nested entrypoint 的 native `record.json`/`receipt.json` 与 source tree 保持相邻，旧
root layout 继续兼容。unknown/timeout/cleanup-unknown 不可投影，也不会触发重跑。

新增 focused launcher/receipt/nested staging/recovery 测试；Ruff、compileall、diff check 和
项目 `.venv` 全仓 **通过**。本轮未启动 external producer、provider、scheduler、WebAgent 或真实
campaign；Feature 154 的 T154-07（真实 process ownership/cleanup/recovery）和 Feature 155
T155-05（外部 launcher 输出接线）仍是后续功能。

## 2026-09-23 Feature 153 producer bundle publication transaction SDD

在 Feature 152 的 authority-bound admission plan 之上新增
`specs/153-producer-bundle-publication-transaction/` 规格，明确 producer bundle 进入 archive
前需要独立的批次 journal、按计划顺序的 candidate receipt、全批次 staged publication 和
fail-closed resume。规格同时绑定完整 archive/state prefix、run/task identity、population
configuration 和 island mapping，避免只绑定 archive 行而无法恢复 `PopulationStrategy`。
现有 `CandidateArchive.commit_initial_seeds` 绑定旧的 `SeedManifest`/seed receipt 证据，不能
直接接收 producer bundle draft，因此 Feature 153 暂不改旧入口或 automatic solve。该轮只完成
SDD，代码、真实 producer、provider、campaign 和 launcher 均未启动；下一步按该规格实现
journal 与 publication transaction。

随后完成 T153-01：新增 `ProducerBundlePublicationCandidate`、
`ProducerBundlePublicationJournal` 及 canonical parser/builder。journal 绑定 run/task、完整
archive/state prefix、authority、budget、population/island mapping、候选 receipt 与状态转移；
`journal_sha256` 计算时排除自身字段，严格拒绝未知字段、重复 JSON key、非法 digest/状态、
重复候选和越界 island。该 slice focused **6 passed**，Ruff/compile 通过；仍未写 archive、
执行候选、调用 provider 或接入 automatic solve。下一步是 zero-write preflight 与 staged
publication。

T153-02 随后完成：新增 `ProducerBundlePreflightReceipt`、
`preflight_producer_bundle_publication` 和 deterministic candidate ID。preflight 通过系统派生
的 `evolution/producer-batches/<journal_id>` 路径做 no-follow 检查，只读验证 plan digest、
authority/budget、journal candidate 映射、archive/state prefix、native candidate integrity
和 candidate ID 冲突，拒绝旧 `seed_handoff` 混合记录；失败不创建或修改文件。Feature 153
journal/admission/population/preflight focused **27 passed**，Ruff、compile、diff check 通过；
最新全仓回归为 **7277 passed、1 skipped**；staged publication、execution/evaluation
transaction、resume/recovery 和 delivery 仍未接线。

## 2026-09-23 Feature 152 显式 producer bundle admission descriptor

沿 Feature 150/151 的现有 SDD 新增 `ProducerBundleAdmissionItem`、
`ProducerBundleAdmissionPlan`、`build_producer_bundle_admission_plan` 和
`parse_producer_bundle_admission_plan`。该 provider-free、只读边界接收 Feature 151 的
`ProducerBundleDraft`，重新校验 native bundle digest 和规范 provenance metadata，并绑定
contract、evaluator kind/fingerprint、runner、dependency、environment authority。计划保留
bundle 输入顺序，规范化材料路径，拒绝重复 bundle ID/路径、非法路径、digest 不一致、额外
metadata、未知字段和重复 JSON key；`digest()` 对嵌套 DTO 重新解析，避免浅冻结对象被篡改后
继续产生相同身份。producer score 不进入计划，也不改变 candidate identity。

新增 `specs/152-producer-bundle-admission-descriptor/` 和
`tests/test_producer_bundle_admission.py`，API 已从 `lunar_evolution` 导出。Feature 152 只
完成 admission intent/authority binding；它不执行 candidate、不写 archive、不发布交付、不
接入 automatic solve、旧单文件 `SeedManifest` 或 launcher。后续仍需单独实现 per-candidate
execution/archive publication、批次 journal/resume recovery 与真实 external producer 验收。
Feature 152 focused **23 passed**；Ruff、compileall、diff check 继续作为提交门槛。本轮没有
调用 provider、producer、WebAgent 或真实 campaign。

## 2026-09-23 Feature 151 verified producer bundle → native population draft

沿 Feature 150 的显式 bundle bridge 继续现有 SDD，新增
`ProducerBundleDraft`、`ProducerBundlePopulationError` 和
`prepare_producer_bundle_drafts`。该 provider-free、只读适配器重新通过 canonical candidate
bundle verifier 校验 regular-file bytes、size/SHA、inode/device 和读取期间变化，再将每个已
校验 bundle 解码为原生多文件 `CandidateDraft`；entrypoint 保持为 `draft.filename`，完整的
`source_files` 映射保留，producer fingerprint/ID、bundle digest 和 envelope digest 只作为
provenance metadata，不进入本地 score 或 candidate identity。单次调用拒绝重复 bundle ID、
跨 bundle 路径复用、篡改源文件、非法根目录和符号链接根；不复制、stage、执行、评测或写入
producer workspace。

新增 `specs/151-producer-bundle-population/` 和
`tests/test_producer_bundle_population.py`，公开 API 已从 `lunar_evolution` 导出。Feature
151 只完成 projection slice；自动 external admission transaction、archive publication、
delivery、launcher/scheduler 和真实 producer campaign 仍未完成，也没有改动旧单文件
`SeedManifest` 协议或自动 solve 默认入口。Feature 151 focused **12 passed**（含 Feature
150 handoff），Ruff、compileall、diff check 通过；本轮没有调用 provider、producer、WebAgent
或真实 campaign。下一步是另行设计显式 bundle admission 到 archive/交付的契约。

## 2026-09-23 Feature 150 显式 producer 多文件分组桥

沿现有 109/142 SDD 完成 provider-free 的多文件 producer bridge。新增
`BundleGroup`、`VerifiedProducerBundle` 和 `prepare_producer_bundle_manifest`：调用方必须
显式给出 bundle ID、entrypoint 与已在 `lunar-producer-result-v1` envelope 中声明的
`candidate_source` 路径；不从目录、lineage、顺序或 producer score 猜测分组。桥接只读校验
contract/producer identity、路径/组边界、regular UTF-8 bytes、size/SHA、inode/device 与读
期间变化，并返回既有 `CandidateSourceBundle` 的 canonical digest。未分组辅助 material 会
忽略，被分组的非 `candidate_source` 会固定拒绝；不复制、stage、执行、评测、写 campaign 或
改变既有单文件 producer API/协议 bytes。

新增 `specs/150-producer-bundle-bridge/` 的 spec/plan/data-model/tasks/quickstart/validation，
README、system-readiness 和本记录同步说明：Feature 150 只完成 grouping/source-verification
preparation，OpenEvolve/Shinka 的完整 multi-file SeedManifest admission、population、delivery
和 launcher 仍未完成。focused bridge **7 passed**，producer 回归 **67 passed**，candidate
bundle 回归 **180 passed**，Ruff、compileall、diff check、公共导出和旧名称扫描通过。没有
调用 provider、producer、evaluator、campaign、WebAgent 或真实效果测量。下一步是单独 SDD 的
多文件 producer admission/完整 population 接线；不重开 Feature 139 旧槽。

## 当前协作约定更新（2026-09-16）

用户已明确允许“该 push 就 push，不用存太多”。后续完成且通过验证的工作应正常 commit
并 push 到 origin/main；历史段落中的“只在本地提交、不 push”已被这一新指示取代。
不改写冻结测量，不重跑 WebAgent。普通流程只把 Feature 069 已有的 Lunar 分数作为参考基线；
不为深度演化安排 WebAgent 对比。新的真实模型/框架效果测量仍须独立登记与固定条件。
下文按 Feature 保留历史进展；旧章节中的“下一步”以最新章节为准。

## 2026-09-22 Feature 149 独立 cleanup-v1 证据

沿 Feature 142 SDD 完成独立 cleanup-v1 离线实现。新增
`candidate_execution_cleanup` canonical parser/builder/read-only projection：cleanup receipt
绑定 launch intent/result、native/process exit、observer/release identity 和独立 process-group
absence probe；只有单一且匹配的 observer/release、`absent` probe、已知且一致的正常退出才会
成为 `verified`。失败、未知、权限拒绝、超时和不完整回调均保持 failed/unknown，PID/PGID
只存在于私有 receipt，不进入 `CandidateExecutionRecord.to_dict()` 的公开投影。

native execution evidence 现在在 runner 返回后写 `cleanup.json`，并把 no-follow descriptor
绑定进 `completed.json`；旧三文件 v1 仍可读取但 cleanup 保持 unknown。`acceptance_audit`
只有 verified cleanup 才允许 execution boundary 通过；slot auditor 可检查可选 cleanup
路径，inode/device 替换、复制目录和 descriptor 篡改均 fail closed。runner 的原有 process
result 语义保持不变，仅增加可选 exit observation callback。

Feature 149 parser/native/audit/slot 相关的九个文件选择集 **291 passed**（精确命令见
`specs/149-independent-cleanup-evidence/validation.md`）。完整三阶段回归也已通过：当前
产品 **7238 passed、1 skipped**，固定归档 **2294 passed**，冻结注册 **24 passed**，整体
exit 0；Ruff、compileall、diff check 和旧名称扫描通过。没有 provider、campaign、WebAgent、
evaluator 或历史生成源码执行。Feature 149 实现已提交并推送；GitHub Actions
[Run 230](https://github.com/vchive/Lunar-Evolution/actions/runs/35749740921) 已在 Python 3.11、
3.12、3.13 全部通过，T007 已完成。

随后仅同步文档的 Run 231 在 Python 3.12 的固定历史归档阶段偶发失败，唯一失败为
`test_preparation_ceiling_does_not_leak_between_threads` 的线程时序断言；Python 3.11/3.13
通过，且在固定历史 checkout 的 Python 3.12 上连续重跑该测试 10/10 通过。Run 230 已验证
Feature 149 产品提交三版本全绿；该历史归档抖动不改变产品或冻结证据。

## 2026-09-23 provider-free 端到端复核与当前发布边界

沿现有 142 SDD 完成一次不调用 provider 的可运行链路复核。`specs/112-automatic-bundle-evaluator/quickstart.py`
成功退出，四个双文件候选得分为 **1、2、6、7**，选择并交付 7 分候选；随后 `deliver` 与
`solve --resume` 均成功，恢复没有重复调用 compiler/evaluator/auditor 或候选生成器。
`tests/test_automatic_detach_phase_c.py` **10 passed**，覆盖真实 subprocess coordinator、准备、
生成、执行、独立评分、选择、交付、待答、继续、取消和清理；`tests/test_agent_bundle_cli.py`
与 `tests/test_agent_bundle_integration.py` 合计 **38 passed**，覆盖多文件 CLI、候选生成、独立
评测和交付边界。

这证明当前 Lunar Evolution 的 provider-free native 多文件管线和后台生命周期可运行，但不新增
真实模型样本，也不等同于 Feature 139 的六阶段 registration/holdout/cleanup 公共审计。Feature
139 的唯一真实 `attempt-001` 已在 2026-09-20 完成，结果为 preparation `1/1`、primary/joint
`0/1`，两个候选分别是 `worker_failed` 与 `malformed_candidate`；旧槽不可重跑。

当前真正的发布缺口只有三类：若要得到成功交付样本，需要新身份、新 manifest/seal、新 campaign
root 和新的真实 provider 槽；AgentLoop worker façade/递归 WorkerService 尚未接入 automatic solve
默认入口；OpenEvolve/Shinka 等外部 producer 的多文件 SeedManifest/launcher 接线及复杂跨文件、
远端运行仍属于后续能力。真实槽、provider、WebAgent 和历史生成源码本轮均未启动。

## 2026-09-22 Feature 142 provider-free registration preflight

在 Feature 148 之后继续现有 142 SDD，新增 `acceptance_registration`：canonical registration
manifest、独立 registration seal 和只读 checkout/Git preflight。manifest 固定新鲜
`attempt-001`、product checkpoint 与受控 product 文件 digest、task/input/evaluator/profile
材料、8 个有序 holdout 输入/预期字节、600/900/1860/3000 秒及 20/160k 预算、单岛单候选
单轮和 12 步上限。三组历史身份 denylist 必须非空且有摘要绑定；材料路径唯一，不能包含
registration/seal 文件或旧目录身份。

preflight 只读取已提交的 manifest/seal，拒绝 symlink/FIFO、未跟踪或篡改字节、dirty checkout、
`HEAD != origin/main`、product checkpoint 非祖先或源码 digest 漂移、身份复用和已存在 campaign
root；不会创建 root、写报告、调用 git 之外的 provider/runtime、执行 evaluator/candidate，
也不会授权 launch。manifest/seal 不包含 preflight 时间或状态，避免提交循环依赖。

新增 [registration spec](specs/142-automatic-solve-lifecycle/acceptance-registration.md)，
更新 142 real-acceptance plan/tasks/validation；provider-free registration/preflight focused
**16 passed**，与 Feature 148 request/audit 组合选择 **98 passed**，Ruff/compile/diff/旧名称
扫描通过。当前只完成离线 admission boundary；真实 launch-time material、独立 cleanup evidence、
真实 automatic multi-file acceptance 和 postrun closure 仍未完成。本轮没有 provider、campaign、
WebAgent 或生成源码执行，Feature 139 的 preparation `1/1`、primary/joint `0/1` 不变。

## 2026-09-22 Feature 148 只读语义与 holdout 审计

沿现有 SDD 完成 `audit_acceptance_artifacts` Python API：canonical request 固定 manifest、
parent/child/task、原生 plan/admission/execution/evaluation pins 与八个 holdout 声明；
只复制 SQLite/WAL 到私有快照，workspace 在原位置读取，保留 device/inode 约束。
准备、生成、唯一执行/评测槽位、执行、独立评测、选择、父交付和生命周期分别审计，
后续成功不能补齐更早的失败或未知证据。holdout 必须有有序且绑定的输入、预期与实际输出
字节、两个退出码及清理观察；审计不运行这些材料。

独立审查修复原生交付检查会隐式恢复 archive 的问题：只读 CandidateArchive/PopulationStrategy
不创建目录、不恢复 seed、不绑定 runtime callback，并拒绝写入口。准备阶段额外严格核对
登记的 600/900/1860 秒预算；父生命周期要求 explicit 3000 秒、唯一 orchestration attempt，
并按 SQLite 插入顺序确认 child success → delivery → task success → parent success → terminal。
取消或预算失败后的晚到成功不被接受。

最终专项 **422 passed**，Feature 147 共享选择集 **58 passed**。中间专项一项失败已确定是
fixture 的最后 SQLite writer 被 GC 回收触发真实 WAL checkpoint；保留原失败日志，增加
强制 GC 复现并显式管理 fixture 连接，产品严格快照不放宽。完整当前阶段检查点
**7146 passed、1 skipped**；归档历史 **2294 passed**；冻结注册 **24 passed**，三阶段 exit 0。
当前产品阶段在最后的预算绑定、slot 补充和 fixture 修补前收集，这些改动由最终 422 项覆盖。
详细检查点与 CI 状态见 [148 validation](specs/148-artifact-lifecycle-holdout-auditor/validation.md)，
不能把早期完整回归描述成最终源码的完整回归。Ruff、compileall、SDD 只读检查、diff 和
当前仓库旧名称扫描通过；`.specify/feature.json` 不变。

当前 native execution v1 没有独立 cleanup observation，即使其余记录成功也必须返回
`execution_cleanup_unknown`，因此本 API 当前不会返回 primary/joint eligible。下一步是
独立清理证据、launch preflight/登记封存与新身份下的真实自动多文件端到端验收。审计本身
不会调用 provider、启动 campaign、写数据库或修改验收计数。本轮无真实 provider、campaign、
WebAgent 或历史生成源码执行；Feature 139 仍为 preparation `1/1`、primary/joint `0/1`。
API 使用与约束见 [148 quickstart](specs/148-artifact-lifecycle-holdout-auditor/quickstart.md)。

## 2026-09-22 Feature 147 验收证据观察与目录审计

沿 Feature 142 的 real-acceptance plan 增加 provider-free 的 observation manifest 和只读
六阶段 receipt observer。它固定登记计划中的请求/墙钟/token 预算，要求 canonical JSON、
manifest digest、生成 receipt 绑定、12 tool-step 上限、顺序前缀和失败终态；结构链闭合只
返回 `chain_complete`，`validation_scope=receipt_chain_only`，preparation/primary/joint
均保持 `0/1`，不能作为真实 launch preregistration。

同时增加 campaign directory byte inventory/audit：descriptor-relative no-follow 读取，逐文件
inode/大小/mtime/ctime/SHA-256 复核，目录项竞态、软链接、FIFO、超大文件和过深目录均 fail
closed。审计不打开 SQLite、不执行候选源码/evaluator、不调用 provider，只确认保留字节仍与
inventory 相符。Feature 147 新增 focused **38 passed**；与本轮 worker/Store/AgentLoop 选择
集组合 **206 passed**；Ruff、compileall、diff 和旧名称扫描通过。

后续独立审查补修一次性 generation iterator 绕过第二轮摘要检查、failed/unknown 混淆和
异常类型泄露；目录扫描增加 8192 总目录项上限、第二遍全树元数据核验及完整 fd 释放。
新 focused **58 passed**、同一组合 **226 passed**。inventory 要求静止目录，并非原子快照。
本次三阶段回归实际为当前 **6777 passed、1 skipped**，归档 **2294 passed**，冻结注册
**24 passed**，整体 exit 0；JUnit 和日志保存在
`.lunar-evolution/test-results/feature147-hardening/`。
Feature 148 的 artifact/lifecycle + 8 holdout 语义审计规格已完成，代码尚未实现；准确测试与
后续任务见 [147 validation](specs/147-acceptance-evidence-observer/validation.md) 和
[148 tasks](specs/148-artifact-lifecycle-holdout-auditor/tasks.md)。

真实 artifact/lifecycle semantic auditor、八个 holdout auditor、launch preflight 和真实
provider acceptance 仍未完成；Feature 139 的 preparation `1/1`、primary/joint `0/1` 及
历史冻结证据保持不变。本轮没有 provider、campaign、WebAgent 或生成源码执行。

## 2026-09-22 Feature 146 有界递归 worker 生命周期

沿现有 Feature 143 SDD 完成 `specs/146-recursive-worker-lifecycle/`。WorkerService 和 Store
统一将递归深度限制为 32；递归配置要求 `max_workers >= max_depth + 1`。AgentLoop worker
工具现在只能在运行中的父 worker 下创建子 worker，父状态检查与 child 插入在 Store 的
`BEGIN IMMEDIATE` 写事务中串行化，取消竞态不会重新启动已停止的 child；祖先遍历使用
服务配置深度，`wait_worker` 受 AgentLoop 总执行截止时间约束。结果读取仍只允许当前
worker 的后代，子 workspace 和 envelope 保持隔离。

新增三层 AgentLoop spawn/wait、深度和容量拒绝、父状态准入、递归取消、结果隔离、私有
workspace 及 deadline 回归，并固定父准入写事务顺序、未启动 child 的取消终态，以及取消父
下的 child resume 拒绝（父成功后仍可恢复）。Feature 146 focused **20 passed**；相关
worker/Store/AgentLoop 选择集 **168 passed**。Ruff、compileall、diff 检查通过；SQLite 仅使用现有 schema 的新鲜
fixture，无新增 migration。准确结果见
[`specs/146-recursive-worker-lifecycle/validation.md`](specs/146-recursive-worker-lifecycle/validation.md)。
本轮未调用 provider、campaign、WebAgent 或外部 producer，自动 solve 和真实模型端到端仍未
宣称完成。`ebde3a4` 的 GitHub Actions Run 225（[35698100175](https://github.com/vchive/Lunar-Evolution/actions/runs/35698100175)）
已在 Python 3.11/3.12/3.13 全部通过；Run 224 的失败属于缺少 resume guard 的中间提交，已由本提交修复。

## 2026-09-22 T009 交付中断与 CI 修复

`873d985` 已推送；进一步独立审查发现观察超时锁未释放、恢复重复登记、取消遗留 staging、
输出提升未计预算等边界，已在后续工作树修正。交付独占锁贯穿暂存到提交，等待另一观察者
时不持控制器锁；恢复前清理本 attempt 的部分批次，输出写入前登记精确归属，取消后清理
遗留文件和账本。新增 9 项故障回归均通过；最终三阶段回归通过：当前 **6722 passed、1 skipped**，
归档 **2294 passed**，冻结注册 **24 passed**，整体 exit 0。

前一提交 `9213f01` 的 Linux CI 失败是真实保留结果：两版本因 `<0.30s` 断言过紧，
3.12 因 0.05 秒预算可能在 runtime 启动前耗尽。现改为进程 release 握手与受控时钟，
验证事件顺序而不依赖机器启动速度。修复已提交为 `0adb637` 并推送；其
[Linux CI](https://github.com/vchive/Lunar-Evolution/actions/runs/35634053012) 已确认
Python 3.11、3.12、3.13 全部通过。

系统仍未全部完成：Feature 139 真实完整交付仍为 preparation 1/1、primary/joint 0/1；
自动 solve 接入 WorkerService、递归 worker、外部 producer 的完整调度和真实框架验收仍未
完成。本轮没有 provider/campaign/WebAgent 执行。

## 2026-09-22 AgentLoop worker 工具 façade

沿 Feature 143 增加一个 opt-in、worker-scoped 的 AgentLoop 工具桥：WorkerService 执行
RuntimeAgentAdapter 时注入准确的 owner/parent worker 上下文，模型只在该上下文中看到
`spawn_worker`、`wait_worker`、`cancel_worker`、`read_worker_result`。子 worker 继续由
Store 的 owner/depth 校验和 WorkerService 取消树管理；wait 是有界、非终态观察，并在轮询间
检查父 attempt 的 continuation guard。结果只返回有界文本/metadata，子 worker 私有产物不
直接进入父 workspace。

新增 `tests/test_agent_worker_tools.py` 3 项 provider-free 回归：普通 AgentLoop 不暴露
worker schema、owner/parent/depth 和结果读取、取消打断 wait，以及 RuntimeAgentAdapter 内的
实际 spawn→wait 闭环。普通 `run_agent`、自动 solve、候选生成和 CLI 默认路径未接入；真实
provider、campaign、WebAgent 和 139 primary/joint 结果均未改变。

上一轮提交的 Linux 矩阵中，Python 3.12 仅在 `test_resume_workers_share_one_wall_clock_budget` 失败，
表现为 0.25 秒测试预算在 CI 文件写入和启动抖动下被提前耗尽；控制器实现仍符合 Feature 137 的
“一次 resume 共用一个 deadline”约定。本地复核确认这是测试夹具的真实墙钟依赖，不是生产路径的
新回归。现将该夹具改为已有受控单调时钟，并由模拟 runtime 显式推进 0.05 秒延迟，保留第二个
请求获得剩余预算的断言，避免 Python 版本和机器负载决定终态。聚焦 7 项通过；提交 `3d26116`
后的 [Linux CI Run 221](https://github.com/vchive/Lunar-Evolution/actions/runs/35692074592)
已确认 Python 3.11、3.12、3.13 矩阵全部通过。

本工作树完整回归收集 6726 项，结果为 **6725 passed、1 skipped**；Ruff、compileall、diff
检查和旧名称扫描均通过。该回归仍是 provider-free 本地验证，尚未宣称真实模型或框架端到端
成功。

## 2026-09-21 自动多文件后台执行（Feature 142 Phase C，发布验收完成）

继续原 SDD，实现 `solve --evolve --multi-file --detach`、`solve --resume --detach`、
`resume --detach` 和 `answer --detach`，都返回同一父任务。后台子进程继承已有 workspace 锁，
父进程先原子登记 PID/PGID，再允许子进程工作；没有启动与认领之间的空窗，也没有快速退出后
父进程晚写登记。策略从原 `evolution_requested` 恢复，凭据只通过环境传递。

答案在锁内只接收一次，启动失败保留答案供显式 resume；等待用户输入会退出后台进程。
可恢复 preparation 的旧失败诊断保留，`launch_status: accepted` 单独表达本次启动成功。
终态继续不创建 worker。强杀后的显式恢复需先确认旧协调进程退出，清理所登记的工作组后
才能恢复 intake；不确认存活状态或清理失败就拒绝启动。

已通过 10 项实际 Python 子进程/本地 HTTP fixture 验收、28 项新 CLI 边界测试，以及
87/220/101 项相关兼容回归。实际进程覆盖前后台同等交付、待答退出、两类 resume、取消、
强杀恢复、候选独立进程组回收和并发排他。另有 35 项锁/登记、20 项 worker 恢复/释放和
7 项启动故障测试；新增共 100 项。独立审查及完整三阶段回归通过：当前 **6684 passed、
1 existing skipped**，历史 **2294 passed**，原始注册 **24 passed**，整体 exit 0。
产品 `ff1edcb` 已推送到 `origin/main`，[Linux CI](https://github.com/vchive/Lunar-Evolution/actions/runs/35568522333)
的 Python 3.12/3.13 全部通过；3.11 在一项既有 attestation 正例失败。受控 GC 已复现源
SQLite 自发 checkpoint 被严格快照正确拒绝，但未捕获首次 CI 的具体交错，产品校验不放宽。
测试现显式保持连接，新增两个 GC 时点，3.11/3.13 各 86 项定向通过，独立审查通过。
首次 CI 失败完整保留；测试补丁 `ad89b50` 已推送，
[后续完整 CI](https://github.com/vchive/Lunar-Evolution/actions/runs/35570899139) 已于
2026-09-21 07:24:13 UTC 核验 Python 3.11、3.12、3.13 的安装、完整三阶段回归、报告保存
和静态检查全部通过，142 T028 已关闭。产品和 tools 字节仍与 `ff1edcb` 完全一致；新增的
两个 GC 参数令当前收集为 6687 项，不改写上面的本机 6685 项检查点。精确记录见
[142 validation](specs/142-automatic-solve-lifecycle/validation.md)，使用方式见
[quickstart](specs/142-automatic-solve-lifecycle/quickstart.md)。

131/134/139 的 188 个文件、781341 字节和全部 SHA-256 再次复核一致；没有真实 provider
请求、历史生成代码执行、新 campaign 或 WebAgent 重跑。真实完整交付验收仍未完成；143 T009
单任务前台 worker consumer 已完成，139 的 preparation 1/1、primary/joint 0/1 不变。

143 T009 已按原 SDD 完成显式选择的前台 CLI `delegate` 单任务消费路径：run/task/worker
持久关联、输入与产物交接、独立等待预算、父取消、中断恢复、结果 envelope 和重复观察者
幂等交付均已接入并验证。AgentLoop、自动 solve 和递归 worker 仍不在此 bounded slice 内。

## 2026-09-21 项目统一命名（Feature 145）

用户要求当前仓库统一使用 **Lunar Evolution**。本轮沿 SDD 新增
[`specs/145-lunar-evolution-identity/`](specs/145-lunar-evolution-identity/spec.md)，完成实际包名、
安装命令、配置和入口迁移：发行包/唯一命令 `lunar-evolution`，Python 包及模块入口
`lunar_evolution`，用户配置前缀 `LUNAR_EVOLUTION_`，默认状态目录 `.lunar-evolution`。
不保留旧命令别名或环境变量回退；已有 execution-only `LUNAR_*` 协议变量仍按原义使用。
用户已改远端名称，本地 origin 已同步到 `git@github.com:vchive/Lunar-Evolution.git`。
本地 checkout 目录暂仍为 `/Users/liminghan/Documents/lunar_agent`。

提示词、HTTP 标识、profile、协议命名、公开 digest API 和 detached 子进程入口均已同步。
`benchmark_case_content_digest` 使用新的 `lunar-evolution-case-v1` 域，不能把旧命名空间下的
hash 当作等价值。外部系统用 reference engine/benchmark 中性说明，保留真实归属。

为不改写历史封存证据，844 个原始历史文件（5235354 字节）从当前发布树退休，固定在
`c6947fd`；[历史索引](docs/history-archive.md)保留路径、提交和逐文件校验值。
2294 项历史回归在仓库外的固定工作树运行，原 24 项注册回归仍用 `5560eb9`，不丢测试、
不改封存 hash，也不把旧测量包装成改名后的新效果。旧章节术语已统一，原始命令和证据以
索引中的固定 Git 版本为准。Git 历史不改写。

本机原状态、运行证据、旧开发环境、缓存和构建目录已原样保存到
`/Users/liminghan/Documents/lunar-evolution-archive/20260921-identity-c6947fd`。
其中 `runs-and-evidence` 是原运行资料，`legacy-state` 是更早的本地状态。独立复核确认
131/134/139 的 21/97/70 文件与全部 781341 字节均匹配原 SHA/size，源码 tar 的 1973 个
Git blob 也全部一致。搬移不证明原绝对路径或 inode 绑定可续跑；普通 `--home` 会初始化所选
工作状态，不应拿唯一归档副本当可写工作区。

全新 wheel 在仓库外环境的 5 项安装验收已通过，包含真实 detached mock 子进程；runner
34 项、CLI/effect 146 项通过。最终产品 `3307fcc` 已推送，本机当前套件 6585 passed、
1 existing skipped；历史 2294 passed，原固定注册 24 passed。回归中发现并补修了进程清理
的两处竞态，235 项相关回归和 100 次真实超时、100 次真实取消均通过。当前 1137 个受控文件
及路径的旧名称匹配为零，链接、静态检查和 SDD 检查通过。
原首跑失败与历史观察器的偶发诊断缺失均如实保留，历史源码不改写。
最终 [Linux CI](https://github.com/vchive/Lunar-Evolution/actions/runs/35559887780) 已于
2026-09-21 04:30:58 UTC 确认 Python 3.11、3.12、3.13 的安装、完整三阶段回归、报告保存
和静态检查全部成功。精确结果记录在
[145 validation](specs/145-lunar-evolution-identity/validation.md)。本轮无 provider 请求或新
campaign，139 仍为 preparation 1/1、primary/joint 0/1；142 Phase C、143 T009 和真实完整
交付验收仍是后续开发工作。

## 2026-09-21 候选响应协议与失败诊断（Feature 144）

按现有候选生成架构继续 SDD，新增 `specs/144-candidate-response-reliability/`，修复多文件
JSON 输出要求与通用助手最终总结指令之间的冲突。bundle request 显式携带响应协议，支持的
runtime 仅在本次请求副本中应用；普通调用、自定义约束和持久 history 不被改写。旧 runtime
继续从完整 prompt 接收约定；不新增请求、重试、工具或预算。prompt 提供两个可被现有 parser
接受的格式示例，明确 `change_tags` / `target_metrics` 是数组且整个 experiment 可省略。

严格 parser 和独立评测未放宽，scratch 源码不能替代最终响应。解析拒绝现在保留已观察的
预算消耗；失败回执保存有界 phase，以及仅从仓库已验证异常类型投影的 `failure_cause`。
三个运行时旧失败名称规范化后可以正常入库；旧调用的诊断、未完成的 running 观察或外部
自报原因不能冒充本次失败事实。runtime 完成只补 metadata，仍须 parser 接受才发成功回执；
同一次失败只发一条回执。旧 schema 1 的成功字段、事件身份和无新字段的历史 payload 不变。

新增专项 100 项和共享回归 297 项通过，独立审查发现的重复回执/外部原因伪造已修复。
完整双阶段当前 8848 passed、1 skipped、24 deselected，冻结 123 阶段另有 24 passed，exit 0。
最终小幅防御性改动有 100 项复验；完整回归的代码检查点、CI 和证据范围见
[144 validation](specs/144-candidate-response-reliability/validation.md)。
最终产品 `c6947fd` 的 [Linux CI](https://github.com/vchive/Lunar-Evolution/actions/runs/35556293182)
也已确认 Python 3.11、3.12、3.13 完整测试和静态检查全部通过。
本轮没有 provider 请求或新 campaign，也不修复或重放历史生成代码；131/134/139 冻结结果不变。
下一步是新固定条件下的真实候选完成与前台完整交付验收。142 Phase C 自动后台入口已完成，
143 T009 单任务前台 consumer 也已完成；不能把这轮离线通过描述成真实成功率提升。

## 2026-09-21 worker 修复与发布验证

继续现有 143 SDD，已完成独立执行 adapter/runtime、精确 attempt 取消/释放、排队取消准入、
实际 PID/PGID 登记清理、服务活性锁与限定 owner 的恢复。第二个服务不再把活动 worker 误标
为 `lost`；旧 attempt 的结束和服务关闭不会影响其他服务的新 attempt；resume 的消息快照与
启动认领在同一事务消费。登记异常即使被旧 runtime 吞掉，也会先停止对应执行且不能报成功。
未确认的清理保留进程登记并阻止继续。

Store migration 8 保留旧记录；旧记录缺少 owner 或锁证据时不自动判为中断。新 factory 接口、
显式本地 API 与恢复限制见 [143 quickstart](specs/143-local-worker-lifecycle/quickstart.md)。
`send` 仍是排队供显式 resume 消费。T009 单任务前台 `delegate` 已迁移；CLI 的 AgentLoop
和递归 worker 不会因为本轮接线就自动具备多 worker 工具。

最终共享回归 260 项通过；独立审查通过；完整当前回归 8708 passed、1 skipped、24 deselected，
冻结 Feature 123 阶段 24 passed，双阶段 exit 0。报告目录为
`.lunar/test-results/feature143-final-verified-20260921/`。本轮没有 provider 请求、新真实
campaign、WebAgent 重跑或历史生成源码执行，131/134/139 的冻结结果不变。

CI 诊断已由 `c22bd37` 推送：保留有限日志和 JUnit，公开有界失败摘要，并让 Python 三版本
独立完成。旧 [run 35522272395](https://github.com/vchive/Lunar-Evolution/actions/runs/35522272395)
在 Linux 3.11 测试步骤失败且没有公开具体日志；新
[run 35523896293](https://github.com/vchive/Lunar-Evolution/actions/runs/35523896293) 三版本均报 96
项失败。公开摘要定位到候选执行；本地复现确认符号链接形式的 shell 被安全检查拒绝。
正向 fixture 改为记录解析后的真实可执行路径，164 项定向回归通过，修复 `93469e7` 已推送；
产品安全检查未放宽。该修复矩阵的候选执行失败已消失，仍暴露四项旧测试环境依赖，
Python 3.12 另有一项间歇性快照失败。后续已修：CI 创建与身份检查一致的 `.venv`；三个历史链
单测在核对真实 tracked seal 后使用显式临时合成链，保留原验证函数和负测；receipt 测试明确
管理本身的 SQLite 连接，防止 GC 在快照中触发 checkpoint。193 项历史链/负测、41 项身份/
诊断、两个 Python 版本各 76 项 attestation 及 250 项相关回归通过。未改产品安全检查或历史
测量记录，也未上传八份私人 campaign 文件。最终修复提交 `8e1e089` 的
[Linux CI](https://github.com/vchive/Lunar-Evolution/actions/runs/35526731156) 已于
2026-09-21 02:05（北京时间）确认 Python 3.11、3.12、3.13 全部通过完整双阶段测试、
报告保存及静态检查。后续仅同步验收文档，产品、测试和 CI 配置保持该已验证提交的字节。
本轮 worker 修复与跨平台回归已收尾。

剩余重点是候选完成可靠性、新的前台真实完整交付验收、
142 Phase C 自动后台入口，以及 143 T009 consumer 接线。外部 OpenEvolve/Shinka 多文件接线
和真实框架验收属于后续能力。143 T009 不构成 142 的依赖。完整清单见
[系统评估](docs/system-readiness-20260916.md)。历史 139 已结束，不重开；104/133 已有后续
实现、002 已替代、094 漏勾已有验收，不把历史清单误算成新开发任务。

## Feature 143：本地多 Agent worker 生命周期（2026-09-21，本地生命周期验收完成）

T009 foreground consumer is now complete in the same SDD. `lunar-evolution delegate` claims one
ready task, durably binds it to a worker attempt before execution, persists a bounded result
envelope, verifies and materializes artifacts, reuses existing evaluation/settlement, and
serializes cancellation against delivery. CLI `--wait-timeout` uses a durable child host and
returns `running` without stopping execution; a later invocation can reuse the active binding.
Bind failures, path traversal, ancestor symlinks, missing/tampered artifacts, late delivery,
cancel races and owner-scoped lost recovery have provider-free regression coverage. The focused
T009 suite passed 44 tests; Ruff, compileall and diff checks passed. This does not claim provider,
campaign, WebAgent or automatic solve end-to-end success. AgentLoop, recursive workers and the
separate automatic-solve background phase remain out of scope.

首版本地 provider-neutral 控制面提供 `dispatch/send/list/wait/resume/cancel`、独立
Worker/WorkerAttempt、owner/depth、双维 phase/outcome、结果单出口、大结果 SHA-256 引用、
级联取消和 `lost` 恢复。首轮 focused 为 8 项，后续基线为 9 项；原 fixture 未覆盖共享 adapter
误取消、第二服务误恢复和排队取消后仍执行三个反例。本轮在同一 SDD 中补修复和永久回归，
保留首次记录于 [validation](specs/143-local-worker-lifecycle/validation.md)。

每个 attempt 现在独占可取消执行实例，Command 和 Runtime adapter 均接实际进程回调。
服务取得本地 owner 锁后才认领任务，显式 reconcile 只处理 caller 的已确认中断 owner；
缺证据和清理失败均保留记录。真实本地子进程回归覆盖独立组、父子级联、无关进程保留、
登记异常、清理失败和关闭；并发 fixture 覆盖跨服务 close/resume、迟到回调及输入原子消费。
这些离线结果不能代替 T009 用户入口集成或真实模型端到端闭环成功。

## Feature 142：自动多文件 solve 生命周期（2026-09-20，Phase B 进程清理完成）

不新开 SDD，继续沿用 `specs/142-automatic-solve-lifecycle/`。本阶段把
`--solve-wall-timeout` 接入 `solve`、`resume`、`answer`，限制为原生自动多文件流程，校验有限
正数范围和模式，并在 runtime、Store mutation、preparation 或答案工件之前拒绝非法值。
新的自动 handoff 持久化 `automatic_lifecycle_version=1`；显式策略才写入
`solve_wall_timeout` 与 `solve_wall_timeout_source=explicit`。续跑恢复精确值并拒绝不匹配、
legacy handoff 注入和损坏 marker；省略值不隐式增加 solve 总时限，旧 handoff 不补写新生命周期。

前台 `solve`、`solve --resume`、`resume` 与 `answer` 现在共用自动编排入口。一次活动执行从
合同 intake 开始共享同一个 monotonic deadline，覆盖 preparation、候选生成、本地执行、独立
评分、选择和父任务交付；每次请求只收窄为原阶段上限与剩余时间的较小值，不重置 deadline。
这不是跨多次 resume/answer 累计的 lifetime budget：等待用户输入结束本次活动执行，合法显式
继续使用同一持久策略启动新 execution；已耗尽或其他终态的 run 不能借继续操作补充预算。
控制对象和临时 timeout 不进入冻结的 profile、contract、plan、receipt 或候选身份。

合同接受后创建或复用唯一 durable parent orchestration task，普通 scheduler 不会领取它，
generated plan 被替换也不会使 parent 提前成功。parent 贯穿 child 与 delivery 保持 running，
只有验证交付成功才完成；预算失败、取消和已有终态遵循 Store winner，晚到成功与新输出提交
不能覆盖它。recoverable preparation 仍保持 effective failed / persisted nonterminal 的恢复契约。
同一 parent 以进程内 owner 和跨进程 `flock` 排他；answer 在写答案工件前取得同一锁，避免重复
继续。终态 continuation 不新增候选、交付或 worker。

`solve`、`answer` 与只读 `status` 增加受限 `solve_execution`：execution ID、active-execution
scope、持久策略及来源、固定阶段和 stopping reason。它不暴露实时 monotonic 剩余量，不推断
远端请求是否完成，也不把任意异常文本作为公开状态。损坏准备历史仍在新增观察或 attempt 前
拒绝。定向生命周期、状态与兼容回归已通过。最终双阶段全量回归通过：当前套件
`8636 passed, 1 skipped, 24 deselected`，冻结 Feature 123 阶段 `24 passed`，两阶段均
exit 0；2026-09-21 补跑报告位于 `.lunar/test-results/feature142-phase-b-20260921/`。

Phase B 已完成：父取消只沿严格 reciprocal parent/child link 传播，并接入 evolution predicate；
candidate、evaluator、snapshot probe 和 runtime 均登记实际 PID/PGID，清理按独立进程组执行，
失败时保留未释放 ownership 防止新阶段覆盖。迟到模型响应、deadline/cancel 竞态、child 尚未
建立、leader 退出而后代仍在、重复组和 cleanup callback 失败均有本地 fixture 覆盖。定向
Phase B 回归 146 项全部通过。Phase C 自动后台执行未开放，automatic `--detach` 继续明确拒绝。
Feature 143 的 Worker/WorkerAttempt 可复用但不能替代这些验收，143 T009 显式 delegation consumer 迁移不阻塞
142。本阶段没有 provider 请求、真实 campaign、WebAgent 重跑或历史测量改写；Feature 139
preparation `1/1`、primary/joint `0/1` 保持不变。

## Feature 141：原生自动多文件 CLI 显式候选预算（2026-09-19，离线完成）

按 SDD 实现 `solve/resume/answer --candidate-generation-max-steps`，仅适用于原生自动
多文件演化。范围为 1–200；显式值与来源写入 handoff，继续时恢复并拒绝改值、旧 handoff
注入和模式切换。未传选项保留旧行为，不给单文件、显式 profile、standalone bundle 或
外部 producer 隐式增加预算。生成器取得不可变预算，timeout 使用持久的候选请求 timeout，
每次调用派生独立 budget ID，完成记录绑定对应 candidate/source identity。

同时修复较低 ModelProfile 上限与完成 receipt 的计数不一致：实际执行仍遵守较低上限，
只有完整、非负、算术一致且不超过候选 authority 的 runtime 计数才能投影为 authority
剩余步数。失败诊断保留原 effective ceiling；整批超预算继续在任何工具执行之前拒绝。
Feature 140 的持久生成 receipt 已由 `741900a` 推送，Feature 141 产品提交 `87d86d9`
也已推送，将它接入普通多文件 CLI。

409 项 focused 回归通过；全量当前 8166 passed、1 skipped、24 deselected，固定历史
24 passed，双阶段 exit0。静态检查、Specify、独立审查和 Feature 131/134 历史 inventory
通过。Feature 140 遗留的历史固定版本验证也已收尾。具体验证记录见 `specs/141-native-multifile-cli-budget/validation.md`。
没有 provider 请求、真实 campaign、历史生成源码执行或 WebAgent 重跑。

以下是 Feature 139 真实运行前的离线检查点，保留作历史上下文。其登记前证据链、
registration/inventory、worker/observer/supervision、实际 retained summary、文本 stdout
捕获及 holdout_gate 失败投影已完成离线集成和独立复核。
B001–B011 与请求/阶段时间关联漏洞均已修复；本轮完整双阶段回归通过。范围见
[139 预登记审计](specs/139-real-multifile-closure/preregistration-audit.md)。
当时离线测试通过不代表已登记；后续真实登记和运行结果以本节下面的 Feature 139 最终记录为准。

## Feature 138：公开状态投影与 preparation 恢复契约（2026-09-19，离线完成）

已完成状态投影与显式 preparation 恢复准入。CLI/JSON 现在同时公开 effective `status`、
持久 parent `run_status`、`preparation_status`、`preparation_recoverable` 和受限
`reason_code`；读取不修改 Store，parent 的终态、evolution/materialization 失败和
preparation 失败按固定优先级投影。损坏 parent/attempt、重复 start、未绑定失败记录、
取消/终态/已准备 parent 均在模型调用和新 attempt 之前拒绝；合法 runtime/wall/local/
capability 失败保持兼容恢复，预算修正后允许显式 `budget_exceeded` 重试。

离线 recovery/request/wall/capability/local diagnostics 聚焦套件全部通过，包含新增的
malformed-stage 回归；状态投影测试 4 项通过。Ruff、compileall、Specify 前置和 diff 检查
通过。双阶段全量回归 exit0：当前 `7963 passed, 1 skipped, 24 deselected`，固定 Feature
123 阶段 `24 passed`。Feature 131
保留 21 文件/155485 bytes，Feature 134 保留 97 文件/327394 bytes，文件集合、大小和
SHA 均与 evidence 一致；没有 provider 请求、campaign 恢复、evaluator 调用或生成源码执行。
规格与验证边界见 `specs/138-status-projection-recovery/`。

Feature 139 的唯一真实槽已经完成：preparation `1/1`，primary/joint `0/1`。17 次请求均
HTTP 200，已知用量 135344 tokens；两个候选生成回执分别为 `worker_failed` 和
`malformed_candidate`，没有 completed candidate、执行、独立评分、选择、父任务交付或
holdout。不能追加旧槽、改写 Feature 131/134，或安排 WebAgent 对比。详见
`specs/139-real-multifile-closure/postrun/report.md`。

## Feature 139：真实自动多文件闭环验收（2026-09-20，唯一真实槽完成，闭环 0/1）

唯一登记为 `registration-139-real-multifile-closure-50min`，campaign root 为
`.lunar/real-automatic-multifile-closure-20260920-50min`，产品固定为 `87d86d9`，登记提交为
`60efead`，manifest SHA-256 为 `12c62065...f0d7`。阶段证据按 preparation、候选
parser-gated completed、隔离执行、独立评分、有效性优先选择、父任务交付严格串联；缺失或
冲突的前置 receipt 不能由后续结果补齐。

实际注册条件为普通请求 600 秒、preparation 请求 900 秒与 wall 1860 秒、全程 wall 3000 秒、
最多 20 次请求、160000 observed tokens、每候选 12 tool steps 和 8 个 holdout。一次性槽已
结束，不允许 retry/resume/repair/replacement；Feature 131/134、WebAgent 和外部 producer 均
不重开或比较。

离线 campaign/ledger、registration/trust-root/inventory、worker、observer、runner、supervision
和 retained summary 已完成实现与独立复核。B001–B011、请求 effective timeout 越界、准备
trace 与请求脱离、阶段晚于 worker 终点，以及合同请求错误使用 900 秒上限均已修复并负测。
summary 消费原生生成回执、请求与六阶段 trace、执行/评分/选择/交付原物；缺失或冲突不能
由后续产物补齐。worker 使用独占 UTF-8 捕获，失败槽不可再次进入，holdout_gate 失败为零
holdout 且可正常汇总；只读分析不调用 provider、候选或 evaluator，也不修复保留现场。

直接原生 CLI 离线夹具仅替换 HTTP 响应，已完成 5 次请求、2 个 completed candidates、
8 项 holdout 和父任务完整交付，质量 3/3。Feature 139 的 363 项测试已在本轮全量中全部
通过。`tools/run_tests.py` 双阶段 exit0：当前 8409 passed / 1 skipped / 24 deselected，
耗时 668.93 秒；固定 Feature 123 阶段 24 passed，耗时 22.92 秒。JUnit 位于
`.lunar/test-results/feature139/{current,frozen123}.xml`。
全 src/tests/139 的 Ruff、compileall、Specify 与 diff 检查通过。Feature 131 保留 21 文件 /
155485 bytes、134 保留 97 文件 / 327394 bytes 的集合、大小、SHA 均未变；Git 跟踪历史
文件分别 15 / 21 份，与 `57bd00d` 一致。详见 `specs/139-real-multifile-closure/validation.md`。

全量启动后，登记清单另补 Feature 113 runtime guard 和 Feature 134 合成测试 fixture 的
覆盖；该窄改动经 18 项 registration_store、静态与最终清单核验通过，不声称全量重新加载。
T007 离线验证、T008 登记与 preflight、T009 唯一真实运行、T010 单次 summary/独立审计均已
完成；结果为 preparation `1/1`、primary/joint `0/1`，监督耗时 811.740448 秒，native/process
exit 均为 1，cleanup 通过。真实结果与限制见 `specs/139-real-multifile-closure/postrun/`；
后续候选生成可靠性工作应独立明确规格，保留 strict parser，并补 typed worker failure 与更可靠的候选最终
响应协议。此处保留 Feature 139 的验收结果；后续生命周期开发继续既有
[Feature 142](specs/142-automatic-solve-lifecycle/spec.md) SDD。其前台活动墙钟与父编排已经实现，
当前验证及 Phase B/C 剩余范围以上方 Feature 142 最新段落为准，不改变本真实槽的 `0/1`。

## Feature 137：run 墙钟预算传播到 Agent 请求（2026-09-18，离线完成）

`BudgetSpec.max_runtime_seconds` 现在会收紧实际执行请求：显式 `run_agent()` delegation 和
普通 `resume()` worker 在调用 adapter/runtime 前，都会取得同一次 controller 执行的剩余
单调时钟预算，并传入 `min(原请求超时, 剩余 run 时间)`。同步多任务与并发 worker 共享同一
起始时刻，后续任务不会重新获得完整 `Config.runtime_timeout`。剩余时间耗尽继续走既有
`BudgetExceeded("max_runtime_seconds", ...)` 与幂等 `budget_exceeded` 台账；取消、活动 runtime
fan-out、进程组清理和迟到结果丢弃语义保持。新增 cancellation-first / budget-first 离线
竞态 fixture，固定 durable winner 不会被后来的结果或取消改写；同时修正
`Store.cancel_run()` 在 run 已经 `failed` 后仍会改写 blocked task 的状态机缺陷。

专项 fixture/controller/adapter/runtime/budget 回归为 116 passed；完整当前回归为
7941 passed、1 skipped、24 deselected，冻结 Feature 123 阶段为 24 passed。Ruff、compileall、
Specify 前置与 diff 检查通过，冻结阶段复核 77 个产品、14 个 measurement 和 69 个历史 pin。
Feature 134 规格与 retained campaign 路径不在工作树 diff 中；本轮没有 provider 请求、真实
campaign、evaluator、生成代码执行或 WebAgent 重跑。规格与证据边界见
`specs/137-run-wall-clock-budget/`。

## Feature 136：候选阶段显式工具预算与完成诊断（2026-09-18，离线完成）

已实现并通过离线验证。`CandidateGenerationBudget` 在每次单文件或 bundle 候选请求前固定
候选级 tool-step ceiling，并把带迭代与调用序号的 `budget_id` 传入 `AgentRequest`、runtime
和 observer。整批超预算继续原子拒绝；没有 fitting-prefix 执行、retry、repair、隐式扩容或
候选发布。`CandidateGenerationDiagnostic` 现在同时提供兼容的 `reason/phase/completion`
和稳定的 `schema_version/stage/outcome` 投影，区分步数耗尽、tool failure、timeout、取消、
空最终响应、malformed candidate 与 completed。`completed` 只在非空、无工具响应通过原生
CandidateDraft/bundle parser 后发出。

Feature 136 只运行本地 fixture，没有 provider 请求、真实 campaign、evaluator 或候选执行；
Feature 134 的登记、证据、分母和历史结果未修改。专项 Agent-loop/adapter/evolution/bundle/
controller 回归、Ruff、compileall、diff 检查均通过。详见
`specs/136-candidate-generation-budget/validation.md`。后续真实运行仍需另立 SDD、登记并
在产品提交 push 后使用新的唯一槽。

## Feature 135：未配置 profile 的 Agent-loop 预算可见性与步数诊断（2026-09-18，已完成）

AgentLoopRuntime 的普通 `run` 请求现在始终使用请求副本附加既有
`lunar_runtime_budget` advisory：未配置 ModelProfile 时仍显示当前剩余工具调用数；传入有限
wall timeout 时显示同一单调时钟计算出的剩余秒数和有效命令窗口；token/cost 继续为 null。
profiled loop 的快照、UsageLedger、超时准入和 `run_isolated` 的无 advisory 行为保持不变。
快照不写入 replayable messages、SessionTranscript 或持久调用状态，每次请求只含一份当前值。

整批工具调用超过剩余额度时仍在 assistant/transcript append 和任何工具执行之前原子拒绝，
新增 `AgentStepLimitEvidence`/`AgentStepLimitReached` 类型以及 attempted_tool_calls 和
tool_steps_remaining 字段；旧异常文本和事件类型保持兼容。没有重试、repair、前缀执行或
提高 max_steps。27 项聚焦测试、共享 runtime/interactive/evolution/master-planning 回归、
Ruff、compileall 和 diff 检查通过。该功能只改善诊断和请求内提示，不能保证模型完成候选，
也没有重开或修改 Feature 134 的任何测量证据。详见
`specs/135-unprofiled-agent-budget-visibility/validation.md`。

## Feature 134：真实准备与 8 项留出通过，未完成交付（2026-09-18）

按 SDD 完成规格、方案、测量实现和离线验证后，登记提交 `358f738` 已先推送再启动
唯一 `attempt-001`。固定产品为 `15710bd`，沿用 131 的任务、输入、provider、GLM-5.2、
population 和 seed；普通请求及候选执行仍为 600 秒，preparation 请求为 900 秒、
preparation 总墙钟为 1860 秒，整次 campaign 仍限 2400 秒、20 请求和 160000 观测 tokens。
8 项预声明 holdout 只在准备通过且仍有 campaign 时间时执行，不重试、恢复或补槽。

新测量保留原生类型化请求失败、验证持久化预算，并安全投影实际 HTTP 状态；父任务的
持久状态与对外状态分开展示。唯一槽已经结束：preparation 1/1，8 项 holdout 全部执行且
精确匹配，primary/joint 均 0/1；没有父任务交付，官方 quality/gap 均 null。合同、evaluator
compiler 和 auditor 请求分别耗时 48.363、346.070、124.757 秒，两项准备请求都低于旧的
600 秒时限，不能将这次准备成功归因于预算增加。

11 次请求均 HTTP200，用量完整 98714 tokens（34088 input + 64626 output），费用未知，
无 pending request；总耗时 896.396 秒，native/process exit 均为 1，清理通过。持久父状态
为 succeeded 表示 intake 已完成；evolution child 失败使 CLI 对外状态为 failed，符合现有
投影规则，不能据此认定父任务持久状态缺陷。

只读诊断确认三次候选生成均在给出最终候选前触及登记的 `--max-steps 4` 工具执行预算。
前两次各执行 2 次 read_file 和 2 次 write_file，随后 2 工具批次在 4+2>4 时被拒绝；
第三次执行 2 次 read_file 和 1 次 list_dir，随后批次在 3+2>4 时被拒绝。已执行的 11 个
工具全部成功，但没有形成可准入候选，evaluated/valid candidates 均为 0，child 以
`offspring_batch_failed` 结束；尚未进入候选执行、独立评分或交付。这是本次登记工具
预算不足，HTTP200 和文件写入成功不等于候选完成。

下一步按 SDD 设计足够且显式的每候选工具预算及候选完成诊断，先用离线 fixture 验证，
再决定新真实测量的预算并独立登记。不能在旧槽追加工具、改变 guard 语义或重试补分。
见[134 报告](docs/history-archive.md)。真实完整交付仍未
通过验收；外部 producer 多文件 seed、全链路预算/取消及 detached 仍未完成。

262 项测量测试通过；全量双阶段为当前 7924 passed/1 skipped/24 deselected 和固定历史
24 passed。本次真实运行使用了独立 preparation 预算、HTTP 投影和结果摘要；类型化
preparation 请求/墙钟失败诊断仅经离线验证，真实准备阶段没有触发这些失败分支。不能
据单一样本声称通用稳定性、演化收益或 WebAgent parity。

## Feature 133：独立 preparation 请求预算与总墙钟预算（2026-09-18，已完成）

已完成确认的完整范围：`--evaluator-preparation-timeout` 控制每次 compiler/auditor
模型请求，`--evaluator-preparation-wall-timeout` 控制一次准备的总墙钟。既有 `--timeout`
继续控制候选生成/执行与冻结 evaluator 执行；preparation 值不进入 `bundle-profile.json`，
不改变 profile bytes 或 evaluator identity。请求缺省沿用 `timeout`，总墙钟缺省为
`min(86400, 2 * request_timeout + 60)`；两者均须有限且在 `(0, 86400]`，总墙钟不小于请求。

计时紧随持久化 `bundle_preparation_started` 开始，覆盖之后的输入检查、两次请求、
本地预检和发布检查；等待准备锁与 start 前准入不计入本次预算。请求和本地进程按剩余
时间收紧，阶段前后与发布前检查同一 deadline。观察到期后不能发布成功 prepared event
或创建 child；已开始的有界写入/登记可能在下一次检查前完成，留下的本地材料须在显式
恢复时重新验证，不能直接充当准备成功的 authority。不引入回滚或任意操作的异步中断。

新 compiled handoff 持久化两项预算及 explicit/default 来源，`resume`/`answer` 恢复且
拒绝显式不匹配。旧 handoff 请求回退存储的 `timeout`，缺失总墙钟保持 legacy-unbounded，
不能在恢复时补有限值改写历史策略；已有值但缺来源时只标 persisted。JSON/text 分开展示
候选、请求和总墙钟。保留 Feature 132 的实际请求证据与 Feature 116 的父任务 persisted
running/effective failed 语义，只有显式继续才按原策略开始新的准备 attempt。

84 项 CLI 策略测试、41 项墙钟测试及 276 项相关集成回归通过；全量双阶段 exit0：
工作产品 7661 passed/1 skipped/24 deselected（525.38 秒），固定历史版本 24 passed。
全量收集后补的布尔预算严格绑定检查另经 169 项诊断回归通过，没有为该窄改动重跑全仓。
112 离线示例仍选 7 分、交付 1 份，终态恢复调用数保持 1/1/1/4/4。Ruff、compileall、
Specify、文档链接、diff 与独立审查通过；131 份历史证据大小和 SHA 保持一致。完整记录见
`specs/133-preparation-budgets/validation.md`，本轮正常提交并推送 origin/main。

没有调用真实模型、重放历史捕获源码、改动冻结测量或新增 WebAgent 效果结论。下一步可为
新的小型真实多文件闭环独立登记产品、任务、provider、请求/墙钟预算及唯一运行槽，再验证
实际准备和交付；不能重开 Feature 131。真实自动多文件端到端成功仍未验收，外部 producer
多文件 seed、全链路预算/取消及 detached 仍在后续范围。

## Feature 132：自动准备保留模型请求失败详情（2026-09-18）

本轮补普通solve/status的可观察性：evaluator compiler/auditor边界保留直接、精确类型的
ModelRequestFailure，持久化固定reason、可选HTTP状态、请求阶段/耗时/时限和最后本地传输
里程碑。新准备schema3严格绑定parent/attempt与唯一紧邻start；坏持久详情降级，取消、
终态、输入漂移和已完成准备优先。没有可信模型详情的普通runtime异常继续schema1，
本地格式/探针失败继续schema2。JSON/text status展示已验证详情，超时提示明确远端完成/
用量未知，显式resume可能发新请求。提示、时限、模型参数和重试策略均未改。

代码复核纠正131收尾中的一个建议：父run保留running是116明确规定的恢复语义，不是
本轮新发现的终态缺陷；effective status=failed及准备失败记录已经表达失败。直接把父任务
改failed会阻断合同复用和显式恢复，因此保留原状态，历史131报告与证据不改写。

验证记录见`specs/132-preparation-request-diagnostics/validation.md`。本轮只做离线验证，
尚不能证明evaluator生成更快或超时减少。下一步应明确受支持的生成预算/等待策略，再为
新的真实测量登记固定条件；在新测量摘要中补HTTP状态投影，不能回写131。自动真实多文件
端到端成功仍未验收；外部producer多文件seed、全链路预算/取消与detached继续后置。

## Feature 131：合同通过，evaluator compiler 等待响应头超时（2026-09-17）

固定产品`c730483`，登记提交`1993f11`先push后运行新的唯一槽；manifest SHA
`5d4f42808eb00e1e0c5fc9258256d4f72439dd788a9dc2fbe91389da522cf43e`，78product/
16measurement/153history pins。任务、provider、预算、population和seed与129相同，仅更新
产品与campaign身份，并固定引用128/129 manifest。

contract compiler在25.237秒返回HTTP200，已知用量3656tokens（1754input+1902output），
原生合同通过严格验证，`contract_verified=true`；129漏`status`的封装失败在这一个同任务
样本中没有复现，但不能据此声称130有因果收益。随后evaluator compiler在等待响应头时于
600.004秒`transport_timeout`；没有HTTP状态、响应正文或已知用量，最后本地里程碑为
`wait_response_headers`，不能区分provider排队、模型生成或其他远端延迟。总用量保持null，
不能用首个请求的3656tokens代替。

正式结果primary/preparation/joint均0/1，0/8 holdout执行，quality/gap均null；没有冻结
evaluator、candidate、delivery或额外请求。总626.814秒、exit1，清理通过、剩余观察PID[]。
21份证据共155485bytes，文件集合、大小和SHA复验匹配；独立审计无阻断项。原始transport
台账保留首请求HTTP200，但公开`results.json`未投影该状态；CLI失败后父run持久状态仍为
`running`，没有造成成功误判或残留进程。当时列为后续终态一致性项；Feature132复核确认
这正是116保留合同、允许显式恢复的持久状态，不能把父run改成终态failed。

完整记录见`specs/131-small-multifile-recheck/postrun/report.md`及`validation.md`。下一步
先处理evaluator生成延迟与超时语义，再在产品修复后新登记真实运行；不重开131。当前仍无
真实自动多文件端到端成功结果，128只证明独立evaluator准备1/1与holdout 8/8。外部producer
多文件seed、全链路预算/取消与detached继续后置。

## Feature 130：合同响应完整封装示例（2026-09-17）

合同compiler提示现在在既有封装规则与详细schema之间给出完整`needs_input`和`compiled`
严格JSON。两例都显式包含顶层status；前者仅含questions/evidence，后者含完整contract/
evidence且无questions。compiled例覆盖inputs fields对象、outputs fields数组、output范围硬约束
和population参数，内容自洽并直接通过生产parser/dataclass。提示明确示例只说明shape，所有
任务事实必须按当前goal/answer替换，不能复制示例内容。

生产`_parse_response`和`_validate_contract_shape`未改；删掉相同compiled例的status仍固定拒绝
`compiler response must be status=compiled with contract`，没有推断、repair、retry或额外请求。
99项聚焦及104项相关回归通过；112 quickstart仍选7分，恢复调用数保持1/1/1/4/4、交付1份。
全仓双阶段exit0：当前7168 passed/1 skipped/24 deselected，固定旧产品24 passed；Ruff、
compileall、Specify、空白检查与独立审查通过。完整记录见
`specs/130-contract-envelope-examples/validation.md`。

本轮没有真实模型调用，不改变129的0/1或任何历史分母，也不能证明示例会提高遵循率。
下一步若继续真实验证，须以Feature131独立登记并先push固定产品、任务、provider和预算，
再运行新的唯一槽；不能重开或修补129。外部producer多文件seed、全链路预算/取消与detached
继续后置。

## Feature 129：真实自动多文件验收在合同封装处失败（2026-09-17）

固定产品b951857，登记08624f5先push后运行新的唯一槽。manifest SHA
`63a056263387dbee5c9282fffb21182c9eb2fd51b6354cf871b5d4b06af10ad9`，78product/
16measurement/133history pins；任务读取limit3、最大化整数value，要求至少两个.py路径。
原生solve --evolve --multi-file，最多20请求、600秒/次、2400秒总墙钟、160000观测token。

唯一contract compiler请求45.509秒HTTP200、4076tokens（1225input+2851output）；完整
2045bytes响应顶层只有contract，缺少必需status=compiled。原生parser拒绝，task_failed
记录同一固定错误；没有合同、evaluator、候选或交付。primary/preparation/joint均0/1，
0/8holdout执行，官方quality/gap为null。总47.339秒、exit1、清理通过、剩余观察PID[]。
没有重试、恢复、替补、修补响应或额外请求。下一轮不能重开这个槽。

183项新测量测试、353项相关回归与112终态恢复通过。独立审查修正候选请求停止后本地
holdout仍可执行、部分失败的官方quality门控、交付input/evaluator/spec绑定。SQLite
只读连接在中断WAL后会改SHM，因此分析现在读取临时DB/WAL副本；实际中断writer测试
验证WAL行可见且原证据不变。产品、12份实现/测试、1721份旧文件与历史证据保持原bytes。
16份本轮证据122657bytes复验匹配；请求6268bytes从冻结提示离线重建hash一致。
完整记录见`specs/129-small-multifile-acceptance/postrun/report.md`及validation.md。

下一步补合同compiler的完整compiled/needs_input JSON封装示例与新离线检查；现有提示
已经说明status要求，不能把漏字段说成规则未提供。保持strict parser，不猜测缺失status、
不执行旧捕获；修复后若要真实验证必须新登记。128的准备1/1与8/8保持，113/115/117/120
各0/2、123/125各0/1不变；仍没有真实多文件闭环成功。外部producer多文件seed、全链路
预算/取消与detached继续后置。

## Feature 128：小型真实准备与留出检查通过（2026-09-17）

固定产品b951857，登记38c323c先push后启动独立唯一槽；manifest SHA
`460da2cedd52c9cf4774139df084129685c1bd686372f2662c5c683421d59a48`。
保留125整份合同、输入/profile、8项holdout、GLM-5.2/provider、采样缺省和预算；没有
改产品、重试、恢复、替补或手动补请求。测量新增严格六字段local_failure可选采集与复验。

compiler380.010秒HTTP200并通过3项自测，auditor125.088秒HTTP200并通过5项独立探针；
评测器成功冻结，8项预声明holdout各执行一次且全部精确匹配。结果freeze1/1、holdout8/8、
joint1/1；记录用量完整43630tokens（8563input+35067output），费用/quality/gap未知/null。
总墙钟507.148秒、exit0、清理通过、剩余观察PID[]；local_failure=null，真实失败分支没有
在本次成功执行中触发。不能把这次准备成功写成多文件solver交付或126/127因果收益。

209项新增测量测试、325项相关回归、112恢复示例通过，独立审查无阻塞项。78product/
15measurement/118history pins、11份冻结实现/测试和1701份旧产品/spec/test字节不变；
63份保留证据与125/123/120的16/15/46份旧证据size/SHA匹配。两请求18082/20616bytes
离线重建hash一致；仅静态解析，未重放生成代码。3/5项probe输入均为JSON对象。
完整记录见`specs/128-format-admission-diagnostic/postrun/report.md`与validation.md。

下一步独立登记一项支持范围内的小型真实多文件任务，贯穿自动solve合同准备、compiler/
auditor、候选生成、执行、独立评分、选优和父任务交付，使用确定性双源码文件要求和
独立输出检查，并在调用前固定预算。113/115/117/120仍各自0/2，123/125仍各自0/1，旧槽
保持封存；8项整数holdout不覆盖全部bool/float类型规则。外部producer多文件seed、
全链路预算/取消与detached继续后置。

## Feature 127：本地评测器准备失败原因（2026-09-17）

新EvaluatorPreparationDiagnostic仅含schema_version、stage、reason、probe_index、input_index、
order_index。固定四阶段compiler/auditor response/preflight，严格枚举/索引关系，位置为1起
整数，拒绝bool，probe/order上限64、input上限32，不含生成内容、路径、名称或异常正文。
原生控制流区分响应准入、输入格式、输出schema、进程、报告、validity、约束码、分数顺序；
snapshot保留既有file set/文件完整性检查，bundle完整性失败无虚构probe位置，无法细分的
本地异常保留preflight_failed。响应内source/envelope等仍统一response_invalid；process
仍粗分process_failed，不推断超时/退出/输出限额具体根因。candidate已有检查范围不扩张。

异常携带诊断经过正常staging清理。自动准备仅为有效的精确类型写schema2/local_failure，
外层stage一致，validation_error/recoverable=false；读取复验精确字段、阶段/原因/位置、
parent/attempt和唯一匹配started。坏详情降级，取消/终态/输入漂移/已完成优先。schema1、
runtime恢复和旧冻结加载不变；diagnostic不授予恢复/评分/交付权限。JSON和文本status均
展示有效原因，数字位置仅在已知时展示。显式用户继续沿用既有逻辑，无自动重试/repair。

新增244项测试通过，当前全仓6770 passed/1 skipped，历史固定快照24 passed，双阶段exit0、
临时worktree清理。冻结6份实现/测试、1616份旧spec/test及125/123/120的16/15/46份保留证据
均未变；Ruff、compileall、CLI、Specify及143个链接通过，独立审查无阻塞项。完整记录见
`specs/127-evaluator-preparation-diagnostics/validation.md`，按授权正常提交推送。
112 quickstart仍选7分，恢复保持1/1/1/4/4调用和唯一交付。提示词、response parser、manifest
和冻结身份未改；私有信号不会把冻结后的生产评分错误冒充准备错误。本轮不调用真实模型，
不执行125捕获源码，所有旧测量分母不变。下一步固定已验证产品，另行登记并先push一项
新的小型准备诊断，再按compiler一次/条件audit和预声明holdout执行；不重开历史槽。

## Feature 126：合成输入复用真实格式准入（2026-09-17）

data_profile公开纯validate_input_format，与真实画像共用_parse_input及原有_utf8/_records。
JSON只接受对象/对象数组，JSONL只接受对象记录，CSV校验表头和行宽，text按UTF-8读取；
保留重复键、非有限数、字段/深度/行数限制，递归/Unicode异常归一为DataProfileError。
不从fields描述推断schema，不要求合成数据复制私有行数、字段类型或统计值。

compiler和audit两种suite、candidate和snapshot两种调用均在第一项probe执行/创建workspace
之前检查整组所有声明输入，expected_validity=0也不豁免。compiler格式失败不会调用auditor；
audit格式失败不运行任何audit harness、不冻结；固定错误只含阶段和格式类别，不含输入
或解析器原文。共享提示说明可执行规则和边界。旧bundle保留既有身份和结构校验，不重放
探针或施加新增输入格式准入；profile bytes、协议、source/output审查和严格冻结边界保持。

新增81项离线测试、240项相关回归及独立审查通过；112 quickstart仍选7分，终态恢复保持
1/1/1/4/4调用及一个交付副本。最初72项先复现60失败/12通过；新fixture不读取或执行125
捕获源码。最终当前代码6526 passed/1 skipped，历史固定快照24 passed；双阶段exit0，
临时worktree已清理。冻结的3份实现/测试、1610份既有spec/test和125/123/120的16/15/46份
保留证据均未变。Ruff、compileall、CLI、Specify及140个文档链接通过。完整记录见
`specs/126-synthetic-input-format/validation.md`，按授权正常提交推送。

下一步补有界、controller自有的本地准备失败阶段/原因，随后才另行固定登记真实诊断。
本轮没有真实模型调用；格式合法不保证业务字段、值类型、范围或评测正确。113/115/117/120
仍各自0/2，123和125各自0/1，真实多文件交付尚未成功验收。外部多文件seed、全链路预算/
取消与detached继续后置。历史campaign和测量登记不可重开、重钉产品或改写。

## Feature 125：compiler自测通过，独立audit阻止错误冻结（2026-09-17）

固定产品eefe389，沿用123整份合同（problem_id也保留）、输入limit3、8个holdout、GLM-5.2
与provider、600秒/请求、1320秒总墙钟、最多2请求和160000观测token阈值。新独立/1根
`.lunar/diagnostic125-glm-5.2-snapshot-protocol-20260917`，不重开123。compiler一次，只有
原生自测通过才audit一次；冻结后运行8个预声明holdout，每项5秒，无重试/恢复/替补。

产品代码未改；四个测量模块与123字节一致，observer只改独立loader名，campaign明确校验
其余固定条件相同。新离线112项及合并325项测试通过；正确target fixture完成2请求/14次
本地harness，错误path fixture只完成1请求/1次probe，未audit/freeze。登记fixture改用
临时Git仓库，保留原product_changed/push检查，不新增依赖固定旧产品的常规测试。
112 quickstart仍选7，终态1/1/1/4/4调用与唯一交付保持；独立审查及历史字节检查通过。

登记ef29c36先push后执行唯一槽。manifest SHA
`c76a7f4802ad2691fc0c400c3525f9e38f4c520399a1a6a9f8f8e4506ea43a12`，
77product/14measurement/91history pins；两请求16751/19504bytes，均离线重建hash匹配。
compiler326.682秒HTTP200并通过原生自测，随后auditor50.640秒HTTP200；本地准备最终
EvaluatorBundleError，未冻结，freeze/joint均0/1，0/8holdout执行。用量完整36499tokens
（8069input+28430output），费用/quality/gap未知/null。监督378.853秒、exit1，清理通过、
剩余观察PID[]。两份3958/1120bytes私有响应完整且无截断/脱敏，16份保留证据size/SHA匹配。

纯静态解析确认compiler3probe、auditor5probe均格式可解析。新源码正确使用target/path，
但把整个JSON输入根当整数：L21读取整根，L38–39拒绝非int，L52–53发无效报告，没有读取
limit字段。compiler的3份输入也是标量整数，audit5份则是符合合同的{limit:整数}对象。
因此首个有效audit输入被该分支拒绝；这是静态充分缺陷，未保留原traceback，也未重跑任何
捕获代码。独立audit提供了区分案例并阻止错误冻结，不能说成auditor失效。

下一步统一合成probe与真实输入已有的格式准入：profile解析已拒绝JSON标量，但probe只
预检输出格式。复用现有JSON/JSONL/CSV/text规则，避免从自然语言fields推断强制schema，
不要求合成数据复制私有行数/类型统计。再补细粒度本地失败阶段/原因，保持audit与冻结严格，
不repair/retry。产品及10份测量/测试冻结bytes未变，旧证据复验通过；完整报告见
`specs/125-snapshot-protocol-diagnostic/postrun/report.md`。单次推进不证明124因果收益或
完整多文件成功。113/115/117/120仍各自0/2，123和125分别0/1，旧槽保持封存。
另新增29项纯静态诊断测试通过，本轮共141项新测试；分析脚本核验固定证据后只解析
JSON/AST，报告可逐字复现，SHA `9d93dc126274c46f8c687577a09dbb6919407aa40f33b67940e43f5318eb487c`。

## Feature 124：补齐 snapshot 请求结构与路径说明（2026-09-17）

共享 compiler/auditor 提示现在给出完整 request 结构，明确 inputs[] 只有
target/source_label/size/sha256，读取 inputs/<target> 并保留嵌套目录；contract input.path
等于 target，profile/probe 的 path 则有 data/raw/ 前缀。outputs[].path 已含 output/，
直接读取；可选输出缺失仍有 present=false/size=null/sha256=null 描述项。零字节输入仍有
文件；source_label、binding 和 evaluator 配置是元数据。示例使用原生序列化器和明确占位
contract/虚构解释器路径，不复制实际私有值或主机路径，任务 contract/profile 各保留一份。

新增8项测试通过，捕获6次真实本地compiler/auditor预检和2次实际candidate/evaluator请求，
覆盖嵌套输入、UTF-8字节、零字节与可选输出缺失。独立构造的target读取成功，path误用在
首个有效probe被拒绝，未进入audit/freeze；没有运行或修补123的私有源码。88项相关回归
通过，112 quickstart仍选7分，终态恢复保留1/1/1/4/4调用与一个交付副本。独立审查通过，
产品实现与测试冻结后未改。首次直接全仓6286 passed/1 skipped/24 setup errors，均为
123旧登记fixture要求519fea5而正确拒绝当前product_changed；这24项在独立5560eb9快照
全部通过。新增显式双阶段 `tools/run_tests.py` 与18项隔离/清理/失败传播测试，CI与README
同步；当前代码跑当前测试，旧24节点在固定快照跑，任阶段失败整体失败，不跳过或改guard。
最终双阶段通过：当前 **6304 passed/1 skipped/24 deselected，418.44s**；固定历史快照
**24 passed，15.30s**，整体exit0，临时worktree已清理，两个JUnit均零失败/错误。
5项实现/测试/CI冻结hash未变；Ruff、compileall、CLI、Specify及135个文档链接通过。
完整记录见 `specs/124-snapshot-request-protocol/validation.md`，按授权正常提交推送。

AST确认src只新增纯示例helper、修改snapshot提示，旧candidate提示字节一致；解析、request
构造、调用、冻结身份和恢复均不变。共享说明1079→5329bytes，不能声称变快或模型更稳定。
历史73个spec/17个测量测试、123的69history/14measurement pins、注册版本77product pins
与123的15份/120的46份保留证据均复验通过。113/115/117/120仍各自0/2，123仍0/1。

下一步在本轮提交推送后，单独登记并先推送修复后的新小型准备诊断，再真实检查
compiler自测、条件auditor、冻结及预声明holdout；不重开123槽，不改变旧分母。当前尚无
真实多文件闭环成功，外部多文件seed、全链路预算/取消与detached继续后置。

## Feature 123：小型诊断0/1，定位输入描述字段不匹配（2026-09-17）

固定产品519fea5，独立/1诊断只直接调用原生snapshot evaluator准备，仍用AgentLoopRuntime
的system+user隔离调用；没有合同编译、普通求解器或source要求。整数value在输入limit范围
内并最大化，一项output hard constraint；输入为limit3，8个预声明holdout覆盖limit1/3。
compiler一次，只有原生解析/源码/自测接受后才audit一次，最多2请求，600秒/请求，1320秒
监督总墙钟同时覆盖本地自测/holdout；冻结后每holdout5秒，无重试、恢复、替补。

登记034b1847eaf0cc043ac87e179ebd72de5fc1fb90已先push；manifest SHA
`9d05c7d95eb427f60d7be7a93dbfb8c7c53ec50904169e0391053292315f60a7`。唯一请求HTTP200，
242.848秒后完整返回，但本地preparation抛EvaluatorBundleError，尚未audit/freeze；最终
freeze和joint均0/1，0/8 holdout执行，quality/gap为null。已知总用量20831 tokens
（2688input+18143output），费用未知。首请求12353bytes，SHA与登记相符；HTTP体79074
bytes仅留长度/摘要，assistant text5365bytes完整保存在本地且无脱敏/截断。最后传输点为
response_headers_received/index1/242766ms，不能倒推出连接/排队/模型计算各自耗时。
supervisor总244.044秒、worker退出1，cleanup通过，无剩余已观察进程。

独立只读诊断确认JSON envelope、3978bytes源码AST、3个probe格式与静态oracle均通过。
生成代码L58使用input entry.get('path')，native input descriptor却是
target/source_label/size/sha256；L61–63因找不到声明而返回validity0，尚未读inputs/limit.json，
足以使首个有效自测失败。输出descriptor的path使用正确，不应一起改成target。
121/122的snapshot prompt只说明inputs/<target>文件位置，未明确inputs[]嵌套字段，也没
区分它与contract.inputs[].path/profile.files[].path。**下一步补齐真实request对象格式与
descriptor示例，并用本地真实snapshot request验证提示一致性**；不能修好后重放此槽。
此为静态充分缺陷，不是实际traceback重放，也不证明提示遗漏是唯一原因或修复必成功。

102项新测试、403项相关回归及112恢复示例通过。77product/14measurement/69history pins
和15个retained文件size/SHA复验均通过；测量实现未改，产品仍519fea5。
根 `.lunar/diagnostic123-glm-5.2-small-evaluator-20260917` 已封存，summarize只读执行一次。
证据与静态诊断见 `specs/123-small-evaluator-diagnostic/postrun/report.md`，静态检查脚本不
执行生成代码；私有响应/源码不公开。113/115/117/120仍各自0/2，不推断旧超时根因，也不
视为121因果延迟收益或真实多文件交付。外部多文件seed、全链路预算/取消、detached仍后置。

## Feature 122：本地 HTTP 里程碑与兼容诊断（2026-09-17）

有界 HTTP worker 增加固定三字段 TransportObservation：last_milestone、
http_exchange_index、elapsed_ms。里程碑依次为 worker_ready、prepare_request、connect、
send_request、wait_response_headers、response_headers_received；每次 urllib HTTP 交换
递增序号，代理 CONNECT 留在 connect 内。毫秒从 parent transport start 算起，worker_ready
表示请求IPC/config已接受。连接包含DNS/TCP/代理隧道/TLS，写入返回不证明远端接收/执行。
中间302响应头不冒充最终状态，慢重定向响应体与第二跳慢头可分辨；这不是服务端根因诊断。

通过继承标准库 handler.do_open 和 connect/request/getresponse，仅包观测，不复制TLS
context/ALPN逻辑或修改请求。粗phase/status、deadline、单PID/lifeline清理、正文限额均保留。
IPC最多256条里程碑，达到上限或观测时钟失效时明确丢弃可选细节并继续原请求；旧2/3帧
协议仍有效。没有完整观测或worker非零退出丢失观测均表示未知，不能说没有发送或消费为零。

TransportResponse/TransportFailure具有可选observation；ModelRequestFailure另存
transport_observation，包括HTTP完成后的响应解析失败。成功ModelTurn和直接无界路径不变。
subject仅在原v4及同节点typed detail均有效时写schema5，缺失/畸形detail回退，旧1–4可读。
新字段只有固定名字与整数，不记录端点、认证、代理、头、正文或异常原文。

新增151项本地HTTP/TLS/代理/重定向、发送/DNS/启动阻塞、严格IPC和normal/deep诊断测试
通过；相关回归445项通过，独立审查无阻塞项。112 quickstart仍交付7分，恢复保持
1/1/1/4/4调用和一个交付副本。最终全仓 **6200 passed, 1 skipped in 415.59s**，JUnit
零失败/错误，冻结后未改实现；Ruff、compileall、CLI、Specify、130个文档链接和历史字节
复验通过。Python3.11另验证语法/导入/标准库hook，行为测试在仓库3.13执行。
完整记录见 `specs/122-transport-milestone-observation/validation.md`，按既有授权正常提交推送。

没有真实模型调用，113/115/117/120仍分别0/2。下一步固定并推送新独立登记：一项小型
合成snapshot evaluator准备诊断（整数value在输入limit范围内并最大化），compiler一次，
只有原生解析/源码/自测通过才调用auditor，最多两请求；600秒/请求，加独立supervisor总墙钟
覆盖本地自测。仅冻结后执行预声明快照holdout，使用独立/1分母。不得当作完整多文件交付、
真实算法质量或121的因果延迟改善。外部多文件seed、全链路预算/取消与detached仍后置。

## Feature 121：评测器生成协议补全与离线请求诊断（2026-09-17）

离线从 `c569508` Git 源码重建120四个请求，SHA全部匹配；评测器请求分别9,723/11,366
bytes，合同与结构画像各一份、system/user各一条，无工具/历史或应用重试。请求未发送
temperature/max_tokens/reasoning_effort；配置里的推理档位并不等于这条路径的实际参数。
`open_response` 还包含连接/等待响应头等阶段，不能区分模型计算、队列或网关原因。
诊断只发布字节数/计数/摘要，读取10个历史文件前与固定evidence inventory核验。

另行确认 compiler/auditor 提示缺少 probe/files/score_order、报告detail/error完整结构，
只说标准库却未说明AST白名单，且没有交代无效业务探针仍须满足输出schema。现在共享
完整占位示例、字段类型、文件路径映射、计数/字节限额、允许导入与禁止调用/属性/字符串
规则；说明可构造小型合成数据，不能从结构画像恢复真实私有值。source检查仍在controller，
auditor只拿冻结source/objective，不拿compiler自测数据。只有两个现有prompt函数改变，
解析器、source validator、模型调用、冻结身份和终态恢复均未修改。

新增51项离线测试（prompt34、只读诊断17）通过；真实本地预检和112 quickstart仍选7分，
恢复维持1/1/1/4/4调用和一个交付副本。最终全仓 **6049 passed, 1 skipped in 403.54s**，
JUnit零失败/错误，冻结后无实现修改；Ruff、compileall、Specify、128个文档链接和历史指纹
复验通过。完整记录见 `specs/121-evaluator-prompt-protocol/validation.md`。
同旧输入构造的新请求为17,058/18,734 bytes，未发送；本轮是协议完整性修复，不是已证实
的延迟或成功率提升。113/115/117/120仍各自0/2，不运行旧verifier重新登记产品指纹。

现有边界保留：最多62个输出硬约束可同时容纳两条有效探针，每条探针最多32个必需路径；
仅能由缺失/坏格式成立的约束未必能构造schema有效反例。不能静默排除要求。后续先在冻结
版本上设计可区分响应阶段的独立小规模诊断；不再单纯加长超时或重开旧槽。外部多文件seed、
全链路预算/取消与detached模式仍后置。

## Feature 120：支持范围真实验收完成（2026-09-17）

登记 commit `f3b575c5bf86019b27529339c88f6f936a779654` 已先推送，manifest SHA
`d8dd67c250161aed751ebf85ae10f330b03c8eedfaeb7356011e4e4ff7f7270e`。两题沿用117预算与
模型，仅把任务要求收敛到可独立验证的硬源码文件数检查（至少2个小写 `.py`）；不声称
helper 导入、依赖限制或实际输入读取。两槽均只运行一次并完成清理，最终 **0/2**。

两题各先完成合同编译（已知 5,236 / 10,925 tokens），合同均包含登记的
`python_file_count minimum=2` source check；随后 evaluator preparation 的第二个请求分别
在约600.004/600.003秒 `open_response` transport timeout。没有冻结 evaluator、候选、输出
交付、源码证据或 holdout；quality/gap 均 null。四次请求已知小计 **16,161 tokens**
（2,881 input / 13,280 output），超时消费与费用未知。24个 holdout 未运行，未重试/恢复/补槽。
详见 `specs/120-supported-scope-acceptance/postrun/report.md`；历史113/115/117各0/2不改写。

304项相关离线回归、source-aware分析与登记测试通过；112 quickstart仍为1/2/6/7、终态
调用数1/1/1/4/4。真实评测器生成仍是当前瓶颈，下一步先离线检查 evaluator 请求规模和
准备协议，再独立登记可区分原因的诊断；当前证据不能区分模型长推理、服务排队或网关
等待。不能继续只延长时限或把超时消费当零。

## Feature 119：源码文件数独立检查与交付（2026-09-17）

合同支持 `verification_scope=source` 配合 `source_check={kind:python_file_count,minimum:N}`，
N 为 1..64 的整数，仅允许精确字段。检查按完整已验证 bundle 中的小写 `.py` 路径计数，
空文件也计入；不证明语法、helper 调用、代码有效性、依赖或真实输入读取。字段缺省保持
旧合同 bytes/digest 不变，非法/null/错误 scope 拒绝，不将行为要求改写为文件数。

自动 snapshot evaluator 接受这种硬源码约束，compiler/auditor 只对其余输出硬约束生成
探针，完整合同仍固定在摘要中。legacy candidate invocation、无检查器的 source、soft
source 和 execution 要求仍提前拒绝；显式 bundle pipeline 和直接评测同样复验能力。

独立评测先复验全部源码字节，再对 bundle 执行本地确定性检查；源码不合格时不调用输出
harness，保留 validity=0/score=0/quality=null 的报告。输出 schema 失败优先，源码通过
仍不能覆盖输出评测失败。`source-checks.json` 绑定完整合同/bundle/source table，包含每项
计数/阈值/结果；仅在输出 harness 返回后由 controller 写入。证据上限 256KiB，报告最多
32 条错误但证据保留完整失败列表。新 evaluation 使用 `lunar-candidate-evaluation-source-v1`，
inspect 重算证据，旧无检查记录保持原协议/字段；不重跑任何候选或 evaluator。

选优使用合并后的最终报告，source-aware 交付采用 `lunar-bundle-delivery-source-v1`，
携带 `evaluation/source-checks.json` 并重验实际源码集合/字节、合同、bundle 与结果。
去掉证据/合同或部分协议降级均拒绝，旧不透明交付仍按原协议读取。完整自洽重写需要外部
expected digest 才能辨别，便携自查不等于身份认证。父任务交付/终态恢复沿用已有摘要绑定。

新增 94 项离线测试：schema/probe/helper 34、独立评测 25、交付 33、自动流程 2。
自动 CLI 生成单文件高分 9 和双文件 2/6/7，前者因源码约束无效且跳过输出 harness，最终
交付 7；两种终态恢复保留 1/1/1/4/4 compiler/auditor/Agent/candidate 次数及唯一交付。
另一本地选优场景同时拒绝源码失败和输出失败。277 项相关回归及 78 项交付回归通过；
旧 112 quickstart 仍为 1/2/6/7，终态次数不变。最终全仓 **5912 passed, 1 skipped in
364.74s**，JUnit 零失败/错误，冻结后无实现修改。Ruff、compileall、installed CLI、Specify、
120 个文档链接和 diff 检查通过，已按授权提交推送。详见 `specs/119-source-file-verification/validation.md`。

没有真实模型、外部框架或冻结槽重跑，113/115/117 仍分别 0/2；本轮不证明真实有效率
提升。下一步在支持的验证范围内独立登记当前版本真实闭环；执行行为要求仍不能通过
源码计数替代。外部多文件 seed、全链路预算/取消和 detached 继续后置。

## Feature 118：合同格式兼容与评测器能力预检（2026-09-16）

合同入口接受严格 JSON，或完整的单层小写 json 代码块（LF 分隔、仅外层 ASCII JSON
空白）。先检查原始响应 UTF-8/64KiB/凭据模式，再去除这一对包装；不从说明文字中提取，
不修复内容，不追加请求。任意层级重复键、NaN/Infinity/溢出数字均拒绝，既有 schema、
未知字段、澄清和退役策略检查保留。普通 Agent 与 evaluator 的解析协议没有放宽。

ConstraintSpec 新增可选 verification_scope=output/source/execution，与 provenance 和
verification 强度独立；prompt 要求明确范围，不按 partial 或空 result_fields 排除要求。
旧合同缺省字段保持缺省，原 canonical bytes/digest 不变；显式 scope 参与摘要，null/非法值
拒绝。自动生成 evaluator 的两种 invocation 均在调用/准备前拒绝显式 source/execution
要求（hard/soft 都保留）；当前不具备它们的独立验证器，不能用输入/输出反例冒充验证。

准备失败使用 capability_check/unsupported_verification，保存具体 ID/scope、合同及同
attempt 事件；JSON/text status 给出原因，无 retry 提示。状态读取将诊断与当前合同复验，
畸形字段不回显；取消优先，显式 resume 仅再次本地检查，不调用模型或创建候选。
旧未声明 scope 的合同仍沿用原完整探针覆盖，不能据此声称旧合同语义已重新认证。

134 项新增离线测试通过（合同格式 57、范围/CLI 77），相关合同 160 项及准备/恢复 171 项
回归通过；本地 112 quickstart 仍交付 7 分，四候选 1/2/6/7，终态调用数 1/1/1/4/4 不变。
最终全仓 **5818 passed, 1 skipped in 380.77s**，JUnit 零失败/错误；实现冻结后无修改。
Ruff、compileall、installed CLI、Specify、117 个文档链接及 diff 检查通过；完整记录见
`specs/118-contract-protocol-capabilities/validation.md`。
没有真实模型调用，不改写 113/115/117 的各自 0/2、响应或未知用量，也不运行旧 verifier
来更新产品指纹。已按既有授权正常提交推送。

下一步是把明确可检查的源码交付要求接入独立验证与最终交付，再注册支持范围内的小规模
真实闭环验收。文件数不证明 helper 调用，输入摘要不证明实际读取，静态 import 不完整
证明运行时依赖；这些执行语义仍不支持。全链路预算/取消、外部多文件 seed 与 detached
模式继续后置，不能把这轮格式/提前诊断修复当作真实多文件有效率已提升。

## Feature 117：延长时限后真实验收仍为 0/2（2026-09-16）

新验收固定产品 `9a26a73`，沿用 115 的两道任务、输入、GLM-5.2/网关、oracle/24 holdout、
population 2+1/seed 113、16 请求和 160000 observed-token stop threshold；单请求/普通
Agent invocation/本地进程限时从 180 改为 600 秒，每题总限时从 1200 改为 3600 秒。
每题仅一次，无答复、恢复重试、补槽或模型回退；两题仍独立 /2，113/115 冻结不动。
登记 `17a0ad2` 先 push 后启动，manifest SHA 为
`822d46f6cc9bfd0850129bf4455bd32eb4652b7f9a07f3dabe9b4a8066b43ec2`。
预算选择的合同在 92.300 秒通过，评测器请求在 600.004 秒 open_response 超时；工作
分配在 36.108 秒收到响应，但原始文本包在 Markdown json 代码块中，严格 JSON 拒绝。
离线诊断确认去掉这对外层标记后的内部 JSON 符合合同 schema；没有写回现场或改变失败。

primary/envelope 均 **0/2**，无冻结 evaluator、子任务、候选、交付；24 个 holdout 未运行。
共三次请求、两次响应、一次未知消费的超时。已知用量小计 **11309 tokens**（input 2337 /
output 8972），总消费和费用未知；两题耗时 693.420、37.276 秒，退出码均 1，清理通过。
两个完整私有响应 5435/8111 bytes 已校验 size/SHA，无截断或脱敏替换，不公开正文。

116 修复在真实失败中生效：第一题 CLI 返回完整失败 JSON、input_request=null，父任务
running 并保留合同，开始/失败事件同 attempt，evaluator_compile/runtime_error 可显式
恢复。此次测量不执行 resume。第二题正常记录 intake/task/run failed。216 项相关离线
测试（含 48 新增）、本地 112 quickstart、预启动和最终独立审查通过；41 个证据文件、
10 条制品记录及 76/15/31 项登记指纹匹配。
详见 `specs/117-extended-deadline-acceptance/postrun/report.md`。

产品与时限都变了，不构成单一修复的因果比较。113/115 历史均不改写。下一步先处理
已确认的合同输出协议可靠性，离线审查 evaluator 输入/约束的可验证性；超时无响应，
不能推断服务端长推理、排队或网关等具体原因，不继续以补槽/逐次加长时限替代定位。

最终离线审查另确认 evaluator 的验证范围不匹配：`_validate_probe_suite` 要求每项
hard constraint 有反例，但 snapshot 不能读取源码/执行记录，无法区分相同输出背后的
文件数量、依赖或输入读取行为。117 第一题三个 partial 约束无 result fields，只覆盖
六项输出约束会被当前规则拒绝。下一步明确输出快照、源码交付、执行行为的验证范围，
保留要求并分配独立检查；不以 partial/空字段静默排除，能力不足须提前说明。文件计数
不证明 helper 调用，输入摘要不证明实际读取。该代码问题不构成本次超时原因的证据。

## Feature 116：真实问题等待与评测器准备失败恢复（2026-09-16）

Store 的 pending_input、answer_input、settle_run 和 scheduler 使用相同的非空问题规则。
无问题、空串及 Unicode 空白的 WAITING 由依赖调度处理，不再误报用户待答；stray answer
不能创建回答 artifact 或释放依赖。旧 awaiting_input/null-question 父任务在显式继续时
重新 settle；status 只读，不回写历史状态。无需 schema migration。

自动 evaluator/profile 准备在现有锁内、昂贵调用前写 bundle_preparation_started，失败写
同 attempt ID 的 bundle_preparation_failed，保留 parent/stage/固定 error_category，不存
provider 异常原文。compiler/auditor runtime 异常经输入/证据复验后可显式 resume；合同
保留，无自动重试。取消、完整性错误及终态不提供重试提示。未完成 start 为 unknown，
可能仍在运行，不代表已确认崩溃或零消费。原 bundle_profile_prepared 仍是唯一准备权威。

solve/answer/resume 发生已记录准备失败时返回父任务 JSON、非零退出及 evolution.preparation；
durable run_status 通常仍为 running，effective status 为 failed。JSON/text status 可查询
阶段与安全类别。原冻结 evaluator 恢复不再调用 compiler/auditor，终态恢复不新增尝试。
阶段间 continuation guard 复验 parent，避免观察到取消/预算终止后继续 auditor 或发布；
不等于中断活动 HTTP 或完整的运行中取消编排。

新增 69 项测试和独立审查通过。最终全仓 **5636 passed, 1 skipped in 383.95s**，JUnit
零失败/错误；本地 112 quickstart 仍为 1、2、6、7 分，终态恢复调用次数维持 1/1/1/4/4，
交付副本 1。Ruff、compileall、installed CLI、Specify、111 个文档链接和 diff 检查通过。
实现冻结后无代码/测试修改；按用户授权正常提交并 push。

实现、离线验证和限制见 `specs/116-preparation-recovery-state/validation.md`。没有真实模型
调用；113/115 的各自 0/2、未知用量和冻结证据均不改写，不运行旧 verifier 来更新 pin。
下一步考虑独立登记与模型耗时匹配的新预算验收，继续验证自动 evaluator 和多文件有效
交付；外部 OpenEvolve/Shinka 多文件 seed、全链路预算/取消与 detached 模式仍未完成。

## Feature 115：修复后真实验收 0/2，一例通过合同编译（2026-09-16）

`acfb815` 先推送登记再运行，产品固定 `5e2568f`；原两道 GLM-5.2 任务、输入、预算、
网关、population 2+1/seed 113 与 oracle/holdout 均与 113 一致。预算选择通过合同编译，
随后 evaluator compiler 请求触及 180 秒 HTTP 超时；工作分配在合同编译请求超时。
最终仍 **0/2**，没有冻结 evaluator、候选或交付，24 个 holdout 未运行，质量均 null。

总计三次请求，一次已接受 glm-5.2 响应、两次 timeout。已知用量小计 8625 tokens
（input 1109/output 7516），两次超时消费未知，不能当作零；费用未知。任务耗时
300.944、180.943 秒，guard 停止后续请求，无补槽、澄清、回退或自动重试，无已观察残留
进程。私有响应诊断保留一份完整 5768-byte 合同文本，不反馈模型；超时没有响应可留存。

168 项相关离线测试和预启动审计通过，登记/产品/旧历史均未改。详见
`specs/115-isolated-intake-acceptance/postrun/report.md`。113 与 115 保持各自 /2 分母，
不能声称修复已提升整体完成率，也没有 WebAgent/普通模式对照。

新确认问题：evaluator 准备失败仅写 stderr/空 CLI JSON，无持久失败事件；父任务保留
合同但误为 awaiting_input。Store 将 DAG dependency waiting 误认作用户问题，pending_input
返回 question=null，answer 可能误接收答复。下一步区分真实输入等待并记录可恢复准备失败，
不永久废弃已有合同，也不重开冻结 115 槽位。

## Feature 114：合同编译协议隔离（2026-09-16）

针对 113 后离线确认的入口接线问题，`RuntimeContractCompiler` 优先使用 callable
`run_isolated`，不再把协议编译交给普通 Agent 的总结提示、工具、记忆和历史。旧 runtime
没有该能力时继续 `run`，已有隔离调用失败不回退、不重试。mock 与普通求解保持原路径。
提示词补齐严格 envelope、字段类型及 evolution 的唯一三字段、范围和默认值；严格 JSON、
未知字段/退役策略拒绝和 needs_input 均保留，不自动修复模型输出。

新增 28 项测试，相关五文件 91 项通过，覆盖真实 Hermes+离线模型的实际请求、预算、
无工具/历史/记忆、澄清回答、普通工具循环、subprocess 兼容和同 run 终态零重编译。
产品冻结后全仓 **5517 passed, 1 skipped in 378.36s**，JUnit 零失败/错误；已有 112
quickstart、Ruff、compileall、installed CLI、Specify、105 个文档链接与 diff 检查通过。
完整验证记录见 `specs/114-isolated-contract-intake/validation.md`。

该修复不等于已证明真实有效率提升。113 仍是 `c977eb4` 的冻结 0/2，不改写、不补槽；
下一步以修复后的提交独立登记新验收。当前编译只使用 goal/answer，材料不足需澄清，
尚无向编译器传入已观察 input profile、失败原始响应留存或编译用量持久总账的新实现。
运行配置 fingerprint 不代表产品字节；保留旧指纹以支持已编译/终态恢复。

## Feature 113：当前版本真实多文件验收 0/2（2026-09-16）

登记 `10b844b` 先推送后运行，产品固定 `c977eb4`。预算选择与工作分配各一次真实
GLM-5.2 请求，均在 contract intake 失败：分别为严格 JSON 解析失败和 evolution 含
未知字段。没有生成 evaluator、候选或交付，质量均为 null，24 个预设 holdout 未执行；
不能据此判断多文件求解质量或演化收益。无重试、补槽、澄清回答、切模型或 WebAgent 重跑。

已知用量合计 15958 tokens（input 2771/output 13187），两次响应模型均为 glm-5.2，
usage 完整、无 pending request；费用未知。耗时分别 89.484、131.041 秒，没有触发
180 秒单调用/1200 秒总时限，退出码均为 1，监督器未发现残留已观察子进程。
固定分母、原始 Store/workspace、调用日志和 hash inventory 均保留。

113 的 118 项离线测试与独立审查通过，已有 112 本地 quickstart 再次通过。详见
`specs/113-real-multifile-acceptance/postrun/report.md`。严格冻结登记和历史测量。

后续已确认修复方向：contract compiler 错接普通 Agent 的工具/最终总结系统提示，应
优先使用现成 run_isolated；补全 evolution 的允许字段提示，保留严格解析与无重试。
失败原始响应未留存，不能推断具体错误语法/字段；接线问题已由离线实际请求形状复现，
不声称它是本次响应失败的唯一原因。修复后新效果测量必须另行登记，不重开 113 槽位。

## Feature 112：多文件 evaluator/profile 自动准备（2026-09-16）

`solve --evolve --multi-file --input SOURCE[=TARGET]` 已接通自动准备，无需手写 profile。
`answer`、`solve --resume` 与通用 `resume` 自动恢复请求中的 `bundle_mode=compiled`；
`compile_evaluator=true` 沿用原字段。explicit profile、额外 evaluator command、OpenEvolve
及 detach 不与该模式混用。正常单文件和 111 显式 profile 入口保持兼容。

`evaluator_bundle.py` 的 compile/load 新增 `invocation="snapshot"`，默认 `candidate` 行为
不变。snapshot 复用六文件 envelope/probe/audit/freeze，绑定独立 invocation protocol；
直接消费 108 request/inputs/output，固定 report ID `compiled-bundle`，不构造旧 candidate
或 execution.json。编译器自测、独立 auditor 的约束反例/有效分数排序都通过后才冻结。
snapshot 预检使用严格报告、既有有界 process helper 与快照复验；重复 load 不跑探针或模型。

新 `automatic_solve_bundle.py` 从完整父任务 input_data ledger 构造普通 pipeline profile，
保存于 `parent/bundle-profile.json`，harness 在 `parent/evaluator-bundle/evaluator.py`，输入
固定为 parent/data/raw。prepared event 绑定 semantic/raw profile、contract、冻结 bundle
摘要和全部 artifact rows；六文件与 profile 计入父任务当前 artifact 预算，编译回调后重新
读 budget。已有冻结材料的准备中断可恢复，不重调 compiler/auditor；已登记或 prepared 的
文件缺失/冲突、或有 child 却无 prepared 均拒绝静默重建。普通 deliver 同样复验自动准备。

Agent bundle generator 保持 scoring=None；旧单文件 scoring excerpt 不进入该路径。
compiler/auditor 使用既有 isolated runtime turn，solver context 不主动复制评测器源码或
探针答案。本地进程能力不是 OS 沙箱，环境/依赖摘要只标识声明，不认证安装环境。

独立 `specs/112-automatic-bundle-evaluator/quickstart.py` 已通过。没有显式profile参数，
独立分数 **1、2、6、7**，最终普通父任务交付 7 分源码/输出/report。终态恢复省略演化与
profile flags，contract compiler/evaluator compiler/auditor/Agent/candidate 次数保持
**1 / 1 / 1 / 4 / 4**，交付副本仍为 **1**。产品冻结后全仓 **5371 passed, 1 skipped in
357.87s**（新增94项），JUnit零失败/错误。Ruff、compileall、Specify、installed CLI、
100个文档链接和diff检查通过；冻结测量相对`027a235`未变。详见该目录 `validation.md`。

自动编译保留既有 csv/json/jsonl/text 输入格式、每probe最多32文件/64KiB每文件及每套
probe合计512KiB容量限制，合同输入必须匹配全部登记数据；显式profile模式保留独立能力。自动
pipeline 使用本地Python、不安装依赖，输出256KiB/file，candidate stdout/stderr限64KiB；
timeout是逐调用/逐进程上限，不是整轮全链路总时长。探针通过不等于完整业务正确性。

下一步优先独立登记小规模当前版本真实验收，覆盖自动生成评测器与多文件任务有效率、
质量、耗时和用量，再依据结果处理缺陷或外部 bundle seed 接线。运行中取消/总预算编排、
detached bundle solve 和真实外部producer接线仍后置。没有真实模型、框架或WebAgent调用，
冻结测量不改写。通过验收的工作继续按用户要求及时提交并push。

## Feature 111：普通任务多文件演化与父任务交付（2026-09-16）

`solve --evolve --bundle-profile PROFILE --input SOURCE[=TARGET]` 已接通正常 contract intake、
原生 runtime 和 Agent bundle generator。固定 profile 的语义摘要进入原 evolution request，
不保存 profile/harness/input 存储路径。输入描述必须与父任务完整 `input_data` ledger 的
`data/raw/<target>` size/SHA 匹配，允许相同重复行，拒绝缺失、额外和冲突行；实际演化读取
父任务 staged bytes。无输入任务不要求 intake 前已存在 data/raw。原 profile loader 仍复验
原始输入/harness 资源，恢复仍需显式 profile 与可访问匹配资源，不是 profileless recovery。

父子关系、canonical contract 与固定 `parent/evolution-run` 目录在恢复修改前验证，目录
不跟随 symlink。`solve --resume` 不带 `--evolve` 也保持 bundle mode；通用 `resume` 和
`answer` 支持相同 profile，先校验再消费答复或 stage 新输入。native population 保持独立
评分，bundle 不走旧单文件 materialization/attestation；detached bundle solve 暂不支持。

新 `bundle_parent_delivery.py` 将选中候选已评分的输出直接发布到父任务 `output/`，完整
源码、输入、contract、harness/spec 与 report 放在 `.bundle-deliveries/`。prepared event
固定 portable copy，普通 artifact rows 登记完整 package，输出复用已有 publication journal；
终态 event 为 `bundle_candidate_delivered`。普通 `deliver` 复验后优先返回 manifest/source
描述/report；solve 使用 `evolution.materialization`，status 使用
`evolution.linked.materialization`，均标记 `mode=bundle`。恢复复用已固定 copy，不重跑
Agent、候选或 evaluator；确认回滚保留失败，未知 publication 保留既有恢复语义。

父任务输出沿用 256 KiB 单文件上限，完整 package 和输出计入父任务 artifact budget。
沿用底层至少一个 declared output 的要求；全为 optional 且 evaluator 接受缺失时，仍可
交付完整源码和 report。未写入 prepared event 的中断副本保留但不作为交付权威。

独立 `specs/111-conversational-bundle-delivery/quickstart.py` 已通过普通 intake、四个双文件
候选（独立分数 **1、2、6、7**）、父任务输出/完整源码报告、普通 deliver/status 和不带
`--evolve` 的终态恢复。恢复前后 compiler/Agent/candidate 次数保持 **1 / 4 / 4**，交付
副本为 **1**。产品冻结后全仓 **5277 passed, 1 skipped in 316.71s**，含新增 90 项，JUnit
零失败/错误。Ruff、compileall、Specify、installed CLI、文档链接和 diff 检查通过，冻结
测量相对 `027a235` 未变。完整验证见该目录 `validation.md`。

下一步优先减少显式 evaluator/profile 准备成本，并在实现冻结后独立登记当前版本真实验收；
外部 OpenEvolve/Shinka bundle seed 接线与运行中取消编排仍未完成。本轮只运行本地 fixture，
没有真实模型、外部框架/WebAgent 或新效果测量，不改写冻结历史。已验证工作按用户要求
正常提交并推送，不再长期积累本地提交。

## Feature 110：Agent 自动生成多文件候选（2026-09-16）

`AgentCandidateGenerator(..., bundle_pipeline=pipeline)` 已接通固定 profile 的多文件生成。
新增 `agent_bundle_generation.py`，每次创建私有 `.bundle-generation-*` 目录，保存完整
contract、已验证输入、完整父代源码 map/独立文件和已验证的局部分数反馈。提示词仍限
60 KiB，大上下文通过 `context/context.json` 引用读取；父代完整 map 位于
`context/parent/files.json`，输入副本位于 `context/inputs/<target>`。候选真实执行仍从
`LUNAR_CANDIDATE_INPUT_ROOT` 读独立 staged input。评测器实现不复制到 solver context。

Agent 只返回一个完整 `{entrypoint, files, metadata?, experiment?}` JSON；重复键、混合
单/多文件字段、路径/大小错误均拒绝，保留旧 experiment/playbook/search directive。
AgentResult 原有 1 MiB 文本上限仍有效，不等于底层 bundle 的 16 MiB 全容量。调用前后
复验原始证据与 staged context；生成失败不会变成 score。旧单文件行为保持兼容。
`CommandAgentAdapter` 直接返回 bundle 时保留原始 JSON，避免丢失 helper 或提前吞掉重复键。

`evolve-bundle` 现在在 `--generator-command`、`--agent-command`、`--agent-runtime` 三种
方式中明确选一。原生 runtime 支持 subprocess/openai-compatible 及已有有界工具循环；
参数和未使用的选项先于 home/Store 校验，相对 workspace 正常使用。不同生成方式/模型/
循环设置参与身份绑定，原 command fingerprint 不变；跨方式不能恢复旧 run。独立评测
仍由显式 profile 负责，Agent 自报分数无权参与选优。通用 mock 不保证输出有效 bundle，
本轮 native runtime 验收使用真实本地 subprocess 与离线模型替身。

本地真实 Agent/runtime fixture 已完成四个双文件候选、helper-only 改进、独立分数
**1、2、0、9**、完整交付及 terminal resume；越界候选自报高分仍未入选。独立可运行
`specs/110-agent-bundle-generation/quickstart.py` 评分 **1、2、6、7**，交付 7 分候选；
恢复前后 Agent/candidate 次数均 **4 → 4**。产品冻结后全仓 **5187 passed, 1 skipped in
284.75s**（含新增 74 项），JUnit 零失败/错误。Ruff、compileall、Specify、installed CLI、
quickstart 和文档链接检查通过，冻结测量相对 `027a235` 未变。最终验证记录见该目录
`validation.md`。

本轮先将既有 40 个已验证提交推送到 origin/main（`d863df6`），继续按用户新指示推送
本功能。没有真实 provider/外部框架/WebAgent 调用或新效果测量。下一步接正常任务路由、
evaluator 准备和 parent-run 的交付/统一恢复；外部 producer 的多文件 seed 导入尚未接通。

## Feature 109：多文件原生 population 与完整交付（2026-09-16）

已把 Feature 103–108 接入现有 population/archive/controller，新增 `bundle_evolution.py`
和 `bundle_delivery.py`。`CandidateDraft.from_files` 表达含入口的完整 UTF-8 source map；
普通 Candidate 保留入口 `source_sha256`，另用显式 `bundle_evidence` 绑定整个 bundle、
plan/admission/completion 和独立评测。多文件 receipt 为 v2，原 v1 字节/摘要与旧 Candidate
JSON 保持兼容。同一 execution/evaluation 不能登记成两个不同 candidate ID。

`MultiFileCandidatePipeline` 固定 candidate argv、完整输入描述、harness/spec、显式环境与
限额，并在启动前重验契约/配置及实际输入/harness 字节。完整源码保存在原 candidates
目录，每次运行另建 `evolution/bundle-attempts/.bundle-run-*`。执行/评测失败或 archive
发布未知均保留已分配现场；只清理未发布的可复用源码 staging。登记复用原 record/receipt/
archive 的事务与校验，选优、谱系、代数、island、实际迁移、失败 outcome 和 resume 沿用
现有 population 循环。bundle parent 的 command request 包含复验后的 `parent_source_files`，
novelty 使用全部源码。配置/源码/评测漂移时不重用旧证据。

新 CLI `evolve-bundle CONTRACT --profile PROFILE --generator-command COMMAND --workspace ROOT`
提供显式本地生成、执行、评分、选优、terminal resume 与可选 `--destination-root` 交付；
声明/profile 校验先于 home/Store 初始化。`--resume --run-id ID` 使用相同配置只复验终态，
不新增候选执行。`candidate-bundle inspect-delivery PATH [--delivery-sha256 SHA]` 无初始化
只读复验。公开 Python pipeline、source accessor 和 delivery inspection API 已导出。

Controller 交付前检查 Store 绑定的 contract/archive/state/result、全部 v2 record/receipt、
事件和 canonical best。交付包含完整源码、已评分输出、输入、contract、harness/spec 和
report；165 文件及长路径有完整 fixture。新的私有目录保存可移植 byte manifest，原 107/108
inode-bound 证据保留原位，不复制后冒充原记录。终态完成且有有效结果时，可交付包含早期
可恢复候选失败的运行，失败结果仍保留。旧 single-file materialization 明确拒绝 bundle。

真实本地双文件 fixture 的独立分数为 **1、2、0、9**；越界候选自报高分仍无效，最终选中
9 分候选。可运行 quickstart 使用父代完整 helper 源码产生 **1、2、6、7**，交付 7 分版本；
原样执行通过，terminal resume 前后 candidate/generator 次数均 **4 → 4**。聚焦覆盖旧
v1 hash、helper-only 身份、迁移、恢复、源码/评测漂移、发布失败/未知、完整交付与 CLI。
产品冻结后全仓 **5113 passed, 1 skipped in 277.57s**（含新增 100 项），JUnit 零失败/错误；
全 src/tests Ruff、compileall、Specify、installed CLI、公开 API 和可运行 quickstart 通过。
复制后的交付也通过原 digest 复验。详见 `specs/109-bundle-population-integration/validation.md`。

下一步优先把正常任务入口和 Agent 多文件生成接到这条已通路径，再接 parent-run 的正常
交付、统一预算/取消/恢复。OpenEvolve/Shinka 的 SeedManifest 与通用 material 仍为单文件；
真实外部 producer、当前版本模型效果和收益尚未验收，新的测量须独立登记。不新增用户
attestation 流程。输出仍是评测时快照；不认证 host interpreter/依赖闭包，不是 OS 沙箱。
本轮没有模型/provider/外部框架/WebAgent 运行，历史冻结测量不改；只在本地 main 提交，
不 push。README、architecture、系统评估、路线图和 109 specs 已同步。

## Feature 108：多文件独立评测与输出快照（2026-09-16）

新增 `candidate_evaluation_spec.py` / `candidate_evaluation.py`，公开
`CandidateEvaluationSpec`、`evaluate_candidate_execution`、`inspect_candidate_evaluation`。
CLI 为 `candidate-bundle evaluate` / `inspect-evaluation`，在 config/home/Store 前分派。
admission 必须固定 spec.pin() 和 `candidate_output_contract_sha256(contract.outputs)`。
指纹包含实际 harness 文件字节、argv、显式环境、报告 ID、协议与时长/输出限额。

评测只接受 recorded 且进程成功的执行记录；核对 intent 的 workspace/input inode，并持有
复验全部三份记录、源码、输入、harness 与声明输出的字节/身份观察。共享祖先目录 fd 降低
句柄放大。新建私有 evaluation 目录保存输入、输出、harness 和 request，harness 从快照
读取并独立计算约束/目标，候选不再运行。缺失或格式不合格的必需输出直接产生无效零分，
不启动 harness；可选输出存在时同样必须通过格式检查。

复用旧 OutputSpec/EvaluationReport 语义，JSON/JSONL 和报告增加严格 UTF-8、重复键、
非有限数检查。报告要求完整七字段、schema 1 和匹配 evaluator ID。106 process helper
增加原始字节接口供 evaluator 完整采集 32 KiB 报告，旧 runner 16 KiB 文本行为保持兼容。
保存 raw report 和 canonical evaluation manifest；检查只读绑定保留快照，失败现场保留，
缺 manifest 不能修复或视为有效评分。每次重新评测新建目录，永不重跑候选。

输出快照明确发生于**评测时**，不是执行退出时输出证明。inspect 的可选 saved digest
固定 manifest；本地一致性检查不认证 host interpreter、依赖闭包或真实执行。harness 是
可信本地代码，要求只读快照并向 stdout 返回报告。调用方可保存返回的 evaluation_path。

双文件本地样例评分 9.0，launch counter 保持一次。108 共 **306 项通过**；产品代码冻结后
全仓 **4976 passed, 1 skipped in 236.854s**，随后新增的 37 项测试也通过，无后续产品改动。
最终 collection 为 5014 项，合计 **5013 passed, 1 skipped**。Ruff、compileall、Specify、
installed CLI 与 quickstart 通过，见 `specs/108-candidate-independent-evaluation/validation.md`。
未运行模型、provider、外部框架
或新真实测量，历史冻结材料未改。继续只在本地 main 提交，不 push。

下一步：把完整 bundle 与该评测结果接入 Candidate/receipt/archive，再串联 population/
producer/controller，验收双文件生成、执行、评分、选优和最终交付。统一入口/恢复和当前
版本效果验证仍未完成；原单文件闭环保持兼容，不引入新的用户 attestation 流程。

## 当前整体评估与下一阶段验收（2026-09-16）

已完成基于 `af4f8d8` 的代码/历史证据盘点，见
`docs/system-readiness-20260916.md`。旧单文件 population 已有完整演化和恢复交付闭环；
新多文件链路止于 Feature 107 execution record。下一阶段按四个里程碑推进：多文件
exact evaluator/输出绑定 → Candidate/receipt/archive/搜索与交付接线 → 统一入口和恢复
→ 当前版本真实验收。该盘点形成时 Feature 108 尚未实现；最新进展见上方 Feature 108。
该次盘点只更新评估和路线说明，无产品改动或新实评。

普通流程 069 历史有效 2/2、082 分阶段最终有效 0/2，应分别保留，不能称为当前版本
整体 WebAgent parity。OpenEvolve/Shinka 已有 adapter/exporter 和 fixture，真实生态搜索
收益未测。远端服务、repository/workflow、训练/RL 和更多算法移植后置，不作为本地融合
版本完成的前提。后续优先闭合用户可用路径与真实效果验证，避免以新增协议数量代替验收。

## Feature 107：多文件候选持久化执行证据（已完成，2026-09-16）

新增 `src/lunar_evolution/candidate_execution_evidence.py`、`run_candidate_execution_recorded`、
`inspect_candidate_execution_record` 和 `CandidateExecutionRecord`。CLI 为
`candidate-bundle run-recorded` / `inspect-execution`，均在 config/home/Store 初始化前分派。
调用方指定不存在的 attempt 目录；完整 plan/admission/pins 和 source/input 字节复验后
独占创建 0700 目录，先 fsync canonical launch intent，再进入 Feature 106 runner 一次。
任意已有目录（包括空目录或中断现场）都不授权重跑；不同新目录代表另一次显式执行。

intent 绑定 plan/admission/bundle/contract、source/input 文件表摘要、workspace/input/attempt
device/inode 和随机 nonce。runner 返回后，result 绑定既有 path-free metadata 投影及其
canonical digest；completed 绑定 intent/result 原始字节 SHA-256、size、device/inode。
文件使用 no-follow、独占临时写入、fsync、no-clobber 发布和重读。关闭异常经过固定错误映射，
共享 DirectoryChain 在报告失败前释放其余 fd。任何失败保留已分配 attempt，不合成执行结果。

inspect 只读检查原声明和证据，原源码/输入可在执行后变化；它不把后验字节当作运行证明。
有效但不完整记录返回 uncertain；完整记录返回 recorded，并保留独立的 runner process status。
相同字节但 inode 被替换、摘要漂移、symlink/FIFO、未声明节点及非法 schema 均拒绝。
不创建 Store、Candidate、score、receipt、archive、attestation 或 resume 状态。

106 同步补修 32 项命令边界、小于 0.05 秒的 timeout 预算突破、可执行文件 no-follow
目录/元数据观察、资源释放和 CLI contract pin；106 focused **32 passed**。107 已覆盖真实
双进程争用、五个 os._exit 崩溃阶段、写入/fsync 中断、路径/身份漂移、无初始化和 installed
CLI；107 focused **107 passed**，最终全仓 **4707 passed, 1 skipped in 232.92s**，JUnit
确认零失败/错误。全 src/tests Ruff、compileall、Specify、diff check 和可运行 quickstart
通过；旧封存测量文件未改。详情见 `specs/107-candidate-execution-evidence/validation.md`。
本轮仅本地 main 提交，不 push。

下一项优先设计和接入多文件 exact evaluator/output-contract，再连 Candidate receipt/archive；
新 runner 的 attestation/resume 尚未设计实现。旧 090/091/095 协议仍仅服务原单文件
materialization 生命周期。未运行外部框架、模型、provider 或 campaign，没有新增效果结论。

## Feature 106：候选 bounded execution runner（已完成，2026-09-16）

新增 `src/lunar_evolution/candidate_execution_runner.py`、`CandidateExecutionRunner` 和静态
`candidate-bundle run` CLI。runner 在启动前重建并重验 workspace plan、execution admission、
源码 bundle、staged input、caller pins 以及 workspace/input 的实际目录 inode；共享普通祖先
目录允许，但同根和互为父子目录拒绝。有效命令是 plan 的显式 argv 加 bundle entrypoint，
固定 cwd 为 candidate workspace，`shell=False`、`stdin=DEVNULL`、显式环境和独立进程组；只
允许 admission 的 `max_processes == 1`，不声称监控候选自行 fork 的进程数。

stdout/stderr 用 selector 增量读取并有界保留，输出超限或 timeout 会终止进程组并在有限宽限期
内回收；启动失败、非零退出、超限、timeout 和清理不确定性使用固定
`candidate_execution_runner_*` 错误。结果 JSON 不包含本地路径或原始 stdout/stderr，只返回状态、
字节数和身份摘要；Python result 对象保留受限文本供调用方处理。runner 不初始化 Store/home，
不调用 evaluator，不写 Candidate、receipt、archive、execution.json 或恢复状态。

新增基础、文件边界和 installed-CLI fixture，覆盖成功、非零退出、timeout、输出溢出、后代
管道、symlink/FIFO/根重叠、输入和源码漂移、reserved env、caller pin、启动失败及无副作用。
Feature 106 focused suite 当前 **15 passed**；后续独立 Feature 才处理 execution evidence、
exact evaluator、launch intent 和 resume。未运行真实 OpenEvolve、ShinkaEvolve、WebAgent、
模型、provider 或 campaign，不产生算法效果结论。

## Feature 105：候选执行输入 staging（已完成，2026-09-16）

新增 `src/lunar_evolution/candidate_input_staging.py`，公开 `stage_candidate_execution_inputs`、
`StagedCandidateExecutionInputs` 和 `CandidateInputStagingError`。完整 admission、plan 与
caller pins 在两根目录 IO 前重验；输入按声明 target 从 caller source root 读取，在新建
`.candidate-inputs-*` 私有目录中独占写入，再重读目标 size/SHA-256。仅复制声明输入，支持
二进制、嵌套目标和空文件；目录 0700、文件 0600。目录实际 device/inode 身份阻止同根、
嵌套和大小写别名绕过。已有 admission 字节观察不跳过新的源检查。

静态 CLI 为 `candidate-bundle stage-inputs ADMISSION --plan PLAN --input-root ROOT
--staging-root ROOT --json`，在 config/home/Store 初始化前分派。API metadata 不含路径；
CLI 单独返回 `input_path`，成功目录交由 caller 管理和清理。失败和中断只清理已确认属于本次
操作的文件，外来替换保留并报固定 cleanup 错误。共享 PrivateTree 同时补已知 inode 的
初始化失败清理，保留 Feature 103 的固定错误码；DirectoryChain 构造中断释放已打开 fd。

Feature 105 三文件测试 **96 passed**；installed CLI quickstart、Ruff、compileall 和 diff
check 均通过。最终全仓 **4568 passed, 1 skipped in 235.87s**，包含新增 Feature 103 初始化
失败兼容性回归。规范、可运行 quickstart 和验收见 `specs/105-candidate-input-staging/`。

该功能不启动 runner、import 候选、安装依赖、调用 evaluator，也不创建 Candidate、receipt、
archive 或恢复状态。目录返回后可被修改，未来 runner 必须在执行时重新校验。下一步是多文件
真实 runner、exact evaluator、execution evidence 和恢复集成。未运行真实框架、模型或新效果
测量，历史冻结测量文件未改；继续只在本地 `main` 提交，不 push。

## Feature 104：候选 execution admission（已完成静态 admission 边界，2026-09-16）

已实现 `src/lunar_evolution/candidate_execution.py` 的静态、path-free admission API：
`CandidateExecutionInput`、`CandidateEvaluatorPin`、`CandidateExecutionBudget`、
`CandidateExecutionAdmission`、`VerifiedCandidateExecutionAdmission`，以及
`build_candidate_execution_admission`、`parse_candidate_execution_admission`、
`validate_candidate_execution_admission` 和 `admit_candidate_execution`。声明绑定完整
Feature 103 workspace plan digest、bundle/contract、排序后的逻辑输入描述、非零
dependency/environment commitments、exact evaluator pin、可选 output-contract digest 与
有界 timeout/output/input/process budget；canonical digest 不含本地路径和自身 digest。

结构 parse/validate 完全内存内进行。可选 `input_root` 使用已有 descriptor-based no-follow
reader，对每个声明文件做有界 size/SHA-256 复核，并在任何输入 IO 前校验 plan、bundle、
contract、dependency、environment、evaluator、output-contract 和 admission caller pins。
省略 `input_root` 时 `observed_inputs` 为 `None`。该层不启动 runner、不 import 候选、不安装
依赖、不检查 host environment、不调用 evaluator、不初始化 home/Store，也不写 Candidate、
receipt、archive、resume 或 materialization ledger；它不是执行回执。

Feature 104 focused 测试当前 **195 passed**（含 installed CLI fixture）；全仓回归
**4471 passed, 1 skipped**，Ruff、compileall 和 diff check 已通过。静态
`candidate-bundle admit-execution` CLI 已在普通配置/Store 初始化之前分派，并覆盖成功、输入
size/hash、plan/pin mismatch、entrypoint 不执行及 no-home/Store。不要把它描述成真实
候选执行、模型、evaluator、OpenEvolve/WebAgent 或效果测量。

## Feature 103：候选 workspace 物化（已完成，2026-09-15）

已冻结并开始实现独立的 `candidate_workspace.py`：将 Feature 102 已验证的多文件 bundle
复制到新建私有目录，逐文件 no-follow 有界读取、独占写入、fsync 和目标重读校验，失败清理
全部临时目录。`CandidateWorkspacePlan` 绑定 contract/bundle、entrypoint、排序文件表摘要、
显式绝对 runner、空默认环境、超时和输出上限；不含本地 workspace 路径。

静态命令为 `candidate-bundle materialize MANIFEST --source-root ROOT --contract CONTRACT
--workspace-root ROOT --command /usr/bin/python ... --json`。它不启动进程、不 import/evaluate、
不初始化 Store/home、不写 Candidate/receipt/archive，也不改变现有 Candidate、SeedManifest
或 materialization ledger。聚焦回归 `266 passed, 1 skipped`，Ruff 和 compileall 通过；安装 CLI
fixture 已确认只复制声明文件、入口不执行且不创建 home。全仓回归与本地提交已完成，未 push。

Feature 104 已完成 admission API、静态 CLI、installed-CLI side-effect fixture 与最终全仓回归。
详见本文件顶部 Feature 104 记录；它仍是静态声明，不是 runner 执行能力。

## Feature 102：多文件候选源码包（已完成，2026-09-15）

新增独立 `CandidateSourceBundle`，把问题 contract、entrypoint 以及每个声明源码文件的
路径/大小/SHA-256 绑定到完整 canonical bundle digest；按路径排序，不受 JSON 格式或
文件声明顺序影响。公开 parse/validate/verify API 深层重建 DTO；要求 contract pin，
可选 caller bundle pin，两者在源文件 IO 前检查。返回 bundle 元数据、文件数和总字节。

文件限定 1–64 个、每个 0–1 MiB、总计 ≤16 MiB；manifest ≤128 KiB。路径必须是 NFC
相对 POSIX，拒绝 traversal、控制/格式字符、`.git` 组件、大小写组件别名和文件/目录
前缀冲突。空文件合法，源码只接受无 NUL 的 UTF-8。复用共享 descriptor reader，
有界读取且拒绝 symlink、非 regular file、大小/hash 漂移和观察到的文件/目录替换。

新命令 `candidate-bundle validate MANIFEST --source-root ROOT --contract FILE
[--bundle-sha256 SHA] --json` 在普通配置初始化之前分派，只输出 status、两个摘要和
文件数/字节数，不创建 home/Store，不执行、导入、评测或登记候选。contract 文件也使用
同一有界 no-follow reader；现有单文件 Candidate、SeedManifest、producer schema 不变。

新增三文件 **159 passed**（核心 84、独立文件边界 45、CLI 30）；和全部 benchmark 联合
**346 passed in 0.73s**。独立终审无 blocker，实际安装 CLI quickstart 双文件/131 bytes
验证成功，helper 同大小改写被拒绝，home/执行 marker 均未创建。全 src/tests Ruff、
compileall、Specify 与 601 个历史封存文件对照均通过。全量 **4169 passed in 202.02s**，
JUnit 确认零失败/错误/跳过；本轮统一在本地 `main` 提交，不 push。详情见
`specs/102-candidate-source-bundle/validation.md`。

本功能只验证声明的源码字节，不扫描未列文件，不保证多文件原子快照、import closure、
依赖/环境、producer 身份、语法或算法有效性。未运行真实框架、模型、provider、WebAgent、
远端服务或 campaign，无新增算法效果结论。下一步需独立设计多文件 workspace 的执行、
输入/依赖/环境契约与 exact evaluator/receipt/archive/resume 关联，再接 repository
producer；workflow graph 候选和真实固定条件对照测量仍未完成。

## Feature 101：comparison receipt 完整计划绑定（已完成，2026-09-15）

099/100 的 comparison ID 只绑定共享条件，原先即使同名 arm 换 benchmark 版本、发布摘要
或互换 envelope，旧 receipt 仍可能通过。现新增可选 `plan_sha256`，绑定完整规范化 plan
（含 arm ID 与 benchmark name/release/publication 的关联），并参与 result ID。合法无 pin
的 099/100 JSON、result ID、digest 已用 `d81145f` golden values 验证保持兼容。

新工厂 `BenchmarkComparisonResult.from_plan(plan, arms)` 在无 IO 的结构复验后显式创建
带 pin 的 receipt；不替旧 receipt 自动补 pin，也不代表此前已运行过该计划。API 的
`expected_plan_sha256` 与 CLI `benchmark-comparison validate-result --plan-sha256 SHA`
要求 caller pin、receipt pin 和完整 plan digest 全部匹配；legacy receipt 无法满足该请求。
输出分别给 `plan_bound`、`evidence_bound` 和 canonical `plan_sha256`，避免混淆计划关联
与实际证据字节校验。pin 是 canonical plan digest，不是格式化 JSON 文件的原始字节摘要。

新增 `validate_benchmark_comparison_plan`，深拷贝重验 plan 结构及所有 arm 的共同身份。
task admission 同样重建 DTO，拒绝内存对象被改为 root 外路径、超限大小或非法 schema。
100 的 fd reader 已抽到私有 `_benchmark_files`，task/plan/result/evidence 和公开输入共用
no-follow、有界读取及读后文件/目录名复核，保留各 API 固定错误码。task/plan/input 也采用
无祖先 symlink、无 `..`、4096 UTF-8 字节/128 绝对组件边界；单输入仍限 16 MiB。

新增四文件共 91 项；所有 benchmark 测试 **187 passed**。全量 **4010 passed in
229.10s**，JUnit 确认零失败/错误/跳过；全 src/tests Ruff、compileall、Specify、diff
check 通过。独立终审无剩余 blocker，实际安装 CLI fixture 已验证双绑定成功、版本变化
拒绝且不创建 home。051/074/076/078/082 的 601 个封存文件相对 `027a235` 未变。

README、architecture、roadmap、101 specs 和 Specify 当前 feature 已同步。仅本地 `main`
提交，不 push；未运行真实框架、模型、provider、WebAgent、远端服务或 campaign，不新增
算法效果结论。该 pin 只覆盖当前 DTO 已表达的字段，不认证 producer、未表达的命令/配置
或真实测量；文件检查不是多文件原子快照。真实对照测量与多文件/repository/workflow
candidate 契约仍未完成，后续另行设计。

## Feature 100 补修：有界证据读取与文件替换检测（已完成，2026-09-15）

复核发现原实现检查路径后再打开文件，期间发生文件/目录替换可能仍通过校验；result JSON
也在完整读取后才限制大小。现改为逐级目录 fd + `O_NOFOLLOW` 打开，文件使用
`O_NONBLOCK`，读取前验证 regular-file 类型和大小，读取后核对 device/inode/size/mtime/
ctime、文件名及祖先目录名绑定。result JSON 最多读取 128 KiB + 1 字节，evidence 最多
读取声明大小 + 1 字节（单文件上限 16 MiB）。同大小改写、文件或目录替换、超限均拒绝。

修复 status 非字符串、超大整数分数、非法 Unicode 路径和超长 JSON 整数的异常泄漏；
descriptor 字段必须同时非 null 或同时省略，显式 bind API 不再接受 None root 跳过校验。
合法 099 receipt 的规范化内容、result ID 和 digest 与旧实现比较一致。文件路径范围收紧：
result JSON/evidence 都拒绝祖先 symlink、`..`、超过 4096 UTF-8 字节或 128 个绝对路径
组件；macOS 的 `/tmp`、`/var` 别名也在此列，应使用实际路径。检查是逐文件的有界观察，
不保证多 arm 原子快照，也不证明外部测量真实或评分正确。

新增三文件共 66 项回归；六个 benchmark 文件 **88 passed**。主仓全量 **3919 passed in
221.00s**，JUnit 确认 0 failure/error/skipped；全 src/tests Ruff、compileall、Specify、
diff check 通过。独立审查无 blocker，额外 144 次异常字段探测无未捕获异常。实际 CLI
离线 fixture 已验证成功、文件变化拒绝且不创建 home。051/074/076/078/082 的 601 个
tracked 封存文件相对 `027a235` 保持原样。上轮记录 3854 是统计错误，修复前实际 pytest
collection 为 3853；本轮计数直接来自 pytest/JUnit。

本轮只修复 100，不新增 Feature 101。README、架构、quickstart、验证记录和 Specify 当前
feature 已同步；未运行真实框架、模型、provider、WebAgent、远端服务或 campaign，不产生
效果结论。只在本地 `main` 提交，不 push；真实对照测量与多文件/repository/workflow
candidate 仍需独立设计，尚未完成。

## Feature 100：benchmark comparison evidence binding（已完成）

在 099 comparison result receipt 的 `evidence_sha256` 之上增加可选的
`evidence_path` + `evidence_size` 描述。调用方通过
`benchmark-comparison validate-result ... --evidence-root ROOT` 或
`bind_benchmark_comparison_result_evidence` 时，系统只读检查每个 arm 的相对 POSIX 路径、
非符号链接 regular file、大小、inode/device 稳定性和 SHA-256；缺失描述、路径穿越、符号
链接、文件变化和摘要不匹配均拒绝。未提供 evidence root 时，099 的 digest-only receipt
继续兼容。描述字段进入 result ID，因此路径或大小变化也会产生不同身份。

本功能只绑定操作者提供的本地证据字节，不证明外部框架、模型或 evaluator 的真实性，
不导入分数到 Lunar candidate、score 或 iteration，也不启动任何框架、模型、provider、
远程服务或 campaign。聚焦 benchmark result/comparison/CLI 回归 **11 passed**，全量回归
**3854 passed**，Ruff、compileall 与 diff check 通过；
当前分支 `main`，不 push。下一层仍是多文件/repository/workflow candidate 契约，以及
在新预注册协议下进行真实 SkyDiscover/LLM4AD/WebAgent 对照测量。

## Feature 099：benchmark comparison result envelope（已完成）

新增 `BenchmarkComparisonResult` 与 `ComparisonArmResult`，把未来固定条件测量的每 arm 状态、
计数、耗时、有限分数摘要和 evidence SHA-256 绑定到 098 comparison plan。严格 canonical JSON、
重复键/非有限值/越界字段拒绝，result ID 由 plan comparison ID 与 arm 摘要稳定派生；admission
要求每个计划 arm 恰好出现一次。该层只保存测量证据，不写入 Lunar candidate、score 或 iteration，
新增静态 `benchmark-comparison validate-result` 命令，在普通配置初始化前复用 097 plan/input
pin admission 并绑定 result arms，只输出 ID 与摘要。该层不运行任何框架、模型、evaluator、
provider 或远程服务。聚焦回归 **18 passed**；详见
`specs/099-benchmark-comparison-result/validation.md`。

## Feature 098：固定条件 benchmark comparison plan（已完成）

已开始在 097 task envelope 之上冻结多 arm comparison plan：所有 arm 必须共享 task comparison
digest、contract、model、exact evaluator 与物理预算；framework 名称、score、generation/run ID
不进入比较身份。计划只做严格解析和只读 admission，不运行 SkyDiscover、LLM4AD、Lunar、模型、
evaluator、scheduler 或 Store。098 模块与 097 admission 已完成，聚焦回归 **82 passed**；本轮
没有运行真实 benchmark 或产生效果结论。详见 `specs/098-benchmark-comparison-plan/validation.md`。

## Feature 097：benchmark/task envelope（已完成）

已完成面向 SkyDiscover/LLM4AD 的离线 `lunar-benchmark-task-v1` task envelope：严格规范化
JSON、benchmark/task/contract/input/model/evaluator/budget 身份、稳定 envelope/comparison digest，
以及只读输入字节和 caller pin admission。新增静态 `benchmark-task validate` CLI，在普通配置
初始化前分派，不启动框架、模型、evaluator、scheduler 或远端服务。聚焦测试 **79 passed**，
全量回归 **3842 passed**；本轮不运行真实 benchmark 或生成效果结论。详见
`specs/097-benchmark-task-envelope/validation.md`。

## Feature 096：外部 producer CLI 热启动

已打通用户可直接操作的 Shinka → Lunar population 工作流。新增
`export-shinka-result RESULTS_ROOT --output NEW_ROOT --contract FILE --producer-fingerprint SHA`，
复用现有静态 SQLite exporter；可按重复 `--program-id` 有序选择，或用互斥的 `--top-k`
（默认一条）。命令在普通配置初始化前分派，输出 exported、候选数量和 envelope 摘要，
不创建 Lunar home/Store，也不启动 producer 或 evaluator。

新增 `evolve --producer-result ROOT --producer-fingerprint SHA [--producer-id NAME]`，
仅供 population 使用，并要求原有 `--evaluator-command` 本地 exact harness。它与
`--seed-manifest` 互斥，也不允许 seed dependency/environment 手工覆盖。新公开 API
`prepare_producer_seed_manifest` 复用原 generic adapter 的 envelope/material/pin 校验，
只在内存构造未 admission 的 SeedManifest。随后由原 controller seed admission 唯一地
执行评测、生成 receipt 和提交候选，避免提前或重复评测。dependency 是 source-bundle
摘要，environment 是原 adapter 的 declared-protocol 协议声明摘要，不认证外部框架的运行环境或依赖。

普通 resume 保留完整 seed/ordinary-candidate 复验；`--detach` 传递原始 producer root、
fingerprint 和可选 name pin，不把临时 manifest 或推导参数伪装为用户输入。已用真实本地
Python fixture 验证 Shinka SQLite 导出、good/bad mixed admission、外部高分不覆盖本地
0.42 分、全 invalid 时不启动搜索、恢复复验与稳定 seed ID，以及 source/pin/evaluator/
envelope 漂移拒绝。没有运行真实 Shinka/OpenEvolve、模型、provider、远端服务或 campaign，
没有新增算法效果或 WebAgent 持平结论。

实现、聚焦测试、独立审查、离线构建和最终全量验证已完成：**3831 passed**。操作说明见
`specs/096-producer-cli-warm-start/quickstart.md`，本轮完成本地提交，不 push。
下一层待办仍是 SkyDiscover/LLM4AD benchmark/task envelope 与独立真实验证；本功能只
处理已有的本地单文件候选，未新增 live runner、网络同步、repository/workflow candidate。

## Feature 095 结项：显式执行证据登记

新增 `attest-materialization-execution PARENT CHILD --receipt FILE`。它用于 090 launch intent
已存在、候选留下原始 `execution.json`、但尚未开始 091 登记的现场。操作者主动提供
canonical schema 1 确认文件，绑定 parent/child/唯一 task、完整 launch digest、candidate/
attempt、execution SHA-256/size/device/inode 和 Store 内唯一 nonce。系统不会从原始执行
文件、诊断或证据包自动生成授权。用白话说：人工确认“只登记这个任务的这一份执行结果”，
不授予重跑候选权限，也不证明执行结果是真实或成功的。

CLI 先解析并冻结同一份最多 16 KiB 的 receipt，再复制 093 有界 DB/WAL 到私有临时目录
预检。校验失败不会初始化源 home/数据库或改写运行证据。校验通过后，在现有 090
生命周期锁内复核 workspace/budget、launch owner、候选和 execution 原始文件，拒绝
临时 execution、指纹漂移、已用/冲突 nonce、以及仅存在于数据库的下游证据。

091 journal 可选嵌入完整 receipt，上限扩为 24 KiB；普通执行 journal 内容保持原状。
`materialization_execution_attested` 与 `materialization_execution_prepared` 在同一个 FULL
SQLite transaction 中登记，通过 receipt/journal SHA-256 和 prepared.attestation_sha256
相互绑定。原执行 artifact 和 commit batch 仍复用 091，不另建表或事后补审计。nonce
在同一 Store 的所有 run 中唯一；相同 receipt 精确重试幂等，另一 nonce 不能替换已有 child 授权。

完整 attested journal 已写、DB 尚未 prepared 时，可以显式重交同一 receipt；普通 resume
仍不能创建 preparation。prepared 后，中断恢复直接校验 journal 中保留的 receipt，不依赖
原确认文件，可继续 091 并通过 092 验证输出、发布和完成终态，全程不重跑候选。
成功/失败的本地候选 fixture 均验证了这条交付链。partial/unattested journal、缺失 bytes
及任何下游 088/089/092 记录仍拒绝，保留现场。093/094 已支持新事件和摘要关联检查，报告
和 bundle 不输出 receipt 正文或 nonce，仍不提供恢复权限。

最终主仓全量 **3788 passed in 224.61s**，新增三文件共 189 项（集成 75、Store 98、
诊断 16），已包含于全量。Ruff、compileall、Specify 与 diff check 通过，601 个封存文件
相对 `027a235` 保持不变；Store、恢复/CLI、诊断和文档独立审查无剩余 blocker。详见
`specs/095-manual-execution-attestation/validation.md`。实现已完成并纳入本轮本地提交。
本轮仅使用离线 fixture/本地测试，没有启动真实
模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或 campaign，没有新增算法
效果或 WebAgent 持平结论；不 push。其余边界：人工 statement 不认证外部身份，不证明
进程实际运行，不识别/终止未知存活进程，不保证 exactly-once 或成功交付，协议记录暂无 GC。

更新时间：2026-09-14
当前仓库：`/Users/liminghan/Documents/lunar_agent`
当前分支：`main`
远端：`git@github.com:vchive/Lunar-Evolution.git`
提交身份：`vchive <vchive@users.noreply.github.com>`

## Feature 094 结项：materialization 证据包导出

Feature 094 新增 `export-materialization-evidence PARENT CHILD --output FILE`，在普通 CLI
初始化之前读取 093 私有数据库/WAL snapshot，并复用该快照生成五阶段诊断。它只导出固定
schema 1 的诊断 report、event identity/type + payload size/SHA-256、artifact identity/kind
+ size/SHA-256；不导出 workspace、goal、命令、原始 payload、候选/输出字节或日志。报告
仍固定 `recovery_eligibility: not_assessed`，证据包不提供恢复权限或成功证明。

输出必须是显式目标，父目录必须已存在，拒绝目标/临时文件冲突、符号链接和任一 run
workspace 内的路径。最多 256 KiB 的 canonical JSON 通过 O_EXCL 同目录临时文件写出并
fsync，再 no-clobber link 到最终文件，最后同步目录；不会覆盖已有文件，也不写源数据库、
workspace、事件、receipt 或锁。相同稳定现场导出到不同路径的 bytes 相同。busy/unavailable
现场在目标创建前拒绝。

聚焦验证 13 passed in 3.84s；Ruff、compileall、Specify 与 diff check 通过；主仓全量
**3599 passed in 205.44s**。没有启动真实模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或
campaign，也没有新增算法效果结论。剩余边界保持：bundle 是脱敏观察清单，不是认证的
外部真实性证明；不解决 raw execution/未完整 prepared 的人工授权缺口，不推断存活进程。

## Feature 093 结项：只读 materialization 诊断

Feature 093 新增 `diagnose-materialization PARENT_RUN_ID EVOLUTION_RUN_ID`，用于查看 090–092
保留的启动、执行登记、delivery plan、输出批次和终态凭据。命令在 CLI `_config()` 之前
分派，不创建 home、数据库、Store、memory 或协议锁，也不调用 runner、promoter、rollback
或任何 recovery/publish API。它把 state.db 和可选未 checkpoint 的 state.db-wal 以 no-follow
有界复制到源目录之外的临时目录，只在副本上开启 SQLite；源内容、目录项和业务记录保持
不变（普通读取造成的 atime 变化不在保证内）。源数据库 rollback journal、WAL/DB 超限、
坏节点、访问失败或复制前后身份变化会返回固定 unavailable 错误，不输出底层异常或保留的
goal/命令/日志内容。

报告 schema 1 分别列出 `launch`、`execution`、`delivery`、`outputs`、`terminal` 五阶段，
给出固定的 absent/present/incomplete/invalid/unavailable 观察状态、文件大小和 SHA-256、
协议事件计数、artifact 计数及固定 issue codes。它会显示 prepared、fragment、legacy、
临时和损坏节点，但不把结构存在称为 committed/successful，也永远输出
`recovery_eligibility: not_assessed`。已有锁只以非阻塞共享方式打开；竞争返回 busy，不创建
缺失锁。诊断生成报告的退出码与 materialization 成败无关：observed/attention_required 为
0，busy/unavailable 为 2。报告只提供下一步保留证据并使用正常 resume 的固定提示。

离线验证：snapshot 与诊断聚焦测试 **136 passed in 20.55s**（snapshot 57、报告/CLI 79）；
覆盖 checkpoint/WAL、完整/中断/legacy/碎片、坏节点、敏感信息、锁竞争、缺失 home/workspace、
并发变化、SQLite 与文件边界及源快照保持。Ruff、compileall、Specify prerequisites 和
`git diff --check` 通过；主仓全量复测 **3586 passed in 201.05s**。
没有启动真实模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有
新增算法效果或 WebAgent 持平结论。

剩余边界：诊断是有界观察清单，不是恢复校验器、授权或成功证明；不重建记录、不验证所有
候选/输入/输出字节、不识别存活进程，也不认证外部 writer。数据库或文件系统在检查中持续变化
时可能返回 unavailable，需要操作稳定后重试。临时诊断副本不会成为运行证据，记录仍无 GC。

## Feature 092 结项：执行后的交付恢复

Feature 092 接通了完整 091 执行登记之后的输出验证、发布和终态完成。resume 在完整
090/091 凭据存在且没有下游发布证据时，可以重新独立验证保留的原 attempt，准备 delivery
plan 并继续交付，全程不调用候选 runner。新模块 `materialization_delivery.py` 在
`evolution/materialization/.delivery-publication/` 保存最多 64 KiB 的 canonical plan，
绑定 launch/execution digest、原 result 身份、execution projection、validation 和有序
输出 path/format/fields/required/size/SHA-256。原输出文件、plan 和目录先同步，再用 FULL
SQLite transaction 登记唯一 child task 的 `materialization_delivery_prepared` 事件。
没有增加 artifact row、schema migration 或输出副本；artifact ID 和 owner 仍由 088
在 parent lock 内选择和核验，保留其他 parent task 的合法复用记录。

恢复先重新核验原始 execution、attempt validation 和计划内输出字节，再在 parent lock
内比较 088 journal metadata。不存在 batch 才可调用原 promoter；已 committed 的 batch
直接复用精确 projection，不重新发布。确认 rolled_back 时生成 outputs=[]、
`error="output_publication_rolled_back"` 的明确失败终态。已准备/已提交的 089 终态优先
按原协议恢复，callback 在任何终态写入前只读检查输出状态。089 完整后写最多 4 KiB 的
delivery completion；final/temp 任一存在时，缺失 terminal rows 都不能自动重建。终态
完整而仅缺 delivery completion 可以补完。092 FS/DB 证据也会阻止 091 重建已删执行 batch。

现代执行完整但缺 plan 时，不会先运行可写的旧 088 recovery：没有精确终态授权的下游
残片在 rollback 或新 plan 写入之前被拒绝。已有 exact prepared 089 仍保留历史恢复能力，
先只读核验输出再完成原结果；完整旧 marker 可回放，不强制迁移。没有现代 091 的更早
attempt 继续遵循原 088 恢复规则。独立审查发现并修正了原先先回滚再拒绝的排序缺陷，
补充零写拒绝与旧 089 恢复两个回归，两路终审均无剩余 blocker。

最终离线验证：092 quickstart 七文件 532 项（91.29 秒）；新增三文件共 249 项，包含
controller/FS 94 项、真实双进程 1 项和 Store 154 项，已包含于聚焦与全量；联合 Store
434 项（2.57 秒，与聚焦有重叠）；主仓全量 3450 项（173.17 秒）。Ruff、compileall、
Specify prerequisites 和 `git diff --check` 通过。051/074/076/078/082 共 601 个 tracked
封存文件相对 `6d6ad49` 无 diff，历史验证数字保持。验证记录见
`specs/092-recoverable-materialization-delivery/validation.md`；README 与 architecture 已同步。
本轮没有启动真实模型、provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或
campaign，没有新增算法效果或 WebAgent 持平结论。

剩余边界：raw execution bytes、未完整准备的 execution/delivery plan，以及 088/089
缺少精确 preparation 的残片仍需诊断；缺失 candidate、execution 或 attempt output bytes
不能重建。088 完整 journal 发布前的中断边界及整批 rollback 不重试保持。协议只保留
090 的至多一次 runner 授权进入，不保证 exactly-once 或成功交付，不识别/终止未知存活
进程。各 attempt 记录有界但尚无 GC；协调删除全部协议证据没有外部真实性保护，088 的
文件系统前缀可见性边界保持。通用 runner 和普通演化候选路径未修改。后续应优先考虑
保留现场的诊断/人工恢复入口及记录保留策略，再决定是否扩展未准备完成的自动恢复授权。

## Feature 091 结项：可恢复的执行证据登记

Feature 091 将最终 materialization 的 execution artifact 和事件改为可恢复的原子登记。
新模块 `materialization_execution.py` 只在 final runner 正常返回之后，核对返回的
`CandidateExecution`、原始 canonical `execution.json` 和 090 launch intent。先同步原始
执行文件及目录链，再写 `evolution/materialization/.execution-publication/journal.json`
并同步，之后以 FULL SQLite transaction 保存确定 ID 的 prepared 凭据。4 KiB journal
绑定 parent/child/唯一 task、launch intent digest、execution path/digest/size/inode 和
确定 artifact ID，不复制或重写原始 execution bytes。

单个 FULL transaction 登记 execution artifact、artifact_recorded、原有形状的
`evolved_candidate_executed` 和 `materialization_execution_committed`，之后保存 durable
completion receipt。commit 抛异常必须重新查询完整快照；无法确认时保留现场，不能转成
伪造的失败终态。prepare 和 commit 都在同一 SQLite snapshot 验证 090 intent、owner、
整个 batch 和 artifact budget。既有 partial、duplicate 或 owner/content 漂移均拒绝。

resume 复用 090 全生命周期锁，在 090 execution gate 和 088/089 任何恢复写入之前检查
091。只有精确 FS journal + DB prepared、execution batch 完全不存在、没有 completion
final/temp、也没有任何对应下游 output/terminal 凭据时，才允许续完登记。完整 committed
batch 可以补缺失的 completion；保留完成凭据或下游凭据时删除执行记录不能触发重建。
现代 journal 丢失而 reserved DB 证据还在时禁止降级；旧完整结果没有 091 证据时保持只读。
终态验证也会检查现代执行登记完整性。没有 089 terminal preparation 时，即使 execution
登记已恢复，controller 仍保留原有缺 marker 错误，不调用 runner、输出发布或新终态生成。

最终离线验证：091 quickstart 七文件 359 项（64.02 秒），执行恢复与双进程两文件 98 项
（26.19 秒），联合 Store 280 项（1.86 秒，含新 execution Store 87 项；聚焦集有重叠），
主仓全量 3201 项（136.98 秒）；Ruff、compileall、Specify prerequisites 和
`git diff --check` 通过。051/074/076/078/082 共 601 个 tracked 封存文件相对 `2e3cd95`
无 diff。两路独立终审发现的 child output artifact 被删、仅剩事件时的下游识别遗漏已修复，
补充 absent/prepared 两个回归并重新完成全量验证，最终无剩余 blocker。详情见
`specs/091-recoverable-materialization-execution/validation.md`。本轮没有启动真实模型、
provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有新增效果
或 WebAgent 持平结论。

剩余边界：execution.json 已存在但还没有完整 FS/DB prepared 时仍不自动补登记；缺失的
原始 execution bytes 不能重建。execution 登记之后如何继续输出验证、发布并准备终态，
以及 output commit 到 terminal preparation 之间的恢复，仍需下一轮协议。090 的至多一次
runner 授权约束保持，不是 exactly-once 或保证最终完成；不推断/终止崩溃后未知进程。
通用 runner 和普通演化候选路径未修改。journal/completion 不做 GC，协调删除所有完成、
下游与 DB commit 凭据缺少外部真实性承诺；088 的文件系统前缀可见性边界保持。

## Feature 090 结项：候选启动意图持久化

Feature 090 为最终候选交付补齐启动前的 durable intent，防止 controller 在 `Popen` 后、
execution evidence 落盘前中断时，resume 把已可能执行的 attempt 当作空 staging 清理并重跑。
新的 `materialization_launch.py` 在 child 的 `evolution/.materialization.lock` 使用非阻塞
flock，覆盖恢复、检查、清理、运行和 088/089 发布的完整 lifecycle。请求的 parent/child、
contract 和 candidate 身份在拿锁前后各验证一次；并发调用立即返回
`materialization_already_running`，之后可复用已完成结果。

通过输入准备、Python eligibility 和 runner 构造后，先同步候选副本及目录链，再以临时
文件 fsync → no-clobber link → 目录链 fsync 写出
`evolution/materialization/launch-intent.json`，最后以 FULL-synchronous SQLite transaction
登记确定 ID 的 child `materialization_launch_intended` 事件。最多 8 KiB 的 canonical intent
绑定 parent/child/task、contract、strategy、candidate ID/path/digest、attempt、runner
fingerprint 和实际 timeout；事件绑定固定路径及 exact digest/size，不新增 artifact row
或迁移。只有本次首次准备且确认完整的调用才能进入 runner 一次，Store 幂等登记或读取
既有 intent 都不授予重跑权限。

intent 临时/最终文件、SQLite 残片或内容漂移均保留现场并阻止 cleanup/relaunch。有 intent
时，在任何 088/089 恢复写入前必须验证真实 execution 文件及独立 artifact/event。完整证据
仍允许 088 验证和安全 rollback，以及 089 prepared terminal 续发；不能补造 execution
记录或从输出推断终态。runner 进入后抛普通异常、没有返回执行结果时固定报状态不确定，
不会伪装成执行前失败。真正的输入/语言检查失败、无 intent 的安全 staging、source-only
contract 和历史完整缓存保持原有语义；缓存请求改变 timeout 也不要求重跑。

最终离线验证：090 quickstart 七文件 252 项（34.47 秒），新增持久化故障文件 10 项
（1.84 秒，与 quickstart 有重叠），主仓全量 3016 项（102.26 秒）；Ruff、compileall、
Specify prerequisites 和 `git diff --check` 通过。051/074/076/078/082 共 601 个 tracked
封存文件相对 `a28411a` 无 diff，Store 与 FS/controller 两路独立终审无剩余 blocker。
详情见 `specs/090-durable-materialization-launch/validation.md`。新增测试全部使用离线 fixture，
没有启动真实模型、provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或 campaign，
没有新的算法效果或 WebAgent 持平结论。

剩余边界：intent 只证明授权，不证明 `Popen` 发生。intent 后、runner 前中断可能零执行，
同样禁止自动重试；保证是协议内至多一次 runner 授权进入，不是 exactly-once 或自动完成。
controller 崩溃后候选进程可能仍存活，resume 不猜测 PID 或终止未知进程。执行文件与
execution artifact/event 的恢复登记，以及 output commit 到 terminal preparation 之间
的恢复仍未实现；后续应优先制定 execution evidence reconciliation 协议。通用
`CommandCandidateRunner` 和普通演化候选路径未修改。intent 和旧 publication 记录暂不 GC，
协调删除全部 FS/DB intent 没有外部真实性保护，仍可能与从未授权的旧记录无法区分。

## Feature 089 结项：可恢复的最终结果登记

Feature 089 处理了“最终 result marker 已写出，但 artifact/event 尚未完整登记”的恢复缺口。
新的 `materialization_publication.py` 在 child 的
`evolution/materialization/.terminal-publication/` 保存完整 canonical `result.blob`、journal
及 completion receipt；`result.json` 和父 `evolved_candidate_materialized` 事件仍保持原有
schema 1 形状。controller 在 Feature 088 输出恢复之后、旧 marker/执行检查之前尝试终态恢复，
并复用已有 contract、candidate、execution、output validator；不重新运行候选或发布输出。

顺序是 staging/journal fsync → SQLite prepared receipt → no-clobber marker 与目录 fsync
→ FULL-synchronous SQLite 原子 terminal batch → durable completion receipt。terminal batch
只新增结果 artifact、对应 artifact_recorded、原有父终态事件和 child committed
acknowledgement；execution artifact/event 必须早已完整，恢复不能补造。prepared receipt
绑定 parent/child/task、journal digest、结果 digest/size 和确定 artifact ID。只有存在精确
prepared 凭据、没有任何 completion 凭据、且 terminal batch 完全不存在时，才允许续完登记。

数据库提交异常须重新查询完整快照，不能把待提交的成功结果改写为失败。partial、unknown、
身份/内容漂移、现代 journal 丢失都保留现场并拒绝交付。`completed.json` 及其临时文件都表明
数据库已经提交；它们存在时缺失任何 terminal 证据都不能自动重建。若完整数据库和 marker
仍在，仅 completion receipt 缺失可以补完；已有 completed 文件也会补 fsync，以覆盖 link
后、目录同步前的进程中断。旧结果只有在不存在任何 089 协议证据时，才能按原有严格只读
规则复用。child 级文件锁只串行化终态发布与恢复。

最终离线验证：089 聚焦四文件 251 项（24.97 秒），终态恢复与双进程测试两文件 51 项
（10.53 秒，和聚焦集有重叠），主仓全量 2903 项（89.67 秒）；Ruff、compileall、Specify
prerequisites、`git diff --check` 通过。051/074/076/078/082 共 601 个 tracked 封存文件无 diff，
Store 与 FS/controller 两路独立终审均无剩余 blocker。所有新增测试都是离线 fixture；没有启动真实模型、
provider、WebAgent、真实 OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有新的效果或
WebAgent 持平结论。

剩余边界：本协议从 durable terminal preparation 开始提供恢复能力；此前的中断仍保留现场
并要求诊断，包括 `Popen` 到执行证据落盘、执行证据到 ledger/event 完整登记、以及 Feature
088 output commit 到 terminal preparation 之间的窗口。不能声称严格 exactly-once execution
或恢复所有执行后的崩溃。stage/journal/completion 暂不 GC，没有外部真实性承诺；协调删除
所有 completion 凭据及 terminal 数据库记录，仍可能与未提交的 prepared 状态无法区分。
后续应优先为候选启动及执行证据建立 durable intent/reconciliation 协议。

## Feature 088 结项：可恢复的演化输出批量发布

Feature 088 补齐了上一轮记录的多 output 发布边界。父 workspace 的
`.evolved-output-publications/` 保存同盘 staging、严格有界的不可变 journal 和 rollback
acknowledgement。journal 绑定 parent/child/owner、完整输出 projection、原文件是否存在以及
stage 的 device/inode。父级 flock 串行化发布与恢复；所有输出和完整 ledger 通过预检后，
以 no-clobber hardlink 发布新文件，并在一个 FULL-synchronous SQLite 事务中登记全部新增
output artifacts、artifact events、既有 `evolved_outputs_promoted` 和绑定 journal digest
的 `output_publication_committed`。复用的文件和目录同样先 fsync；旧文件和其他父任务的
合法 artifact ID/owner 保持不变。

提交异常必须回查完整一致的数据库快照，不能直接视为未提交。只有确认未提交时才删除
仍匹配 stage inode 和 digest 的本次新增链接，整批预检在任何删除之前完成；rollback
中断后会补同步已删除路径的目录。commit/rollback 不可确认、journal/输出/ledger 漂移时保留
现场并拒绝 terminal claim。恢复先于 materialization marker replay，验证 journal owner
与数据库 owner；日志目录丢失但 SQLite acknowledgement 仍在时禁止降级。重复发布请求
改变 bytes、owner 或输出集合也会拒绝。路径大小写/Unicode 别名、文件/目录前缀冲突和
跨 volume 输出会在发布前拒绝。

最终离线验证：088 聚焦四文件 196 项（15.30 秒），主仓全量 2787 项（83.45 秒）；Ruff、
compileall、Specify prerequisites、`git diff --check` 均通过。051/074/076/078/082 共 601 个
tracked 封存文件无 diff，独立终审无剩余 blocker。离线测试覆盖第二文件/第二 artifact/事件失败、commit
后异常、不可查询的数据库、真实进程 `os._exit`、rollback 中断、双进程争锁、复用输出、
日志丢失和完整性漂移。没有启动真实模型、provider、WebAgent、OpenEvolve/ShinkaEvolve、
远端服务或 campaign，也没有新增效果提升或 WebAgent 持平结论。

剩余边界：逻辑原子性交付以 SQLite batch 为准，任意文件系统读者在发布期间或 crash 后
恢复前仍可看到部分路径。stage/journal 暂不 GC；完整 journal 发布前的中断保留现场并要求
诊断，同一 evolution identity 的已回滚 batch 不会重新发布。恢复不会执行候选，也不会补造
缺失的 terminal marker。`Popen` 到 durable execution evidence 的窗口，以及 terminal
marker 与 materialization ledger/event 分开持久化的缺口在 088 结项时仍未覆盖；后者已由
上面的 Feature 089 在明确 prepared 凭据之后实现恢复。flock 只协调本模块的
发布者，不对其他同用户进程提供文件真实性保证。后续开发应分别为这两个窗口制定恢复协议，
不要将本轮离线工程验证解释为新的算法效果测量。

## Feature 084/085 结项：verified seed 与 population-first

Feature 084 与 Feature 085 已于 2026-09-14 完成实现、离线验证和独立终审。所有新演化任务
只接受 `population` 或显式 `openevolve`；默认 contract、`solve --evolve`、standalone
`evolve` 与 benchmark 均使用 `population`。历史 `loop` contract/archive/result 仍可只读，
但新建、controller resume、CLI answer 以及 `LoopStrategy.run()`/`resume()` 都会在首次 mutation
前固定拒绝并给出 `loop_strategy_retired`。显式 OpenEvolve 只提供候选 material，必须经过 Feature 084
的本地 exact evaluator、verified seed receipt 和 canonical commit，外部分数不进入 Lunar
score、rank 或最终交付权威。

恢复与 writer 边界已补齐：root/stage/backup 会在任何创建、替换、清理或 callback 前只读
预检；state/config/archive/result/outcomes 严格拒绝重复 JSON key、非有限数值、历史 loop、
unknown、mixed 与 cross-strategy operational evidence。materialization 将 state/archive/result、
artifact ledger、candidate digest、execution artifact/event、parent output、promotion event 与
terminal marker 绑定；marker 缺失而 `execution.json` 或 `.execution.json.tmp` 存在、异常或不可
检查时保留现场并拒绝重跑。

最终离线验证：Feature 084 聚焦 507 项（10.91 秒），Feature 085 聚焦 583 项（27.55 秒），
主仓全量 2673 项（78.26 秒）；Ruff、compileall、两个 Specify prerequisites、
`git diff --check` 均通过。051/074/076/078/082 共 601 个 tracked 封存文件相对当前 HEAD 无
diff，独立终审无 P0/P1/P2 blocker。本次没有启动模型、provider、WebAgent、真实
OpenEvolve/ShinkaEvolve、远端服务、company evaluator 或 campaign，也没有产生新的效果提升、
有效解率提升或 WebAgent 持平结论。

084/085 结项时仍保留两个系统边界。Feature 036 的多 output 发布没有跨文件系统与 SQLite ledger 的整体事务；
第二个 output artifact 失败时可能残留前面已发布的文件和 ledger row。完整修复需要 Store 批量
事务、同盘 staging、commit/rollback journal 与 crash recovery；此项已由上面的 Feature 088
实现可恢复批量发布。另一个边界是 subprocess
`Popen` 成功到 `.execution.json.tmp` durable publication 之间的硬崩溃窗口；在没有 durable
pre-launch protocol 或独立事务的情况下，现有证据不能判定候选是否已经执行，因此不能声称
严格 exactly-once。

## 最新续作：Feature 087 ordinary candidate integrity

Feature 087 已为普通 `population` 候选补齐离线、可恢复的完整性边界。每个新候选都以
canonical `CandidateReceipt` 绑定 source、lineage、规范化 evaluator report、contract、
evaluator、dependency、environment、runner 和 generator identity；可选 `execution.json`
也以精确 digest 绑定。archive line 保存 compact integrity projection，state 保存统一
authority 和 archive digest；credential-shaped `evaluator_kind` 会在 config/context、
authority 和 receipt 层全部拒绝。source 与 execution evidence 的 no-follow descriptor 从评测前
持有到完整 publication 结束，并在 receipt、record、目录 fsync、archive append/fsync
边界重复核对；evaluator 返回的嵌套 report 会立即深复制，避免回调返回后再被修改。

普通候选 publication 现在按 source → receipt → record → archive 的顺序落盘，archive 与
outcome append 在写前检查总大小不会超过 reader 上限。append 或 fsync 失败会回滚到旧长度，
再次 fsync，并在截断及目录 fsync 后确认当前路径仍指向 held inode 和旧 size；若 publication
与 rollback 都无法确认，则固定抛出
`ordinary_candidate_archive_publication_unknown`，保留 orphan source/record/receipt 供诊断，
但不让其进入 canonical archive、resume population 或 controller index。evaluator/worker
失败仍不生成 receipt。`CommandCandidateRunner` 在正常 leader 退出后也会清理同 PGID
descendants。

resume 在 generator/evaluator 调用前校验 config、authority、source、execution、receipt、
record、archive、outcome、state、lineage、island 与 active population；新版 integrity state
缺少 config 也会 fail closed；非法 parent 结构即使 receipt/record/archive 的完整绑定被同步
重算仍会拒绝。现代 ordinary-integrity state 的 `active_ids`、`best_candidate_id`、`rng_seed`、
`last_migration_iteration` 和 `stagnation` 会从已验证 archive 按 seed/iteration 顺序重放
rank/trim/migrate/best/stagnation 规则后重建；替换、迁移/停滞水位漂移、bool/float 数值类型绕过
及与 projection 冲突的 status 均以 `population state projection mismatch` fail closed。marker
仍可见时，需要 outcome binding 的现代 checkpoint 不能通过同时删除整组字段和 journal 降级为
legacy；不完整 pending batch 和空 seed population 保留原有更具体错误的优先级。ordinary
marker 一旦由 pending state 建立，后续 state 会单调保留；seeded 首批 offspring 全失败且没有
ordinary record
时也不能丢 marker，带 modern marker + `seed_admission` 的 state 必须保留 outcome binding，
因此 marker 仍可见时删除 outcome 整组会 fail closed。若协调删除 marker 三字段、完整
outcome/failed binding 和 journal，seed-only archive 与真实 Feature 084 pre-ordinary checkpoint
不可区分，不在 Feature 087 的无外部承诺边界内。旧普通 archive 可以只读，
但不能作为 active population 静默恢复。完整 pending batch 可以在不重放 callback 的情况下
finalize；不完整 batch fail closed。controller 只索引 canonical sidecars；失败路径只允许
state digest 已绑定且完整验证的普通 archive 前缀，并跳过未提交 seed sidecar，避免伪 seed
证据进入 ledger；generic indexing hook 永不直接发布 population seed，seed evidence 仍只走
独立 commit gate。同一 `(path, kind)` 的既有 ledger rows 若 digest 或 size 冲突也会 fail
closed，不会用首条记录掩盖冲突。

最终离线验证：087 聚焦三文件 212 项（3.69 秒），主仓全量 2408 项（65.02 秒）；Ruff、
compileall、Specify prerequisites、`git diff --check` 均通过，074/076/078/082 共 595 个 Git
封存文件无 diff，两路独立终审无剩余实现或行为 blocker。没有启动模型、
provider、WebAgent、OpenEvolve/ShinkaEvolve、远端服务或 campaign，也没有新的效果、有效解率
或 WebAgent 持平声明。保留的系统边界包括：同用户进程
仍可能在最后一次 publication 校验后再次改写路径；resume 会拒绝没有同步重算或替换全部
hash-bound artifacts 的 drift，但 receipt 没有外部签名/HMAC，不能对能一致改写
source/receipt/record/archive/state 的同用户进程提供真实性保证。父路径组件核验与完整路径
`open()` 之间仍有系统级 TOCTOU；controller 异常前缀搜索是低频 O(n²) 路径；首次 state 尚未
写入时恢复已发布初始候选会固定报
`ordinary_candidate_integrity_state_missing`。纯 seed、尚未开始 ordinary transaction 的
checkpoint 仍属于 Feature 084；state 对任意字段没有独立外部承诺，空初始化
`candidate_failed` 的 running/failed status 与 error 若被协调改写，不能只靠该 state 判别。
projection replay 依赖当前 rank/trim/migrate/family 规则，后续算法变化必须升级 integrity
schema 或显式迁移。

## 最新续作：Feature 086 remote material handoff

Feature 086 已在当前工作树完成离线实现并完成独立审查：新增
`src/lunar_evolution/remote_material_handoff.py`，把已由调用方取得并可选 reconcile 的
`RemoteExperimentState(status="completed")` 转换为通用 `ProducerResultEnvelope`，再通过
对象级 `admit_producer_envelope` 进入既有本地 exact evaluator、receipt 和 verified-seed
admission。只有 pinned producer ID/fingerprint、非空 `candidate_source` references、有效
bounded budget 和本地 regular-file/大小/UTF-8/path-confinement/SHA-256 校验全部通过才会调用
evaluator；remote completion、timestamp、attempt、原始 state ID 和 score-like evidence 只保留
摘要。generic-safe experiment ID 可以作为经过校验的 opaque `producer_run_id` 标签保留，但
不能成为 Lunar score 或 candidate identity，也不能直接生成 Lunar rank、archive 或 population
状态。指定的 staging root 必须与 material root 严格 disjoint（包括解析后的文件系统别名），
避免 admission 在同步目录内创建临时文件。该 bridge 不执行 backend、网络、
subprocess、scheduler、模型或 campaign。

新增 remote bridge 生命周期、伪造 DTO、material/staging 路径别名和固定错误边界测试，并补充
Shinka SQLite → exporter → generic producer admission 端到端离线 fixture：高 producer 分数
不会覆盖本地 evaluator 的 0.42 分，lineage 保留，无效候选进入 rejected subset，原始
score/prose 不进入 canonical metadata。当前工作树全量收集并通过 2262 项（基线 2210，另含此前
Shinka/producer 变更及本轮测试）；最终数字以本轮全量 pytest 输出为准。

## 演化生态融合与 OpenEvolve verified producer

本轮已把“Lunar 融合外部演化项目”的边界落实到离线实现。OpenEvolve、未来的
ShinkaEvolve 及远端 reference-engine-v2/WebAgent 控制面只提供候选 material；Lunar 继续持有
algorithm contract、本地 exact evaluator、receipt、canonical archive、resume、rank 和最终
交付权威。OpenEvolve 是 AlphaEvolve 风格的第三方 Apache-2.0 开源实现，不是 Google
DeepMind 官方源码；其他公开项目及分层接法记录在
`docs/evolution-ecosystem-fusion-roadmap-20260911.md`。

新增 `src/lunar_evolution/seed_handoff.py`、`remote_evolution.py` 和 `openevolve_handoff.py`。外部 seed
的 evidence 与 record metadata 在 canonical persistence 前都规范化为固定
`{present, score_present, payload_sha256}` 摘要，不保存原始外部分数、payload 或 prose；
seed identity 绑定 evaluator kind 与 fingerprint，receipt 只接受 report schema `1`。
manifest/source/symlink/大小/编码/控制字符/lone-surrogate/深层 JSON/material-ref 边界均使用
固定错误码。远端 backend 目前只有 bounded、score-free 的
`submit/status/sync/continue_experiment/cancel` DTO/protocol 和 unknown reconciliation，没有
网络 transport，也不会由默认路径实例化。

`PopulationStrategy` 已支持 verified seed 的私有全批裁决、原子 commit、稳定 `seed-*` ID、
generation/iteration 0、确定性 island、receipt/provenance/handoff 校验及 fresh resume
revalidation。offspring 使用五类 durable outcome：`evaluated`、`candidate_failed`、
`evaluator_timeout`、`worker_unknown`、`run_failed`；journal、SHA watermark、archive baseline
和 candidate 双向绑定已落盘，failed-only batch 不推进正式 iteration，完整 outcome 可在
resume 时只 finalize 而不重放。

`OpenEvolveStrategy` 在 mode-0700 系统临时目录运行显式 producer，传入 bounded
contract/budget/config，stdout/stderr 直接丢弃，timeout/cancel 清理进程组。producer 结果先走
同一 seed handoff 和本地 exact evaluator，再原子发布一个 `strategy=openevolve`、
`iteration=1`、`island_id=null` 的稳定 `seed-*` candidate。completed resume 不重跑 producer，
而是从 canonical source/sidecar 重建 admission，重新调用本地 evaluator 并核对
source/receipt/provenance/config。外部 evaluation 无论分数多高都不会进入 Lunar 排名；本地
evaluator 异常、invalid 或 `None` 时为 0 candidate。

controller 的 seed evidence 事件分为 deterministic `seed_admission_adjudicated` 和实际
state/commit-marker 匹配后的 `seed_admission_committed`，并登记 marker、record、receipt 和
offspring outcome artifacts。terminal resume 会先核对 SQLite run 与 canonical state 的
status、strategy、contract、config、seed manifest/marker；缺 state 的失败或取消任务不能被
新 manifest 复活，避免 run/state split-brain。孤立 seed identity 参数在 claim 前拒绝。

新增 `src/lunar_evolution/producer_handoff.py`，提供 transport-free 的
`ProducerResultEnvelope`/`ProducerMaterial` DTO、对象入口 `admit_producer_envelope` 和文件
入口 `admit_producer_result`。OpenEvolve、
ShinkaEvolve 或其他 runner 只需把已落盘的候选 material `{path,size,sha256}`、producer
identity、lineage、预算和 terminal status 导出到同一 envelope；Lunar 以一个全批
`SeedManifest` 绑定 source-only bundle digest，统一做 exact-harness admission 和确定性
island 分配。外部 metrics/evidence 只保留 `{present, score_present, payload_sha256}`，不
进入 Lunar score/rank。多候选 mixed batch、路径/size/digest/symlink/FIFO、未知字段/status、
credential/deep-evidence、空 terminal envelope 和 local invalid evaluation 均有离线测试；
没有启动真实 ShinkaEvolve 或任何远端 transport。Shinka 后续只需显式导出 `best/main.*`
及 parent lineage，不能把其 generation/SQLite ID 映射成 Lunar iteration。

当前新增的 `src/lunar_evolution/shinka_handoff.py` 是上述边界的离线 exporter：它只读打开
`programs.sqlite`（缺失时才使用 `evolution_db.sqlite`）的静态、无 WAL/SHM/rollback-journal
sidecar 快照，支持显式有序 `program_ids`（此时省略 `top_k`），并把省略 ID 时的 `top_k`
保留为按 `correct=1` 与 producer score 排序的 convenience 选择，省略 `top_k` 默认取一条。
候选优先来自
`gen_<generation>/main.<ext>`，仅在该文件缺失时回退到 `best/main.<ext>`，且必须与 SQLite
中的 `code` 字节完全一致。导出目标必须是不存在的新 leaf，已有 parent 必须是无任意 symlink
组件的目录；目录提交后的 parent fsync 不确定时会保留已发布树并返回固定 commit-unknown。
导出后直接调用 `admit_producer_result`；`combined_score`、
`correct`、metrics 和 generation/SQLite 元数据都只归一化为外部 evidence，parent IDs 仅作
有界 lineage，不参与 Lunar exact evaluator、score、rank 或最终交付权威。该 exporter 不启动
Shinka、模型、网络、Slurm 或远端服务。

初始化 evaluator 异常现在使用固定 `run_failed`、`evaluator_timeout`、`worker_unknown`
代码；候选 source tree 在评测异常时清理，不再生成带异常正文的 synthetic invalid report，
fresh failure 保持 iteration 0 并在无 active candidate 时 fail closed，terminal resume 不会
重放 generator/evaluator。generator-only 初始失败仍保留旧的 offspring retry 兼容语义。普通
offspring/candidate 尚未拥有与 imported seed 等价的 contract/evaluator/dependency/environment
四类完整 fingerprint/receipt，后续应另立 Feature，避免混改现有 archive schema。

最终离线验证：remote lifecycle/producer/Shinka focused 130 项；主仓全量 2262 项（基线
2210 项加本轮及此前新增测试）；全 `src/lunar_evolution`/`tests` Ruff、compileall、Specify
prerequisites、`git diff --check` 均通过。074/076/078/082 的 595 个 Git 封存文件无 diff。
没有启动模型、真实 OpenEvolve/ShinkaEvolve、WebAgent、provider、公司平台、远端 backend
或 campaign，也没有复写任何历史 measurement。

Feature 084/085 后续已完成实现、任务核验和独立终审，结项状态与最终验证见本文件顶部。
此处所述普通 offspring/candidate 完整 receipt/fingerprint schema 后来由 Feature 087 完成，
remote material bridge 由 Feature 086 完成。仍保留的后续项包括 ShinkaEvolve exporter 的
更广泛真实 runner/benchmark 验证；SkyDiscover/LLM4AD 先接 benchmark/task envelope，
仓库型或 workflow 型候选另开冻结 Feature。离线互操作本身不构成有效解率提升证据。

## 0. 历史续作起点：Feature 084

已找到并离线审查本地 `reference-engine-v2` 仓库（`/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/reference-engine-v2`）及 WebAgent 2.5 分支。审查结论是：reference-engine-v2 的深度演化通过远端实验控制面运行；其 `initial_programs` 必须经过本地 evaluator enrichment/可行性门槛，有效 rollout 才推进正式 iteration。WebAgent 的 `evolve_create/status/sync/continue/cancel` 是服务委托，不是 Lunar staged Build 的本地 runtime。

Feature 084 当时以草案写入 `specs/084-verified-seed-handoff/`，目标是先实现本地 verified seed adapter、身份/lineage/provenance/evaluator receipt 和恢复校验，再定义显式但暂不联网的 reference-engine-v2 backend protocol；该 Feature 后续已按此边界完成。远端分数只能作为 provenance，必须经 Lunar 本地 exact harness 重验后才可进入 population。084 不启动模型、WebAgent、provider、公司评测、真实 reference-engine-v2 服务或新 campaign，也不改变 074/076/078/082 封存文件。审查证据见 `docs/reference-engine-v2-review-20260911.md`、`docs/webagent-v25-branch-audit-20260911.md` 和 `docs/webagent-v25-evolve-service-audit-20260911.md`。

## 1. 历史状态：Feature 083

083已完成可选主机执行保护，`.specify`当时指向083。新增公开Python接口
`host_execution(report_path)`，普通/深度trial CLI增加`--keep-awake-report PATH`；默认
路径和原生结果不变。macOS进程持有PreventUserIdleSystemSleep断言，派发前同步查询
验收并fsync日志及父目录，结束时查询/释放；单次scope覆盖配置/凭据读取及原trial调用。
日志必须新建且位于workspace及case-source之外，拒绝symlink、覆盖、文件篡改和目录
别名绕过；跨PID拒绝，并发单次状态受锁保护。取消/写入/释放失败均保留原业务异常，
FD关闭结果不确定时不盲目重试旧编号。日志分别记acquisition/release/work状态与墙钟、
monotonic原始采样及有符号区间，不保存凭据、候选、评分或异常文本。

新增163项、相关222项（5.21秒）、独立163项（0.24秒）通过。主仓首次全量发现一项
082测试依赖当前38源码文件的陈旧假设，已改为从082固定Git blobs构造临时副本，保留
缺失HTTP helper拒绝检查；该模块54项root/独立均通过。最终主仓1982项全量通过
（60.95秒），全src/tests Ruff、Specify、diff通过。两个本机native scope正常/异常路径
以及普通os._exit(0)局部退出清理验证通过，证据见083 validation；不泛化为真实睡眠或
所有崩溃模式保证。074/076/078/082各68/105/205/217份Git封存文件未变，未跑旧
live-source审计、WebAgent、provider探测、候选补评或新campaign。

目标仍是GLM-5.2分阶段Master→Build完整交付并通过原生harness。083只解决主机策略
和观察证据，不证明有效解率改善，不阻止合盖/手动/低电睡眠，不改变原有timeout或预算。
后续优先单独定义单次请求时限与有限传输恢复，明确共享期限、物理尝试和未知usage
边界，再以新登记实评验证；不重开082/078旧槽。082维持有效0/2，普通流程历史2/2
只作背景，旧失败分数/完整usage/cost仍null。以下082及更早记录保留为历史。

082已完成终局核验与封存：2026-09-11 14:21:02 +0800两槽均已结束，计划验收/进入Build
各2/2，最终有效解0/2；无checkpoint/续跑/subject完成回执/harness，分数及完整失败
usage/cost均null。钣金subject原生5280.137秒，最后请求open_response/transport_timeout
4036.528秒对期限4036.519秒；邮政subject1324.816秒，最后请求14.901秒对3970.214秒，
属于提前报出的传输超时，不能判定具体provider原因。钣金计划交付文件均缺失；邮政
solve.py及三份output存在，缺摘要和回执，未执行候选补评。详情见082 postrun/results.md。

独立终审与root复验251证据SHA通过；38源码/122冻结/36历史项，以及074/076/078
各68/105/205份Git封存文件保持原样。watcher33500已退出0、保存172快照；进程核验
联合190份证据、10PID/5PGID及可见后代/argv/cwd未见残留，保留时点和脱离后代局限。
T082全部关闭；产品仍固定e36b103，未新增产品改动或开启下一批campaign。不要重试
已失败槽、运行候选补分、改旧manifest或运行旧live-source审计。

本轮系统日志含多次Sleep/Wake；Python/外层wait均使用不计系统休眠的mach_absolute_time，
原生计时不等墙钟，13:56旧ETA已撤回，不能把墙钟差值当deadline失效或精确休眠时长。
下一项优先明确评测主机保持唤醒与时间口径，再设计单次请求预算/有限传输恢复及未知
usage约束。WebAgent固定代码比较已独立复核，见docs/webagent-transport-recovery-review-
20260911.md；不直接照搬SSE重放或TTL计数。目标仍是分阶段真实交付与原生有效解，
普通流程历史2/2继续作为已验证背景。以下为082运行中的历史观察，以上述终局为准。

082进展13:59：墙钟已超过此前估算的13:56工作截止，但slot1仍无原生终止记录，不能
按UTC差值判定monotonic预算耗尽。root只读power投影记录了本轮Sleep33/Wake35/
DarkWake32事件；实际Python monotonic/perf_counter实现为mach_absolute_time，SDK
说明其不累计系统休眠（mach_continuous_time才继续前进）。此前13:56墙钟ETA撤回，
没有精确重建休眠时长，也不能据此确定任何模型传输失败根因。证据见082
postrun/observations/20260911T055914717921Z-host-power-time.json。未保存原始电源日志或
改变主机配置/运行条件；继续等slot1原生终止，T082-05/06仍开放。

以下13:01为邮政终止观测；slot1最新状态以上述13:59说明为准。

082进展13:01独立partial：邮政slot2已原生失败终止（subject1324.816秒、退出2），钣金
slot1仍Build。238项证据SHA通过；邮政合法v4为model/model_failed，typed
transport_timeout，phase=open_response，elapsed14901ms、request_timeout3970214ms，
HTTP/status均null。本次不是共享预算耗尽，不能进一步确定底层或provider原因。
无subject/harness回执、无评分、完整失败usage/cost未知，当前1/2终止而非本批最终0/2。
新审计为082 postrun/observations/20260911T050153627104Z-independent-partial-audit.json
及同时间report.md；root核对报告SHA。slot2进程观察05:03:52 UTC未见已知PID/PGID及
可见后代/slot2 cwd残留，slot1仍活跃，不宣称全批清理。13:15 root逐槽诊断再核验6份
终止证据，确认solve.py及3份output文件存在，缺少_agent_summary.md/receipt.json；
仅文件元数据，未执行候选或补评。详情见同目录20260911T051522240740Z-slot2-terminal-
diagnostic.json。冻结条件未改；T082-05/06继续开放，等slot1终局再作全批终审封存。

后续判读与进程核验方案见082 postrun/terminal-decision-guide.md和process-cleanup-review.md；
它们是运行期只读审查说明，不是本批最终结果，不授权新增尝试或改变原生评分边界。
本地固定WebAgent e24恢复策略已作独立只读比较，18份blob身份及关键source/dist逻辑
复核通过，见docs/webagent-transport-recovery-review-20260911.md。可研究有限传输恢复，
但需单独解决共享期限、物理尝试计数、未知usage预留及回执契约；不能把SSE卡顿重放
当作本次非流式错误的现成修复，不能照搬会受300秒TTL影响的重试计数。没有执行
WebAgent、外部探测、当前槽重试或新产品改动，下一项仍待082终局证据及封存。

以下12:41及12:35为较早观测，当前终止状态以上述13:01记录为准。

082进展12:41：第二份独立只读partial审计通过227项证据SHA，钣金slot1与邮政slot2
均已验收Master计划并进入Build（2/2）。两槽均未续跑、仍started_unresolved，终止0、
subject/harness回执0；分数、完整用量和费用均null，尚无最终有效解结论。新观测为082
postrun/observations/20260911T044152076409Z-independent-partial-audit.json及同时间report.md；
root核对保存JSON/报告SHA与阶段计数。12:35旧观测保持原字节。不改冻结条件、不重试；
继续观察到两槽终止，再作独立终审与进程核验。T082-05/06仍开放。

以下12:35记录是较早的观测，最新阶段状态以上述12:41记录为准。

082进展12:35：独立只读partial审计通过225项证据SHA，邮政slot2的Master计划已验收，
Build进入证据已确认；钣金slot1仍Master。两槽均started_unresolved，终止0、回执0、
harness0，尚无分数或最终有效解结论。观测为082 postrun/observations/
20260911T043548445457Z-independent-partial-audit.json及同时间report.md；root核对保存报告
SHA与计划/Build各1、终止0计数。没有更改运行条件或重试；继续等两槽终止再做最终审计。

082已在登记021b3d0396d3dbe982dd250b5da956bbc7ce469f推送后于2026-09-11 12:28:28 +0800
唯一启动。dispatcher PID/PGID88086；worker88266/88267；subject88272/88273来自可见PPID
链和固定argv角色核验（原生subject-started marker的child PID为null，未伪填）。两槽初始
均master_running、未决，无已验收计划/Build/回执/评分。新HTTP workers已在对应subject
PGID内观测到，身份快照见082 measurement/initial-descendant-processes.json；不保存原始
argv或进程环境。root只读watcher session33500每30秒保存postrun/progress；其marker派生
进程列表不穷尽子进程，最终检查必须纳入独立快照的subject PGID/HTTP helper与cwd关联。
不要再prepare/check-only/dry-run/launch，也不要改已冻src/scripts/tests/inputs/readiness。
当前仅观察082 summarize/postrun audit和元数据；T082-05/06必须等终止、独立终审及封存。

以下是082启动前登记记录，当前运行状态以上述说明为准。

082已完成新测量登记，`.specify`指向082。源固定e36b103，GLM-5.2，钣金/邮政各一新S槽，
Master1200/build2400/reserve120、共享5400秒/200工具/800万tokens，一波并发2、不补位。
232项实现定向、232项独立复核、1819项主仓全量（53.27秒）、73项单独loopback验证通过。
唯一prepare已完成；实际独立preaudit与449项正式guarded dry-run通过，原样报告已镜像。
38源码/122冻结/36历史/23helper与实际shebang解释器、Python/SSL和HTTP helper身份一致。
manifest SHA880761221b0ac2bb11acaffac2dbb8312171ae91adcc6da5ffd06763d2546bdb。
当前尚未launch；登记提交推送后才能唯一启动。T082-01至04完成，05/06待真实终局和封存。
不要再prepare或改已冻src/scripts/tests/inputs/readiness。未作provider探测、WebAgent执行
或公司平台查询；本次测079/080/081合入整体表现，不作纯deadline因果结论，不解释078
旧根因。074/076/078各68/105/205份Git封存文件保持原样。正式失败诊断会绑定原生失败
记录、请求及双副本，只投影v1–v4固定字段，不改变回执/harness/评分或补回完整失败成本。

081已完成有限timeout的绝对HTTP传输截止，`.specify`指向081，T081全部关闭。stdlib
独立exec HTTP worker受父进程统一deadline约束并kill/wait回收；匿名lifeline处理父进程
单PID死亡，worker继承subject PGID。请求/凭据走有界匿名IPC，环境净化；保留代理绕行、
标准TLS行为、None直接urllib及v4/legacy失败分类，不接受迟到成功或失败，不自动重试。
66项HTTP＋7项HTTPS新增测试、464项实现定向、73项独立复核、主仓1687项全量（50.45秒）
通过；Ruff/Specify/diff通过。离线wheel安装到独立venv后，public complete成功加载包内
helper；正常请求成功，0.3秒慢体在0.3041秒被拒绝，全程只有两次loopback请求。
074/076/078各68/105/205份Git封存文件保持原样，没有新增真实评测或provider探测。

当前目标仍是GLM-5.2分阶段Master→Build完成交付并经原生harness验证。下一步需围绕
当前产品准备新的固定测量登记，使用已有WebAgent高分case背景，不重跑WebAgent、
升级模型或重开旧槽。081不能证明078的旧超时根因或有效解改善；078保持有效0/2，
旧分数与完整失败usage/cost未知。纯模型解析仍在父进程，不宣称整个complete硬实时
返回或服务端停止计费；当前验证是macOS证据，Linux尚未实跑。

以下为080及此前历史状态；080当时提出的HTTP截止改造已在081完成。

080已完成最后失败请求的阶段与耗时证据，当时`.specify`指向080，T080全部关闭。产品只改
runtime/subject_diagnostics；v4新增request_observation固定phase、elapsed_ms及实际
传入的request_timeout_ms，保留v1/v2/v3与原异常链/成功解析/请求参数/账本/评分边界。
坏时钟或无效时序安全回退v3，不跨请求或异常节点复用证据。76新测试、391实现定向、
238独立定向和主仓1614全量（39.79秒）通过，独立审查/Ruff/Specify/diff通过。
078/076/074各205/105/68份Git封存文件未变。本轮无新增真实评测、provider探测或重试；
078有效解仍0/2，不能由080补回它的未知时序或完整失败usage/cost。
未来失败可区分请求打开、响应体读取、解析校验与HTTP错误正文处理；它仅是终局诊断，
不覆盖成功请求历史或外层强杀，不能断言具体网络/provider原因。root独立本机fixture
确认timeout=0.15秒的分段200响应在0.3100秒仍成功：urllib限制单次socket等待，不保证
整个HTTP请求deadline。下一项应单独定义并验证绝对请求截止行为；需要真实验证时另作
固定登记，不改旧槽。该问题不能回填为078两次超时的根因。

078已在`a80f9b8`封存推送后，合入079安全模型失败诊断（isolated `b2ed0e9`，merge
`27eb0cc`）。`.specify`现指向079，T078/T079全部关闭。主仓1538项全量测试（40.13秒）、
全src/tests Ruff、Specify/diff通过；独立集成复核确认37源码/74测试/31Specify/3规范
与已审版本一致，078新增两份主仓测试保留，078/076/074各205/105/68份Git封存文件未变。
079仅为自有typed模型失败补充v3固定reason/response_status，保留原失败分类、v1/v2、
成功解析、预算、回执和原生评分权威；无重试、补跑或新增真实调用，不能回填旧失败原因。
本轮没有启动下一批campaign。当前已确认的问题是分阶段Build在交付前模型超时；后续
仍需围绕Build交付完成真实验证，普通流程历史2/2有效不推广为普遍稳定保证。
旧live-source审计因当前源码变化而拒绝属于预期行为，不得改旧manifest以通过检查。

以下为078封存终局与此前执行过程，当前代码状态以上述集成说明为准。

078终局已核验：两槽均Master计划验收且进入Build（2/2），但均约5280秒model/timeout，
没有checkpoint/续跑/subject回执/harness/评分，有效解0/2。subject原生耗时5280.390/
5280.378秒、退出码2，模型/工具事件16/21与14/21；HTTP状态、分数、完整失败usage/cost
和独立精确Master耗时均保持null，不能推断provider故障或提示修改的因果效果。
独立审计与root复验236证据SHA通过，37源码/114冻结文件/30历史锚点未变；watcher7684
退出0，174进度快照已保存，已知5个PID/5个PGID及可见argv/cwd关联无残留。
T078全部关闭，结果和最终证据见078 postrun/results.md。此批须先封存推送，再合入已审
079（b2ed0e9）；079未参加078，不自动追加campaign、重开失败槽或修改旧manifest。
当前目标仍是分阶段Build完成交付并经原生harness验证；普通流程历史2/2只是已验证背景。

以下078运行中记录为历史过程，当前状态以上述终局为准。

078进展22:25：第二份独立partial审计通过212证据SHA，钣金和邮政均已验收Master计划
且进入Build（2/2）；未续跑、尚无subject/harness回执或评分，两槽仍未决。观测为078
postrun/observations/20260910T142536754391Z.json/md。不能把交接计为有效解或因果结论。

078进展22:21：首次独立partial审计通过210证据SHA；邮政有效Master计划已验收并进入
Build，钣金仍Master。两槽仍未决，无subject/harness回执和分数。观测文件为078
postrun/observations/20260910T142109400271Z.json/md，不计有效解，不改变运行条件。

078已在登记`e76a3a341a90703f4ba91a9e14e33ca81a76c488`推送后于2026-09-10 22:17:13 +0800
唯一启动。dispatcher PID/PGID26135；slot1 worker26307、subject26308；slot2 worker26306、
subject26309。初始两槽均master_running，尚无计划/Build/回执/评分；root只读watcher
session7684每30秒写postrun/progress，measurement/保存启动与初始身份快照。
不要再次prepare/check-only/dry-run/launch，不改变已冻source/scripts/tests/input字节。
观察仅用078 campaign.py --summarize、postrun/audit.py；最终必须等两槽终止、独立审计、
核对进程并封存后才合入079。T078-05/06仍未关闭。

078已完成077规划职责的新测量登记准备，当前`.specify`指向
`specs/078-master-planning-role-measurement`。源码固定fba6ab8（不含079），同GLM-5.2、
钣金/邮政各一个新S槽，Master1200/build2400/reserve120秒、checkpoint32轮、共享5400秒/
200工具/800万tokens，一波并发2、至多一次同进程续跑，失败不补位。脚本沿用074固定
执行层，无额外076加载层，23个helper。328项隔离场景、176项root定向与独立审查通过。
已prepare一次，实际独立预审和328项登记dry-run通过；37源码/114冻结/30历史项一致。
manifest SHA605cfd030b3b65e9bc1995157f44acdbbbbe7e55837b6f4a27b7042afb996804，预审/dry-run
已原样镜像。登记提交推送后才能唯一launch；本段记录时尚未启动。T078-01至04完成，
05/06待真实终止与最终审计。不得重做prepare或并入079后继续使用当前登记。

079安全模型失败诊断已在隔离分支codex/model-failure-evidence提交推送b2ed0e9，暂未合入。
仅runtime/subject_diagnostics新增typed v3 fixedreason/response_status，原分类、解析接受、
预算/失败/评分权威不变；88新测试、1447隔离全仓、215独立回归与review通过。它不会参加
078，必须等078封存后合入；不能补写076原因或提供失败完整usage。本地worktree为
`.lunar/worktrees/feature079-model-failure-evidence`。

076已在`9ad2e1c`封存推送，随后合入077（isolated `1df9ae1`，merge `48e2b70`）。
当前`.specify`指向`specs/077-master-planning-role`，T076/T077全部关闭。主仓238项定向
回归、Ruff/Specify/diff通过，隔离全仓1359项通过。077只澄清Master规划职责：先交最小
Build计划，原始任务逐字保留，未知实现细节留给Build；system/tools/预算/评分权威不变。
它尚未参加真实评测，不能将离线通过当作有效解改善。当前目标仍是完成分阶段的有效解
交付；下一步用新预注册验证077，并针对本轮model_failed缺乏细分原因补足安全诊断。
不重开旧槽、不执行旧候选补分。076封存资料保持原字节；旧live-source审计因当前源码
改变而拒绝是预期行为，不得更新旧manifest来适配。

076终局：两槽均已结束，独立审计/root复验225证据SHA通过，37源码/111冻结文件/24历史
锚点未变。钣金1200.259秒model/timeout，无计划和Build；邮政2190.554秒model/model_failed，
首次通过含公开score词汇的Master计划并进入Build，已有solve.py和两份output文件，缺少
摘要/完成回执。两槽均无续跑/harness/评分，有效解0/2，完整失败usage/cost及分数均null。
model_failed没有HTTP状态码，不能断言具体provider原因或超时。watcher98576退出0，已知
9个PID/5个PGID及可见argv/cwd关联进程无残留。结果见076 postrun/results.md和final证据；
T076全部关闭，已先封存后合入077。不得重开失败槽、执行其候选补分或修改旧登记。

077已在隔离worktree完成Master职责澄清，独立审查通过：只改Master user prompt，前置
当前规划职责、原任务逐字保留、未知细节留给Build；不改system/tools/预算/原生评分权威。
14项新增测试、238项定向检查及1359项隔离全仓测试通过。首次全仓缺少8份.gitignored
历史证据，按封存SHA复制补齐后通过，未改测试或历史SHA。已在076封存推送后合入。

以下为076启动及此前历史；当前终局以上述说明为准。

076进展2026-09-10 17:32：独立只读审计确认邮政slot2计划验收且进入Build，计划含
combined_score/score/evaluator，201项证据SHA通过；这是075后首个真实合法阶段交接。
钣金slot1仍master_running；两槽均未决，尚无subject/harness回执、有效解或评分。
最新观测见076 postrun/observations/20260910T093257281442Z.json/md；不提前计有效，
不更改正在运行的预算/源码/输入。仍须等两槽结束后最终审计封存。

Feature076已启动075修复后的真实交接测量，`.specify`指向
`specs/076-public-plan-handoff-measurement`。源码固定`96d5a60`，GLM-5.2，钣金与邮政
各一个新S尝试，Master1200、build2400、reserve120秒，5400秒/200工具/800万tokens，
一波并发2、至多一次合作式续跑、不补位。311项隔离检查与独立审查通过，已prepare，
manifest SHA=`6690a02223aa3ea34bd5f88d9482d75d4a087857d69edd4245ac04479a321b76`。
实际独立预审和311项dry-run通过，37源码/111冻结文件/24历史锚点一致，原样报告已镜像。
登记`2916041947c49800b3dda0f5c463014292291aae`推送后，于2026-09-10 17:25:31 +0800
唯一启动；dispatcher PID/PGID93194，worker93363/93364，初始快照subject93365/93366。
两槽初始均master_running，尚无计划/Build/评分；T076-04关闭，05/06待结束和最终审计。
绝不能再次launch、prepare或执行要求未启动的preaudit/dry-run，不改源码/scripts/tests/
输入字节。观察只用076 campaign.py --summarize、postrun/audit.py；新缺陷在隔离worktree
处理，封存后再集成。075未解决或保证解决钣金规划超时；本轮只作描述性测量，历史不进
分母，不修改074封存SHA或重开旧槽。

最新状态：074已在`68b5e58`封存推送后，合入075公开计划词汇修复：isolated `065661f`，
merge `b5fc3b2`。当前`.specify`指向075，T074/T075全部关闭。主仓src/tests/.specify
与已审隔离版本相同，主仓260项定向回归/Ruff/Specify/diff通过，隔离全仓1316项通过。
修复移除计划文字与普通输出名的语义黑名单，保留结构、路径、身份和原生评分权威，
新增疑似凭据/当前API key输出路径拒绝。没有追加真实尝试；074全部封存文件与原版一致，
旧live-source审计现在会拒绝改变后的源码，这是预期结果，绝不能改历史SHA使其通过。
当前目标仍是让分阶段流程真实完成Master→Build→有效解；下一项需要用新登记验证075
后的实际交接与有效性，并根据证据处理规划超时。普通流程历史两例有效仍是已验证背景，
不把它推广成稳定保证，也不把本次0/2或离线通过改写成修复效果。
独立集成复核确认merge父链为seal68b5e58与reviewed065661f，138个产品/测试/Specify
文件与已审版本一致，074的68个Git封存文件逐字节保持；忽略的Python缓存不属封存证据。

074已于2026-09-10 14:30结束，最终独立审计/root复核205证据SHA通过，已知PID/PGID与
可见argv/cwd关联进程均无残留。钣金subject1200.203秒明确model/timeout；邮政167.136秒
runtime_failed，073解析器本次成功，但计划的公开objective scorer/combined_score被
workflow_checkpoint的score子串规则误拒绝。公开problem.json直接支持这些词汇。两槽
均无已验收计划/Build/续跑/subject或harness回执，分数与完整失败usage/cost均null，
有效解计数0/2。原生诊断与纯校验复现的区别、证据SHA及进程可见性限制见074 postrun/
results.md、final-audit.json、final-report.md、final-process-check.json和逐槽diagnostic。
本批源c28e498、登记27f7124b、manifest b154975d保持，T074全部关闭，不得重开失败槽。
075已在隔离分支修复语义词汇误拒绝并补充凭据路径拒绝，260定向/1316全仓及独立review
通过；先封存推送074，再合入075。075未参与本次测量，尚无修复后的真实有效解结论。

Feature074已启动修复后的新实评，`.specify`指向`074-corrected-staged-measurement`。
被测产品源码固定`c28e498`：钣金、邮政各一个全新S尝试，GLM-5.2，Master上限1200秒，
其余共享5400秒/200工具/800万tokens和一次合作式续跑不变。一波并发2、不补位；历史
069/072仅作背景，不进入分母。本轮分别验证计划验收、进入Build及最终exact-harness
有效解。测量脚本通过固定SHA复用原生执行/receipt与072只读阶段校验，只替换两槽登记
和汇总边界，不修改产品。137项新测试、239项完整隔离场景与独立交叉审查通过，登记已
生成：SHA `b154975d9557b9697fcdc7915de3ab7bb225165c6aaa1c6c0ab3f432a2123229`。
实际独立预审/dry-run已通过并镜像，37源码/99冻结文件/18历史锚点一致。登记提交
`27f7124b28ef9a7318c5f574a9ac97b16a718b9c`推送后于2026-09-10 14:10:22 +0800
唯一启动。dispatcher PID/PGID77166，slot1/2 worker77318/77317，初始快照观察到
subject PID/PGID77319/77320。首份独立partial审计通过181证据SHA，两槽均master_running，
当时还无计划/Build/receipt/评分。T074-04已关闭、05/06待结束与最终审计；绝不能再次
launch，不要修改源码、scripts、tests或输入字节。进度只读使用074 campaign.py --summarize
和postrun/audit.py；不要执行要求未启动状态的check-only/dry-run。启动与初始进程快照
见074 measurement/，独立观测见postrun/observations/；progress/为非权威只读进程/阶段快照。

最新代码状态：072最终证据已在`0a7f90e`封存推送后，合入073修复（merge `228b213`，
isolated `dd4d7f5`）。当前`.specify`指向073，T072与T073全部关闭。主仓src/tests与已审
隔离版本完全一致，167项主仓回归、Ruff、Specify和diff通过，沿用隔离全仓1147通过。
没有追加真实尝试；073尚无新的真实有效解结论。072旧manifest和全部终局资料不变，
其live-source审计会因当前parser源码变化而拒绝，这是预期行为，不能改旧SHA来适配。

2026-09-10 13:28之后最新结论：Feature072四槽均已终止，独立最终审计/进程检查通过。
300秒组0/2：钣金300.229s model/timeout，邮政300.123s runtime/timeout；1200秒组0/2：
邮政240.183s、钣金841.108s均返回了说明文字+json代码块，被整个响应的json.loads拒绝。
全部无已验收计划/Build/续跑/receipt/harness/评分，失败完整usage/cost和精确Master耗时
仍为null。233项证据SHA核对一致，37源码/92冻结文件/13历史锚点未变。已知PID/worker
PGID和可见argv/cwd关联进程均未发现存活；原始subject child IDs未记录，保留可见性限制。
结果见072 postrun/results.md、final-audit.json、final-report.md和final-process-check.json。
T072-05/06关闭；本批不补位、不回填，预注册09a7ea9及旧manifest永久保留。

针对格式问题，Feature073已在隔离worktree `.lunar/worktrees/feature073-master-plan-json-envelope`
分支codex/master-plan-json-envelope提交推送dd4d7f5。仅增加确定性的Master响应外壳解析，
原计划语义、路径、脱敏、预算和原生评分入口保持；93解析器+10集成测试通过，全仓1147
通过，独立review/Ruff/Specify/diff通过。新纯解析器可在内存接受两个已终止响应，但不
执行候选/模型/harness、不改失败结果。修复现已在072证据封存后合入，具体提交见本节开头。
后续目标：用新预注册验证修复后的Master→Build→独立有效解链条；本轮只证明放宽时间
仍会遭遇格式门槛，不能宣称1200秒普遍足够或已改善有效解率。

以下为本轮已完成的启动与准备过程：

Feature072已在预注册提交`09a7ea997df71e31bcdccaeba20f9140aa630b94`推送后，
于2026-09-10 13:09:00 +0800启动一次。后台dispatcher PID/PGID69681，第一波worker
69812/69813，初次进程快照观察到subject69814/69815。当前两槽都在Master，尚无计划、
Build或评分；后两槽等待波次屏障。不要再次launch，冻结源码/脚本/tests/input字节。
manifest SHA=`cbdb07e22b08a8944b9e80bf7f30cbd4057b931bd6128077dcf5da533834f830`，
37源码/92冻结文件/13历史锚点核对通过，实际预审与159项隔离dry-run均已提交并镜像。
当前观测见072 `measurement/launch-observation.json`、`initial-process-observation.json`和
`postrun/observations/20260910T050941Z.json`。后者通过169项证据检查，只是partial观测；
T072-05/06仍待全批完成/最终审计。只读进度使用072 campaign.py --summarize；完整观测
用072 postrun/audit.py，尚未完成时不能加--require-complete。不运行要求未启动的预审/dry-run。

2026-09-10 13:05左右最新工作：用户质疑300秒Master是否足够，已定义Feature072预算对照，
当前`.specify`指向`specs/072-master-budget-measurement`。在修正后源码`5c89e04`上，
同GLM-5.2/公开输入/exact harness新建四个S槽，仅master_seconds为300/1200两组；
顺序钣金300、邮政1200、钣金1200、邮政300，两波并发2。总5400秒/200工具/800万tokens，
build2400/reserve120/32轮合作边界及一次续跑不变，失败不补位，不运行WebAgent。
1037项全仓离线测试通过，独立实现交叉审查完成，正在冻结预注册与最终离线预审；本段
记录时尚未launch。旧069失败只作历史背景，不作修复后控制。精确Master耗时没有权威
独立计时，保持null；分别记录计划验收/Build阶段证据与最终有效解，不能从长预算成功
推出计划必定用了超过300秒。更明确角色/提示设计暂缓，避免与预算实验混在一起。

2026-09-10最新结论：Feature069四次预注册真实评测已全部结束并通过独立最终审计。
普通M有效2/2：钣金validity=1、overall/quality=0.999999；邮政validity=1、overall/quality
=1.0185。分阶段S有效0/2，两次均在300秒Master模型截止点失败，未进入Build或续跑，
失败评分及完整用量保留null。本批证明普通流程能在这两个历史高分case交付有效解；
单次case/arm样本不能证明稳定性或整体优劣，也不能据此评价续跑效果。最终资料见
`specs/069-webagent-normal-workflow/postrun/results.md`、`final-audit.json`和`final-report.md`。
测量源码始终为`80f5af1`；最终证据已在`26fc4a4`封存推送，随后按序合入070（`6def340`）
和071（`caf9a1f`），两项SDD任务均关闭。当前主仓`.specify`指向071；127项主仓定向测试、
Ruff、Specify、diff和独立集成复核通过。src/tests与已审071分支完全一致，沿用其946项
全量通过记录。修复只改tools.py：UTF-8截断保留完整前缀；嵌套argv字符串在执行前返回
可纠正诊断，不自动执行或重试。这些修复未参与刚结束的测量，也未新增模型调用。

当前目标：保持普通流程作为已验证的默认交付路径；先用Feature072预算对照验证Master
更长上限的阶段交接和最终交付，再决定是否调整规划职责/最小交接。无需为得到成功而补跑旧批，
不将普通流程2/2推广成普遍稳定保证，不扩张尚未真实触发的续跑能力。

以下保留历史过程；其中“运行中”“待合入”“保持源码冻结”等描述对应当时状态，
当前状态以本节开头的最终结果及已集成说明为准。

2026-09-09 最新转向：用户要求优先在 WebAgent 稳定高分的 case 上真实测量 Lunar。
Feature 068 已完成两例对照：sheet_metal_nesting、china_post_pickup_optimization；来自
平台 WebAgent/AgentServer（OpenCode）的同一 GLM-5.2 normal 实验，均三次有效且均分最高。
本次明确用 GLM-5.2，每例固定一次，5400 秒 / 200 工具 / 8000000 tokens；两个 case
已复算匹配官方 1.10.6。独立评分环境补齐钣金 evaluator 所需 pandas。钣金套料完成并
由 exact harness 判定 validity=1、overall=0.999999、quality=0.999999；邮政揽收优化
运行至 5400 秒超时，79 model turns/80 tool steps，无 subject receipt/harness/分数。
固定分母 valid=1/2，完成率 0.5；不同 case 不合并均分。结果、审计和 SHA 见 Feature 068。
暂停上下文功能开发，不改变旧 GLM-5.1 campaign，不运行 WebAgent。详见 Feature 068。

Feature 069 已完成可选 staged subject 接入、离线验证与四槽真实评测。钣金M与邮政M均
有效，overall分别0.999999和1.0185；邮政S和钣金S均在master超时失败。原设计目标为
`Master → Build → typed checkpoint → 至多一次同 attempt continuation`，通过同一预算改善交付率。
入口为 `run_subject_adapter(workflow_config=...)` 或 `effect-subject --workflow-config PATH`；
默认 normal workflow 不变。实际 master 模型输出的 JSON 计划经过验证后传给新的 build session，
所有阶段共用累计 tokens/cost/tool steps 和墙钟；receipt 汇总完整阶段用量，EffectTrialRunner
继续负责公共输入、receipt 和 exact harness 的唯一验证与评分边界。

2026-09-10 复核修正了早期独立 seam 的不足：不再丢弃 master 输出，不再把失败后部分 usage 当
完整用量，不允许重新初始化同一 attempt 或重置 deadline。首版只在完整工具轮次持久化后的
合作式边界续跑一次；API 超时/未知 usage、超预算或损坏 checkpoint 均终止，保留已有候选且不
产生 receipt。进程被杀后的恢复尚不支持。控制文件和 transcript 都增加了运行中软链替换检查。最终配置/master 摘要在落 checkpoint
前再次校验，避免模型末轮篡改冻结证据后仍生成 receipt。全仓 828 项测试通过（其中 101 项
staged 定向测试），Ruff、diff check 和独立审查通过。

真实 AgentLoop + 假模型、subject adapter/CLI、现有 trial gate + fixture harness 的离线测试已
覆盖计划传递、累计预算、单次续跑、失败不评分和身份/路径保护。它们不是私有 harness 实评，
不能据此声称有效解比例提高。T069-06 已完成：冻结4个新尝试，每个case各1次 control(M)
和staged(S)，两波并发2，顺序为钣金M/邮政S，然后钣金S/邮政M。两臂均GLM-5.2、
5400秒/200工具/800万tokens；S的master300/build2400/reserve120秒均包含在总时间内，
32个完整工具轮次可触发唯一一次同进程合作式续跑。失败不补位，未评分保留null。

产品源码冻结在`80f5af1`，预注册SHA为
`07781f3390586e49c2c521012e7981350c06215e6c7103a865a97f25597e423e`；
37源码、74执行/测试/输入文件、8个历史证据锚点已固定。独立审计通过，隔离dry-run26项、
全仓874项测试通过，未调用真实模型。协议与证据见`specs/069-webagent-normal-workflow/measurement/`。
汇总纯读取native state/record/report，不调用会恢复备份的读取路径；启动与退出证据须一致。
T069-07进行中：预注册已提交推送`454b521`，本机`.lunar/real-eval-glm-5.2-staged-20260910/`
于2026-09-10 10:19:43 +0800启动；父进程PID48660，第一波slot1/2已进入subject，
邮政S当时为master_running，尚无终止或评分。后台父进程会在第一波两槽均终止后启动
slot3/4；绝不能再次运行`--launch`。当前启动快照见measurement/launch-observation.json，
它不是最终结果。仅用`campaign.py --summarize`读取进度，勿运行要求未启动的check-only/dry-run。
2026-09-10 10:34进度：slot2邮政S已在master阶段300秒模型超时，subject退出2，
15模型响应/19工具调用，尚无master计划/build/resume/receipt/harness/分数；worker退出0仅
代表失败证据正常保存。当时slot1钣金M仍运行，slot3/4尚在波次屏障后，不能把该观测当成全部失败。
诊断/记录/SHA经独立核验，机器与文字观测见measurement/interim-slot-002.json和.md。

本槽还暴露一个确定性工具bug：28,878字节UTF8有效CSV的20,000字节预览截断汉字，误报编码
错误；另两次命令把argv数组嵌套编码成字符串导致可执行名错误。三次错误缺少逐调用耗时，
不能断言它们单独造成master超时。Feature070只在隔离worktree
`.lunar/worktrees/feature070-utf8-prefix`（分支`codex/read-file-utf8-prefix`）修复UTF8边界，
不修改正在测量的主仓。Feature070已在隔离分支提交`42c7f6e`，45项边界/复现测试与
919项全仓测试通过，独立审查、Ruff、Specify和diff检查通过；等本批结束并审计后才合入。
主仓仍为原874项测试与冻结产品源码，本批不补跑。

随后完成Feature071：在`.lunar/worktrees/feature071-command-argv`、分支
`codex/command-argv-diagnostic`（基于070）提交`5a39aa4`，为JSON数组被写成字符串的
command返回静态纠正提示，启动前拒绝，不自动转换/执行/重试；真正argv与普通string保持。
27项新增测试、946项隔离全仓测试与独立审查通过，Ruff/Specify/diff通过。测试证明模型
自行纠正后的两次工具调用只启动一次fake进程，原始参数与累计用量不重置。070/071均已
推送各自分支，等待本轮终止并审计后按顺序合入；主仓`.specify`仍指向069。

再次只读核对WebAgent固定`e24df25`发现：它的300秒是`agent_wait`等待窗口，超时后worker
继续运行；Lunar的300秒master硬截止与最终JSON计划门槛是自己的实验设计，不能称为
WebAgent同等配置。实际v2.5 master协调多角色、写PLAN.md并派发solver，权限并非只读。
详见`docs/webagent-master-comparison-20260910.md`。历史高分记录未绑定这一代码commit，
因此只把角色/交付契约作为本批结束后的假设，不中途调整规划策略。

2026-09-10 10:49进度：钣金M仍在运行，已有分析脚本但无receipt/评分；邮政S的失败仍为
已审计记录，后两例继续等待第一波结束。源码37、冻结输入/测试74、历史锚点8项SHA均未变。

2026-09-10 11:05只读观测：slot1仍未决，slot2失败，slot3/4未启动。新增
`specs/069-webagent-normal-workflow/postrun/`审计与中文报告工具，位于冻结dispatcher/tests
之外；29项离线测试、Ruff和独立复核通过，没有模型调用。审计通过原worker逐槽核对实际
private case/extractor/evaluator，验证注册提交、全部冻结文件、源码Git blobs与实际import
路径，再核对唯一attempt、wave顺序和native record/state/report/receipt链。它不启动或
恢复运行、不写campaign文件；`--require-complete`对当前未完成批次明确拒绝最终验收。
历史分数投影逐项对照已冻结原记录，null和大于1的分数原样保留，不加入本批分母。
实际审计及报告已保存为`postrun/observations/20260910T030511Z.json`和`.md`，共155个
证据文件；这只是partial observation。外层时间一致性检查有明示2秒容差，不增加预算；
最终仍须人工确认本批进程退出。T069-07保持未完成，全部终止后用只读工具封存最终审计、
报告并独立复核，再合入070/071；合入后保留原Git/SHA锚点，不改历史manifest适配新源码。

2026-09-10 11:14进度：slot1钣金M已完成exact harness评分，validity=1、overall/quality
=0.999999。Subject 3068.032秒，harness 122.493秒，native run 3190.563秒；实际模型
GLM-5.2，30次模型交互，subject累计input719940/output149337/total869277 tokens，
费用null，以上用量不包含extractor。独立复核subject/harness回执、record/state/report/
outcome链及private harness实际字节通过；37/74/8冻结SHA未变。分数与上一批钣金Lunar
相同，但历史样本不进入本批分母。slot3/4已于11:12:53 +0800在第一波全部结束后自动
启动；本批仍未完成。新partial审计及报告为`postrun/observations/20260910T031419Z.json`
和`.md`，核验185个证据文件；成功槽详细口径见`postrun/slot-001-success.md`。

2026-09-10 11:18进度：slot3钣金S也在master的300秒模型截止点失败，subject退出2、
耗时300.222秒，native300237ms；诊断model/timeout，7个模型响应、11次工具调用，
无subject/harness回执，评分与完整usage为null，resume_used=false。两槽S已全部终止，
本臂有效解0/2；两次均未进入Build或触发续跑，不能由此评价续跑后的求解效果。slot4邮政M
仍未决，全批T069-07仍未完成，不提前计算普通臂的最终完成率。最新partial观测见
`postrun/observations/20260910T031858Z.json`与`.md`，核验196个证据文件。继续等待唯一
剩余的已注册attempt终止，主仓源码/dispatcher/tests保持冻结，070/071暂不合入。
Slot3 transcript经独立只读核验有11个唯一call/result完整配对：read_file4、list_dir3、
run_command4；其中1次run_command把JSON argv嵌套编码成string，触发FileNotFoundError，
与071所覆盖的模式相同。无其他工具错误，不能由此把300秒全部归因于这一次错误。
workflow的初始0计数不代表零消费；checkpoints目录存在但为空，无master计划/build
transcript/receipt/harness。17项证据SHA及分析见`postrun/observations/slot-003-master-failure.json`。

随后补充两份已终止Master的行为分析，见`postrun/master-behavior-analysis.md`和`.json`。
两槽都没有成功返回并持久化的最终响应，模型超时发生在计划JSON解析之前，并非已返回的
计划被校验拒绝；不能据此断言服务端未生成文本。read_file/list_dir没有同路径重复；成功的Python数据探查分别7/3次，
重复加载公开输入进行不同统计，未见写候选或执行solver。参数错误后均有自主纠正，
缺少逐调用耗时，不能单独归因。实际master复用通用系统角色和normal求解任务，加附加
planning说明；代码向每次请求副本提供master剩余时间，但不持久化该提示。不能说模型
不知道截止时间，亦无法区分网络、排队与生成耗时。角色混合仍是待验证解释。下一轮角色/
交接设计仍待本批结束后另行SDD，当前不改预算或启动新尝试。

2026-09-10 12:09:16 +0800，全批终止。Slot4 subject3331.589秒、harness50.244秒、native
3381.900秒，GLM-5.2/provider_observed、59次模型交互，input2010306/output138981/
total2149287 tokens；用量仅subject、不含extractor，费用null。原始harness认可validity=1、
overall/quality=1.0185，大于1原样保留。12:11:50只读`--require-complete`最终审计通过：
passed/complete/final_acceptance均true，212项证据SHA经独立重算一致，37源码、74冻结
文件及8历史锚点全未变。T069-07已关闭；summary SHA为
`712e78755f61ce360a3249abe29624ec9aef291936b7209adba075d18938d450`，final audit SHA为
`3175509fe7d2df7210047ec956ad2f24049189524adfe5670586704ec6cdb2e7`。
独立进程检查及root复核均未发现已知PID/PGID、可见命令参数或cwd关联的本批残留；
详见`postrun/final-process-check.json`，保留child PID未记录等覆盖范围限制。全部四槽
各一次，未重跑WebAgent、未请求新平台数据、未补位、未复制旧候选。文中带时间的运行中
段落是历史观测；本批现在已封存，后续源码变化不得改写manifest来通过旧冻结检查。

本批运行期间产品源码、measurement脚本和tests保持冻结，现已完成按case报告和独立审计。此前结果不回填，不重新运行WebAgent。源码SHA和run/attempt
由预注册worker实际核验；adapter继续核验request/case/profile/limits绑定。模型密钥仅通过
用户已授权的CC Switch读取并传进相应子进程环境，不写入证据。设计见`specs/069-webagent-normal-workflow/`。

Feature 067 已完成使用新预算诊断的两槽真实 GLM 测量。两次均明确触发
200000 token ceiling，subject 耗时 488.371 / 522.781 秒，valid=0/2、scored=0，完整失败
usage 和分数仍为 null。新诊断与独立审计均通过，详见第 25 节；没有补位或回填历史。
Feature 066 已补齐后续预算失败的具体触发项与有界部分用量证据，保持
旧版诊断、成功回执和评分/恢复边界兼容；全仓 726 项测试及独立审查通过，详见第 24 节。
Feature 066 开发轮没有真实模型调用或回填旧记录。此前 Feature 065 已完成 Feature 063/064 新变体
的两槽真实 GLM 实评。两次均在
subject 阶段 runtime/budget_exceeded，无产物、receipt 或评分；valid=0/2，评分和未知
usage 为 null。已独立核验并保留负结果，详见第 23 节。Feature 064 代码为 `6189e50`，
profile 预算提示、命令剩余时间收紧、write_file 原子替换和超时输出修复已通过 667 项测试。
此前 Feature 063 已提交并推送于 `fef89a8`，吸收 WebAgent v2.5/base `e24df25` 的工具参数
契约思路；分支审查见第 21 节和 `docs/webagent-v25-review-20260909.md`。

Feature 058 已提交并推送于 `1ae1893`，新增只读预检及公司平台 baseline 来源记录。
Feature 059 已完成普通求解和 isolated compiler/audit 调用的模型预算、超时边界修复。
Feature 059 已提交于 `503fe0a`。Feature 060 已提交并推送于 `f4b7ba9`，修复结构化输出验收
绕过，统一普通/委派 Solver、候选程序执行和最终产物生成的独立输出校验。
用户再次确认现有实验数据已足够；不运行 WebAgent，不再要求补 WebAgent 数据。
2026-09-08 用户进一步要求推进真实 Lunar 评测：当前优先级已切换为运行首个真实 trial，
不再以新功能开发作为前置条件。下文旧轮次的“本轮不启动真实 trial”仅是历史记录。
已通过用户授权的 CC Switch 接通模型，完成 `supply_chain_inventory` 的首个真实 1 run ×
1 round：有效性 `1.0`、得分 `0.2079`，历史最佳 `0.3496`。独立的 2 runs × 5 rounds
试验已结束，但两个 run 均在首轮 subject 退出、未进入评分；最新证据与待修复项见第 16 节。
用户随后要求改用 WebAgent 已有记录中的较弱求解模型：已选定并实际验证 `glm-5.1`，
后续不再启动 `gpt-5.6-sol` 求解。Feature 061 已补齐此前失败暴露的安全诊断缺口；
GLM 独立单 case 实评已执行，在 900 秒预算内未产出候选、没有进入评分，安全诊断为
model timeout。当前模型选择、结果与证据边界见第 17–18 节。

以下保留 2026-09-06 续接时的历史提交记录：

```text
4a61044 test: cover nested candidate manifest traversal
46d576d docs: update handoff for failure statistics
32561c9 feat: report deep evolution failure statistics
558f510 docs: record continuation findings
f633dde fix: allow candidate interpreter startup before timeout
b3df70e docs: add lunar agent handoff
edaa4a6 feat: add controlled deep evolution feedback
```

此前收口已修复普通/深度效果试验的记录权威和深度 round receipt 完整性，更新 Feature
048/051/052 文档，并补齐官方 FM-Eval AgentServer normal-mode comparator。变更已按指定身份
提交并推送；完成时保持 `main == origin/main`。

## 2. 产品目标和设计边界

Lunar Evolution 的目标是一个独立、本地、可被其他 Agent 调用的算法问题 Agent：

- 用户可以直接运行；Codex、Hermes、OpenClaw 等也可以把它当作 CLI 子进程调用。
- 不要求用户机器预装 Hermes、OpenCode、Codex 或某个全局配置目录。
- 内部自带 Agent runtime 骨架，同时允许显式接入 OpenAI-compatible endpoint、subprocess
  或 mock runtime。
- 解决算法/组合优化问题，输出结构化文件、数据和可验证报告，而不只是对话文本。
- 借鉴 WebAgent 的 clarify/build/evolve、fresh loop、评估、恢复和证据边界，但不复制其
  服务化、队列、计费、远端 workspace 架构。
- 同时保留三类搜索入口：`loop`、`population`、显式 `OpenEvolve` adapter。
- 所有评分必须由独立 evaluator/harness 给出，Agent 不能自报分数。

当前总体架构可看：

- [架构文档](/Users/liminghan/Documents/lunar_agent/docs/architecture.md)
- [项目 README](/Users/liminghan/Documents/lunar_agent/README.md)

核心链路：

```text
CLI / parent Agent
        ↓
LocalController + DomainRouter + MasterPolicy
        ↓
AlgorithmProblemContract / plan / output contract
        ↓
Runtime Adapter
  mock | subprocess | OpenAI-compatible | AgentLoopRuntime
        ↓
loop | population | openevolve adapter
        ↓
candidate archive → execution/evaluator → verified artifacts/data/report
```

深度效果评测另有独立边界：

```text
fresh subject round
        ↓
exact private extractor/evaluator harness
        ↓
bounded RoundFeedback
        ↓
fresh subject round + shared candidate workspace
```

## 3. 已完成工作

### Feature 001–011：独立 Agent 基础和恢复

已完成 standalone local Agent、CLI/TUI 基础、Hermes-inspired bounded tool loop、模型 runtime
adapter、交互恢复、transcript、Master Policy、plan contract、DAG 调度、artifact acceptance、
evidence-guided recovery、隔离 worker pool、retry feedback。

对应目录：

```text
specs/001-standalone-local-agent
specs/002-webagent-effect-parity
specs/003-hermes-inspired-local-agent
specs/004-interactive-session-recovery
specs/005-session-transcript-recovery
specs/006-master-policy-plan-contract
specs/007-domain-routing-solver-evaluator
specs/008-artifact-acceptance-contracts
specs/009-evidence-guided-recovery
specs/010-local-isolated-worker-pool
specs/011-verified-retry-feedback
```

### Feature 012–026：算法任务、Agent adapter 和演化运行时

已完成算法问题契约、loop/population/OpenEvolve 入口、Agent delegation、Agent-backed
generator/evaluator、portfolio、evaluator ensemble、runtime-backed evolution、执行验证、
对话式算法任务、role DAG、evolution agent loop、结果 handoff、provenance、verified feedback。

### Feature 027–036：benchmark、运行 profile 和结构化输出

已完成 evolution benchmark、unified benchmark、runtime profile benchmark、Agent evidence、
structured algorithm outputs、input staging、role evidence、runtime artifact envelope、
conversational evolution handoff、evolved output materialization。

### Feature 037–047：执行闭环、评估器安全和搜索增强

已完成 execution-grounded evolution/refinement、objective harness handoff、frozen evaluator
bundle、private data profile、adversarial evaluator audit、solver scoring contract、verified
experiment memory、adaptive search orchestration、contract-driven algorithm playbooks、
quality-diversity population。

对应重点目录：

```text
specs/037-execution-grounded-evolution
specs/039-execution-grounded-refinement
specs/040-frozen-evaluator-bundle
specs/041-private-data-profiling
specs/042-adversarial-evaluator-audit
specs/043-solver-scoring-contract
specs/044-verified-experiment-memory
specs/045-adaptive-search-orchestration
specs/046-contract-driven-algorithm-playbooks
specs/047-quality-diversity-population
```

### Feature 048–050：reference-benchmark 效果层

- Feature 048：导入历史结果，比较单 case 的 Lunar best 与通用 baseline historical best，
  只允许独立 harness 提供分数。
- Feature 049：加入可执行的 subject/harness adapter，支持 public projection、private
  extractor/evaluator、receipt 和环境隔离边界。
- Feature 050：生成 content-addressed effect kit，冻结 suite、case digest、public file ledger、
  evaluator/extractor digest，避免 benchmark 内容漂移。

本地已准备好经过官方 publication 身份校验的 `supply_chain_inventory` kit 和历史 comparator：

```text
.lunar/lunar_evolution-kit-real-001/
```

该目录被 `.gitignore` 忽略。baseline 来自 FM-Eval 只读 Query 的实验
`fmexp-1fae1f63-b54a-400b-9ca4-118a4c6387f9`，三次历史分数为
`0.3496 / 0.3496 / 0.2415`，historical best 为 `0.3496`。选中 case 的三条结果都满足
FM-Eval conclusion eligibility；整个来源实验本身仍保留 `failed/partially_valid` 状态，不能把
case slice 的可比较性扩张成整个实验成功。该实验的 adapter 是 `agentserver` 且
`deep_evolution=false`，所以它是官方 FM-Eval AgentServer normal-mode comparator，不能称为
WebAgent historical baseline；严格的 WebAgent 比较仍需同 publication/case 的
`adapter=webagent` export。

### Feature 051：五轮深度演化效果试验

目录：

```text
specs/051-deep-evolution-effect-trial/
src/lunar_evolution/deep_effect_trial.py
tests/test_deep_effect_trial.py
```

命令：

```bash
lunar-evolution effect-deep-trial ...
```

行为：默认 5 个 outer rounds；每轮启动新的无记忆 subject 进程；共享 attempt workspace；
每轮执行 exact private harness；每轮原子保存 logical-run record；`--resume` 校验 suite、
baseline、case、receipt、harness 和配置身份；报告 round curve、best、P50/P90、gain 和
milestone。

本次进一步加固了效果试验的恢复和评分权威：

- built-in deep subject receipt 用 `request_sha256` 绑定 canonical request；旧的已完成
  receipt/record 仍可读取，但未登记 subject round 没有绑定摘要就不能复用；
- 恢复时逐项复核 subject 的模型、evidence、turns、usage，以及 harness 的 extraction、
  validity、overall、quality、detail metrics 和已记录的 harness request 摘要；
- 已有 request-bound subject receipt 且 harness 目录安全时，未写入 durable round 的 harness
  目录会删除并由 private harness 重评分；harness 早于 subject receipt 或路径不安全会 fail
  closed。未在 state 中登记摘要的普通/深度 `record.json` 也不能自动成为权威记录；
- 只有 `incomplete_rounds` 可继续原 attempt；进程或边界失败在下一次恢复时创建新 attempt，
  并保留旧目录作为证据；
- control、state、record、attempt 路径检查完整祖先 symlink 链；subject 不能预建同级
  harness workspace；
- `record.previous.json` journal 覆盖 `record.json` 已替换而 `state.json` 尚未登记新摘要的
  中断窗口，只允许回滚到与 state 摘要精确匹配的上一版本。

### Feature 052：受控 RoundFeedback 契约

目录：

```text
specs/052-deep-evolution-feedback-contract/
src/lunar_evolution/deep_feedback.py
tests/test_deep_feedback.py
```

当前反馈不再是裸的 validity/quality/overall 三个分数，而是严格、有限的 projection：

- finite scores、score delta、best round；
- 通用 allowlisted detail metrics；
- 候选文件的相对路径、大小、SHA-256，不传文件内容；
- `invalid_candidate`、`evaluation_failed` 等有限失败类别；
- `repair_validity`、`repair_evaluation`、`change_search_strategy`、`refine_best`、
  `preserve_best_and_probe` 指令；
- 停滞窗口默认 2，可由 `--stagnation-rounds` 配置并冻结进 state identity。

subject receipt 仍然不允许携带分数；分数只能来自 private harness。

### Feature 053：深度试验失败统计

目录：

```text
specs/053-deep-effect-failure-statistics
```

深度试验的每个 case 报告现在包含有界 `failure_statistics` 投影：逻辑 run 错误码、round
反馈类别、已记录/已完成 round 数、超时计数，以及覆盖每个配置 round（含空 round）的固定
明细。该投影只从已验证的持久记录派生，不创建分数，也不改变 private harness 的评分权威。
本次还修复了候选物化的极短超时可靠性：候选解释器启动保留 50ms 下限，避免正常候选在
启动阶段被误判超时；较长预算保持原值。

### Feature 054–055：模型 profile、成本控制与 runtime 集成

目录：

```text
specs/054-model-profiles-cost-control/
specs/055-runtime-model-profile-integration/
src/lunar_evolution/profiles.py
src/lunar_evolution/model_profile.py
```

`ModelProfile` 提供无凭据的模型身份、thinking budget、步数/超时、token 和 micro-USD 成本
上限；`UsageLedger` 对每轮规范化用量做整数计费并在超限前拒绝。`AgentLoopRuntime` 可选接入
profile，使用 profile 的默认 timeout 和 step 上限，在每轮模型响应进入工具动作前校验 token/cost
预算，并在成功结果中报告 profile 名称和可用的 `cost_micros`。没有 profile 的既有调用保持原有
行为；同一 runtime 复用时账本按 invocation 重置。

### Feature 056：CLI runtime profile provenance

目录：

```text
specs/056-cli-runtime-model-profile-provenance/
```

普通 `run`、`solve`、`resume`、`answer` 和 `plan` 的 `--agent-loop` 现在可通过
`--model-profile PATH` 加载有界 JSON `ModelProfile`。profile 必须是非 symlink 的普通 UTF-8
JSON 文件，内容经 `ModelProfile.from_dict` 校验；它可提供默认 model，并把 timeout、步数、
token 和成本限制传入 `HermesSessionRuntime`。没有 `--agent-loop` 时显式 profile 会在运行前
拒绝。detached 子进程只传播 profile 路径，API key 仍通过环境变量传递。solve 的 compiler
fingerprint 包含 profile 的 canonical SHA-256，profile 变更会拒绝 conversational resume。
one-shot runtime、`run_isolated`、effect adapter 和 evolution/benchmark 专用 runtime 参数
仍未接入该 CLI profile，后续应单独设计。

## 4. 本地知识库索引

知识库根目录：

```text
/Users/liminghan/Documents/fm/ku-offline-D15p9TZGvN/
```

正文通常在 `raw/content/<docGuid>.json`，同步日志在 `archive.log`，离线渲染页面在
`docs/<docGuid>/index.html`。

重点文档：

| 文档 | docGuid | 作用 |
|---|---|---|
| 深度演化 PRD | `sqWURJ5cTnE_Z7` | Session/Experiment 生命周期、Top 5、可恢复和用户可见演化图谱 |
| v2.5 深度演化工具集设计 | `7bveCuILHL_BnP` | evolve_create/update/continue/cancel/list/status/sync 七工具和窄控制面 |
| web agent 与 reference-engine-v2 深度演化打通链路梳理 | `y0gVkzefWknA6h` | Console → AgentServer → AgentRunner、异步进度回调 |
| 深度演化阶段 webagent loop vs reference-engine-v2 evolve | `qx9kRYpa6zTQmP` | 同模型 loop 与 population/pipeline 对比、reward hacking 证据 |
| 基于 reference-benchmark-v2 的深度演化阶段模型评测报告 | `YfEcoKAjskbg3P` | 100 轮模型对比、token/时长/成本、格式失败影响 |
| webagent benchmark 测评工程方案（二期） | `xOvDqBtdcHUO16` | fm-eval workload、评测服务化和 benchmark 接入方案 |
| reference-engine-v2 Island & Population Ablation | `jncZRh92LHwYV0` | population/island 消融证据，后续比较 population 时查阅 |

面试/架构辅助文档：

```text
/Users/liminghan/Documents/fm/面经/合集/伐谋agent架构细节面试小抄.md
/Users/liminghan/Documents/fm/面经/合集/项目二-伐谋WebAgent与Workspace.md
/Users/liminghan/Documents/fm/面经/合集/webagent-架构图.svg
```

## 5. 可查阅代码仓库

### Lunar Evolution

```text
本地：/Users/liminghan/Documents/lunar_agent
远端：git@github.com:vchive/Lunar-Evolution.git
分支：main
```

### WebAgent

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/webagent
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/webagent
```

已知分支：

```text
origin/master
origin/reference-engine-v2.5/base
origin/reference-engine-v2.5/evolve_tool
origin/reference-engine-v2.5/master-agent
origin/multi-round
origin/memory_card
origin/lunar_evolution/memory
origin/feature/or-agent
```

重点代码检索词：`evolve`、`loop`、`population`、`workspace`、`agentic loop`、`master agent`、
`analyst`、`executor`、`callback`。

### reference-benchmark

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/reference-benchmark
远端：(original address retained in the archived revision)
当前本地分支：agentco-bench-lite
```

真实 case 示例：

```text
/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/reference-benchmark/03_assignment/supply_chain_inventory
```

该 case 已包含 `instruction.md`、`data/`、`tests/extractor_agent.py`、`tests/evaluator.py`、
`tests/baseline/reference_metrics.json`，但 `reference_metrics.json` 不是 FM-Eval historical
run export，不能直接冒充 WebAgent baseline。

### FM-Eval

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/fm-eval
远端：https://liminghan01@icode.baidu.com/baidu/acg-fm/fm-eval
```

重点：`container_runtime/harness/`、`tests/test_harness_equivalence.py`、
`tests/golden/harness_equiv/`、`tools/release/`、`service/`。

### reference-engine-v2

```text
本地：/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/reference-engine-v2
远端：(original address retained in the archived revision)
```

### 外部参考

```text
OpenEvolve: https://github.com/algorithmicsuperintelligence/openevolve
DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness
Lunar Evolution remote: https://github.com/vchive/Lunar-Evolution
```

OpenEvolve 在 Lunar 里是 adapter，不是必须依赖；Hermes/OpenCode/OpenClaw 同样是可选外部
调用方或显式 runtime，不是 Lunar 的部署前置条件。

## 6. 下一步任务（按优先级）

083的可选主机防空闲休眠保护已完成实现、独立复核与全量验证。下一项单独定义
请求时限及有限传输恢复的SDD，明确物理尝试计数、共享期限和失败usage
未知时的预算边界。需要验证效果时另作GLM-5.2新登记，用已有高分case背景测分阶段
Master→Build→原生harness有效解，不重开082/078旧槽，也不升级模型或重跑WebAgent。
主机保护本身不能证明有效解率提升。当前实现和验证状态以第1节及083 validation为准。

以下P0/P1及来源说明保留为早期历史，不再作为当前待执行任务。

### 历史 P0：Feature 068 的高分案例真实测量（已完成）

用户要求先选 WebAgent 稳定高分 case 验证 Lunar 能力。已只读查询既有平台逐次记录，
在最新选中的 GLM-5.2 normal 实验中按三次均有效/eligible、均分降序选定钣金套料和
邮政揽收优化。两例各运行一次 Lunar，预注册更接近历史资源规模的有界预算，全部结果
保留。详细协议在 `specs/068-high-score-case-measurement/`；不把 AgentServer/OpenCode
部署身份说成已核实的 v2.5 commit，不把 provider/工具/缓存/未知配置差异说成完全公平复现。

### P1（已暂停）：围绕已观测的输入预算压力，审查并设计最小上下文改动

第 19–20 节的历史解释和固定两槽测量已完成，失败就是该配置下的正式结果。当前按
第 21–23 节完成 WebAgent 设计借鉴及其实评：Feature 063/064 的两槽新变体仍未完成，
没有观察到本批完成率改善；不能宣称其中某个改动的因果效果。Feature 066 补齐诊断后，
Feature 067 的独立两槽测量已明确这两个新槽触发 token ceiling（第 25 节）。两次最后
请求仅输入 tokens（25670 / 25488）就超过此前剩余额度（20433 / 1880），这支持优先
离线审查完整消息回放、工具读取/输出和上下文体积，再用 SDD 选择最小预算管理改动。
方案需保留公开任务、工具调用/结果配对、候选与评分权威边界，并在原 `glm-5.1` 和预算下
另行预注册固定次数测量；只提前拒绝下一请求不能证明求解效果提升。大文件分页、UTF-8
截断和上下文归档仍是独立候选，不能当作已定位的具体根因。
不追加任何已结束 campaign 的第三次尝试，不为了成功而补位，不修改历史结果，不再运行 WebAgent
或索要数据。历史失败的具体预算触发项仍未知，完整失败消耗仍不能由部分观测推定。

以下保留既有测量所用的冻结来源与执行边界：

官方 publication kit 和 AgentServer normal-mode historical comparator 已就绪，不需要手填
历史分数：

```text
suite:    .lunar/lunar_evolution-kit-real-001/suite.json
projection: .lunar/lunar_evolution-kit-real-001/baseline-agentserver.json
raw:      .lunar/lunar_evolution-kit-real-001/fm-eval-results.json
case:     supply_chain_inventory
baseline model (historical): gpt-5.6-sol
current Lunar solver:        glm-5.1
adapter:  agentserver (deep_evolution=false)
```

关键摘要：

```text
suite SHA-256:    1701995e8f65d9bd2ba73e840b870c9427fce27107e14048cffb34d594a04e46
baseline SHA-256: 17e308b4eca5cdc1ebf334daf9c8956fe8871230c1ddcd38872d56f66466a34b
raw SHA-256:      fa41c138ed3c73a50dd17e9e99704b41a079aef15ab45b1a6bdd65c3897c889d
```

`provenance.json` 保存只读查询、模型观测和来源实验状态；
`publication-identity-verification.json` 保存发布期 FM-Eval SDK commit
`b17023d3f849f3312f8fc79f366b0c18495ee726` 的复算证据。旧 `baseline.json` 没有内嵌 adapter
provenance，保留作历史审计，SHA-256 为
`355a8f1dee33532e720711a9c72988e83f61b4f9af8e4187e51ed3e859579440`。Feature 058 从同一 raw
export 离线生成 `baseline-agentserver.json`，明确保存 `source=company-platform` 和
`adapter=agentserver`；除来源字段外，模型、case 身份和全部 per-run 值与旧 projection 一致。
`baseline-agentserver-provenance.json` 记录本次输入/输出摘要和一致性复核。

当前任务复用冻结 suite/harness，已有 AgentServer baseline 仅保留审计；不补跑 WebAgent 或搜集新的 WebAgent export。
用户最新模型要求优先：已有单 case baseline 的模型是 GPT，与新选 GLM 不同；旧 baseline
保留作历史证据，不传入 GLM 的同模型比较、不改写模型标签。离线 WebAgent 报告足以确认
GLM 求解模型选择，但其中跨 case 聚合值不能伪造成此 case 的 per-run baseline。
effect protocol 的规范机器字段是 `baseline_historical_best`；显式 WebAgent provenance 或
旧 `fm-eval` 无 provenance 的兼容路径还会输出 `webagent_historical_best` 别名。因此当前
示例使用带明确来源的新 projection。只有将来另行要求 WebAgent-specific 比较时，才需要
取得相同 publication、CaseRevision 和 harness 身份下 `adapter=webagent` 的 export。
`effect-baseline` 在默认 `webagent` 模式下会拒绝该 export 的显式 `agentserver` evidence；使用
`--adapter-kind agentserver --baseline-source company-platform` 可离线生成带明确来源的
`baseline-agentserver.json`。冲突的 adapter evidence 仍会被拒绝；缺少 adapter metadata 的
legacy export 继续兼容，但必须另外保留来源证明。

2026-09-08 初次检查时，普通 shell 中没有
`LUNAR_EVOLUTION_MODEL_ENDPOINT`、
`LUNAR_EVOLUTION_API_KEY`、`LUNAR_EVOLUTION_MODEL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、
`ANTHROPIC_MODEL`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 或 `ANTHROPIC_API_KEY`。本轮已另行创建
专用 `.lunar/harness-venv-sdk-0.1.81/` 并安装、验证评分依赖，见第 15 节；无需在项目 venv 中
重复安装。来源实验的 extractor 冻结为 Anthropic API、模型
`glm-5.2`，发布期 FM-Eval harness 锁定 `claude-agent-sdk==0.1.81`；exact extractor 必须使用
包含对应依赖、与冻结身份相符且获授权的运行环境，并显式设置
`ANTHROPIC_MODEL=glm-5.2`。密钥只通过显式环境传递，不能写入仓库、request、receipt 或
report，也不能用 Codex/Claude 的本机登录态冒充 extractor 配置。随后用户明确授权复用
CC Switch 当前 provider 的 API 配置；第 16 节记录了只读接入、显式环境注入及首轮真实结果。
普通 shell 中没有这些变量已不再是启动阻塞。

当前执行步骤：

1. 先读第 17 节，检查 `.lunar/real-eval-glm-5.1-20260908/started.json`、`report.json`
   和 `attempt-001/diagnostics/`，保留已运行 attempts；不要重复启动已消费的实验目录。
2. 当前 solver 只用 `glm-5.1`，extractor 保持 `glm-5.2` 与 SDK `0.1.81`，继续通过
   已授权的 CC Switch 只读加载连接环境，不再运行旧 GPT 脚本。
3. 单 case 实评由本机 `run_single.py` 调用已有 subject/exact harness adapters，预先验证
   冻结输入，成功后检查实际 receipt 与模型身份。只有 private harness 的实际结果可评分。
4. 本次没有 GLM per-run baseline，仅报告独立分数、用时与可观测用量；不计算匹配模型的
   delta/breakthrough，不用跨 case 聚合分代替单 case 历史结果。
5. 这两个冻结 slot 已完成；按第 20 节汇总失败与分母。未来新的 baseline-free 批量测量
   必须单独冻结 manifest 和 SDD，不放宽现有 comparative runner 的模型一致性 guard。

### P1：修复真实 case 适配差距

真实 reference-benchmark 的 extractor 使用 `claude_agent_sdk`，并可能需要 case-specific 的数据
语义。执行真实试验后，若 Lunar 写出的文件不能被 extractor 识别，优先补充：

- case-specific output contract / `OutputSpec`；
- subject prompt 的目标文件提示；
- solution artifact materialization；
- harness detail metrics 的安全 allowlist；
- 不改变 evaluator authority 的 repair loop。

不要把 extractor 改成“帮 Agent 重新求解”，也不要将 private `gt.json`、`information.md`、
`tests/` 内容注入 subject。

### P1：统一 native loop / population / OpenEvolve 的反馈抽象

当前 Feature 052 只覆盖 effect-deep-trial 外层 loop。后续可以把 `RoundFeedback`、native
`ExecutionAwareRefinement`、population 的 best/novelty summary、OpenEvolve result envelope
统一到一个 runtime-neutral `EvolutionFeedback` 接口，但必须先有真实效果数据再抽象。

### P2：模型 profile 和成本控制

从知识库评测看，深度演化模型需要同时看质量、时延、token 和格式失败率。现有进度：

- Feature 054–057 已提供 `ModelProfile`、max steps/timeout、每次调用的 token/cost 预算和
  telemetry；深度试验的每个 fresh subject round 分别应用预算。
- Feature 059 补齐 missing usage、isolated 调用、显式 timeout 和精确预算耗尽时的行为。
- Feature 053 已提供 per-round error code/timeout breakdown；更细 parse failure 分类待需要时扩展。
- 跨所有 outer rounds 的总预算仍是后续工作；`thinking_budget` 当前只保存配置，未映射到
  provider 请求参数，不应声称它已经限制了推理 token。
- 后续支持新版 workload-based export 时，把权威 `experiment.request.workload_ref.kind` 纳入
  baseline adapter guard，并明确它与 `adapter_request.kind` 的优先级；
- best-of-run、best-of-round、suite average 的明确区分。

## 7. 6Astra 模型切换注意事项

截至交接时，仓库代码没有 `6Astra` 的硬编码限制。Lunar 的 OpenAI-compatible runtime 接受
任意非空模型字符串，入口包括：

```bash
--model 6Astra
--agent-runtime-model 6Astra
export LUNAR_EVOLUTION_MODEL=6Astra
```

但模型必须真实存在于所配置的 endpoint/provider，并且 provider 返回的 `model` 字段如果存在
必须满足身份校验。Codex Desktop 项目顶部的“当前模型”属于宿主应用的模型目录/权限选择，
不是 Lunar 仓库代码控制的配置；仓库无法把一个未被宿主暴露或未被 endpoint 支持的模型强行
加入 Codex 的模型切换列表。

后续接手者应区分两件事：

1. **Lunar CLI 调模型**：检查 `LUNAR_EVOLUTION_MODEL_ENDPOINT`、`LUNAR_EVOLUTION_MODEL` 或对应 CLI 参数，确认
   endpoint 的路由文档中确实使用 `6Astra` 这个精确 ID。
2. **Codex 项目本身切换模型**：检查 Codex Desktop 的宿主模型权限、项目策略和当前 host 的
   model catalog；这不由 Lunar 项目文件解决。

此问题在本次交接前尚未完成宿主侧诊断，不能把它误判成 Lunar runtime bug。

## 8. SDD 工作规范

当前 `.specify/feature.json` 指向：

```text
specs/097-benchmark-task-envelope
```

后续新功能必须：

1. 新建 `spec.md`、`plan.md`、`tasks.md`，必要时补 `research.md`、`data-model.md`、
   `quickstart.md`、`contracts/`。
2. 先写失败测试，再实现。
3. 运行：

```bash
uv run pytest -q
uv run ruff check src tests
uv run python -m compileall -q src
uv build
SPECIFY_FEATURE_DIRECTORY=/Users/liminghan/Documents/lunar_agent/specs/<feature> \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

4. 代码提交使用：`vchive <vchive@users.noreply.github.com>`。
5. 按当前范围直接在 `main` 开发并本地提交，不 push；不要擅自切换到工作树或新分支。

## 9. 接手第一步

新 Agent 应先阅读本文件、`README.md`、`docs/architecture.md`、Feature 051/052 的 SDD 文档，
然后执行：

```bash
cd /Users/liminghan/Documents/lunar_agent
git status --short --branch
git log --oneline -5
uv run pytest -q tests/test_effect_trial.py tests/test_deep_feedback.py tests/test_deep_effect_trial.py
```

接着阅读第 17 节并检查 GLM 实验的 started/report/diagnostics；当前 solver 是 `glm-5.1`。
复用冻结 suite 与 exact private harness，已有 GPT baseline 和第 15–16 节的 GPT 脚本仅用于
历史审计。不要重复运行 WebAgent、要求补数据或把 GLM 实评伪装成匹配模型的历史对照。
只有 exact harness 实际完成后才能报告新的独立分数；没有同模型 per-run baseline 时不计算
breakthrough，也不声称 WebAgent parity、suite parity 或 statistical superiority。

## 10. 本次续接记录（2026-09-06）

已通过 FM-Eval 官方只读 Query 取得 machine-readable 历史结果、case catalog 和 publication
身份，完成 `supply_chain_inventory` 的 official-publication kit、AgentServer normal-mode
baseline、provenance 和发布期 SDK 身份复算。历史三次分数为
`0.3496 / 0.3496 / 0.2415`；requested/effective model 都是 `gpt-5.6-sol`，evidence 为
`runtime_observed`，authority 为 `descriptive`，所选 case slice 的 conclusion eligibility 为
`eligible`。来源 adapter 是 `agentserver` 且 `deep_evolution=false`，因此不能把它标成 WebAgent
baseline。严格的 WebAgent comparison 仍缺同身份 `adapter=webagent` export。这些产物位于被
`.gitignore` 忽略的 `.lunar/lunar_evolution-kit-real-001/`，不包含凭据。

本次还修复了普通/深度效果试验对未登记 record 的自动采信、深度 receipt/request 绑定、完整
telemetry/metric 恢复校验、未登记 harness 重评分、失败 attempt 复用边界、subject 越界创建
harness workspace、祖先 symlink、record/state 提交窗口，以及非 WebAgent baseline export 的
误接收。`record.previous.json` 只在摘要与 state 当前授权版本精确匹配时用于恢复；伪造或摘要
不匹配的 journal 会 fail closed。旧的已完成 schema 继续兼容读取，但不能追溯获得新摘要提供
的完整性保证；需要新证据时必须重新评分。

针对性及全仓测试、Ruff、compileall、构建、Feature 048/051 Specify 前置检查和
`git diff --check` 已通过。真实 `2 × 5` 深度试验尚未运行：当前环境缺少显式 subject endpoint/
model 凭据、extractor 的 `glm-5.2` 配置和包含 `anyio`、发布期 `claude_agent_sdk` 的运行环境。
不得把 AgentServer historical baseline 的准备完成误报为 WebAgent baseline 或新的 Lunar
效果结论。

Feature 054/055 已完成并通过全量 pytest、Ruff、compileall、构建、Specify prerequisites 和
`git diff --check`。Feature 056 已完成并通过全量 pytest、Ruff、compileall、构建、Specify
prerequisites 和 `git diff --check`，提交于 `8c00edd`。

## 11. Feature 057（2026-09-07）

Feature 057 已完成实现：`effect-subject` 支持受限 `ModelProfile`，并在不暴露凭据或分数的
前提下输出 profile digest、token usage 和 cost telemetry。普通/深度 effect trial 的请求、
receipt、logical record、report 和 resume identity 均绑定 profile digest；profile 文件被修改、
缺失或与请求模型不一致时 fail closed。无 profile 的旧请求和历史 record 继续兼容读取。

已通过全量 pytest、Ruff、compileall、`uv build`、Feature 057 Specify prerequisites 和
`git diff --check`，提交于 `9e08129`。真实效果试验仍未运行，subject endpoint/model 凭据及
exact extractor 运行环境待配置；不得据此声称 WebAgent parity 或新的效果结论。

## 12. Feature 058（2026-09-08）

Feature 058 已完成实现：新增只读 `effect-preflight`，在不启动 subject、exact harness 或
模型请求的情况下，复核冻结 suite/baseline、public case、命令可执行文件、显式环境变量、
model profile digest，以及 exact harness Python 的 import/distribution 能力。预检报告只保留
身份、哈希、版本和环境变量名称，不写入凭据、私有路径、命令原文、分数或 extractor/evaluator
输出；可选 JSON 文件使用新路径原子写入并拒绝 symlink/覆盖。

Feature 058 的聚焦测试和全量 pytest、Ruff、compileall、`uv build`、Feature 058 Specify
prerequisites 以及 `git diff --check` 均已通过。已从本地 raw export 生成带 `agentserver` 来源的
`baseline-agentserver.json`，历史最佳仍为 `0.3496`，仅用于所选 case 的描述性历史对照。
本轮没有运行 WebAgent 或真实 Lunar trial。未来真实试验需要显式 subject endpoint/model
凭据，以及包含 `anyio` 和发布期 `claude_agent_sdk==0.1.81`、并配置 `ANTHROPIC_MODEL=glm-5.2`
的 exact harness 环境。预检通过也不构成新的 Lunar 效果结论。

## 13. Feature 059（2026-09-08）

Feature 059 统一 `AgentLoopRuntime.run` 和 `run_isolated` 的模型执行约束。有 token/cost
上限时，每个返回的响应必须具备合法 usage；缺失、格式错误或超限会在执行工具、保存成功
响应或生成 subject completed receipt 前失败。用量刚好达到上限的最终文本可成功；同样
用量的工具请求会在副作用发生前停止，不再发起下一次模型调用。

显式 timeout 只能收紧 profile 上限。模型返回和各工具执行前后检查剩余时间，过期响应
不得成为成功结果或触发下一步。账本改为每次调用独立；isolated 仍只有 system/user 输入、
空工具集，不读写 transcript/memory，无 profile 的旧路径保持兼容。

先验证 69 项新增 runtime 回归中 42 项失败、27 项通过，及 4 项 subject adapter 回归全部
失败，再实现修复；实现后 126 项聚焦测试通过。费用依据响应后 usage 计算，不能撤销已计费
请求或保证单次请求绝不超支；运行中的模型/工具仍负责自身取消。跨整个深度试验的总预算
尚未实现，当前预算粒度是一轮 fresh subject invocation。

全仓 532 项 pytest、Ruff、compileall、`uv build`、Feature 059 Specify prerequisites 和
`git diff --check` 均通过；独立审查未发现阻塞问题。

继续使用已有 `baseline-agentserver.json`，不重新运行 WebAgent，也不要求新的平台实验数据。
后续优先按实际需求完善求解产物和演化流程；不在没有真实效果证据时抽象统一反馈接口。

## 14. Feature 060（2026-09-08）

已修复自定义 acceptance 的 `any` 分支可以绕过必需 OutputSpec 的问题。此前，缺少字段的
CSV 可能因为另一条文字条件通过而被提升并交付；现在声明输出始终与 base evaluator、task
acceptance 共同作为必过条件。删除了仅因 output_valid 出现在规则树中就跳过校验的优化。

`evaluate_output_contract` 复用既有格式、字段、大小与安全路径检查，独立处理最多 32 个
OutputSpec，并保留 `output_valid` 叶子诊断用于重试反馈。可选输出只有真正缺省才跳过；
已存在的目录、直接/断开/循环软链接、软链接祖先和非目录祖先都不能被当作缺省。
普通/委派 Solver、ContractCandidateRunner、最终 materialization 均使用该函数。

先确认 controller 17 项新增回归中 9 项失败、8 项通过，候选/最终产物的 4 项路径阻塞回归
全部失败；实现后 93 项聚焦测试通过。测试覆盖缺字段后重试修复、只提升正确产物并校验
交付摘要。旧 materialization 恢复证据无需迁移，但本次不会追溯重新评价已完成的历史 run。

现有通用 acceptance 语法仍保留自身 32-rule 上限；独立输出检查不消耗该表达式的规则额度。
本轮没有改变 CSV/JSON 内容格式规则、promotion 事务或 evaluator 评分权威。继续使用既有
实验数据，没有运行 WebAgent、真实 Lunar trial、平台查询或新的模型调用。

全仓 566 项 pytest、Ruff、compileall、`uv build`、Feature 060 Specify prerequisites 和
`git diff --check` 均通过；独立审查未发现阻塞问题。

## 15. 首次真实评测准备（2026-09-08）

用户要求继续并追问何时真实评测 Lunar。当前优先执行真实试验；无需等待下一项 feature，
也不再寻找 WebAgent 基线。首轮为 `supply_chain_inventory` 的 1 run × 1 round，通过后在
新 workspace 扩展为 2 runs × 5 rounds。沿用既有 company-platform/AgentServer baseline，
历史最佳 `0.3496`，保持单 case 描述性对照的证据边界。

本机准备产物（全部位于忽略目录，无凭据）：

```text
.lunar/real-eval-20260908/README.md
.lunar/real-eval-20260908/run.sh
.lunar/real-eval-20260908/input-checks.json
.lunar/real-eval-20260908/harness-environment.json
.lunar/real-eval-20260908/harness-requirements.lock
.lunar/real-eval-20260908/sdk-wheel-verification.json
.lunar/real-eval-20260908/readiness.json
.lunar/harness-venv-sdk-0.1.81/
```

准备结果：

- suite、baseline、raw export、完整 private case、extractor、evaluator 和公开文件摘要均
  已复核，baseline 的 benchmark/evaluation profile 与 suite 一致。
- 专用 Python `3.13.12` 使用 `venv --copies` 创建，可执行文件非 symlink。已安装
  `claude-agent-sdk==0.1.81`、`anyio==4.15.1`、`mcp==2.2.0`；extractor 所需 SDK 符号实际
  import 和 `pip check` 均通过。发布期仅锁定 SDK，传递依赖没有完整历史锁；本次实际版本
  单独记录，不能声称重建了发布期的完整依赖环境。
- PyPI 直连下载较慢，改用清华镜像获取 macOS arm64 SDK wheel，并核对官方 PyPI SHA-256：
  `e4bc8797cc2bc882031cf6b287a550ae2bb38a3822aa081e9ffc81bb4bed51da`。
- 启动脚本固定 subject `gpt-5.6-sol`、extractor `glm-5.2`，分别显式传递环境。每次先预检，
  通过后才启动 trial；拒绝缺失或空的四个连接变量。Bash 3.2 语法检查及缺省/空值退出检查
  通过，未创建 smoke/deep trial 目录。

本节准备阶段的启动阻塞曾是缺少以下连接配置，现已通过第 16 节的用户授权 CC Switch 接入解决：

```text
LUNAR_EVOLUTION_MODEL_ENDPOINT
LUNAR_EVOLUTION_API_KEY
ANTHROPIC_BASE_URL
ANTHROPIC_AUTH_TOKEN
```

已向用户请求现有环境配置文件路径或本机环境注入，不要求在聊天中发送密钥。不要搜索其他
应用的登录态来代替配置。配置到位后在同一进程环境中执行：

```bash
bash /Users/liminghan/Documents/lunar_agent/.lunar/real-eval-20260908/run.sh smoke
# 首轮真实链路完成并核对后：
bash /Users/liminghan/Documents/lunar_agent/.lunar/real-eval-20260908/run.sh deep
```

`run.sh` 每次都会重新预检；`smoke --resume` 或 `deep --resume` 只恢复各自冻结的配置。
当时 `readiness.json` 是缺配置状态记录，没有模型调用、私有 harness 执行或新的 Lunar 分数；
该文件现已更新为第 16 节的实际运行状态。本次准备仅更新交接文档和本地实验文件，没有修改产品实现，未重跑
已通过的 566 项全仓测试。

## 16. CC Switch 接入与首轮真实结果（2026-09-08）

用户明确授权使用本机 CC Switch，若不能接入再提供 key。已只读接入 CC Switch `3.19.2`
的当前 Codex/Claude provider；没有修改 app 设置或开启代理。辅助脚本
`.lunar/real-eval-20260908/ccswitch.py` 只读 settings 与 SQLite，将 API 配置仅通过进程环境
交给现有 `run.sh`，不输出或复制密钥。CC Switch 当前 Codex 默认模型虽然是 `gpt-6-astra`，
本次实验仍固定为 `gpt-5.6-sol`，未改变历史比较的模型名。

实际连接证据：

- 两组当前接口的模型列表都包含 `gpt-5.6-sol` 和 `glm-5.2`。
- 现有 Lunar Chat Completions runtime 的最小工具往返通过，两次响应均报告
  `gpt-5.6-sol`，探测共 205 tokens；没有执行本地工具。
- SDK `0.1.81` 在隔离临时目录用 `glm-5.2` 完成一轮无工具 query，报告模型相符。
- 完整 `effect-preflight` 通过，见 `ccswitch-preflight.json`。

首轮真实结果位于 `.lunar/real-eval-20260908/smoke/`：

| 项目 | 结果 |
| --- | --- |
| case / 配置 | supply_chain_inventory / 1 run × 1 round |
| 模式 | deep_evolution / loop 的第一轮 |
| overall / quality | 0.2079 |
| validity | 1.0 |
| 历史最佳 / 差值 | 0.3496 / −0.1417 |
| 用时 | 351.715 秒 |
| Lunar 模型交互 | 15 次 |
| Lunar 输入 / 输出 / 总 token | 95,723 / 4,383 / 100,106 |
| 实际响应模型 | gpt-5.6-sol，provider_observed |

首轮真实求解、原始私有 extractor/evaluator 和 receipt 链已完成；没有超越历史最佳。
独立只读审计 16 项证据一致性通过，包括 state 授权 record 摘要、request/receipt、公开输入、
solution manifest、实际 private case 和评分脚本摘要。`smoke --resume` 快速完成且返回报告
与原报告完全相同，没有新建 attempt。

这些用量仅属于 Lunar subject，不包括 extractor；harness receipt 未保存实评 extractor
的返回模型、usage 或完整成本。归一化中间文件和 SDK transcript 仍是临时产物，因此保留
证据支持 receipt 一致性审计，不能仅凭该目录离线重算评分。比较仍仅为本 case 的描述性
对照，baseline 的模型身份仅有 `runtime_observed`，不能升级为两侧 provider 证明。

后续独立 `deep/` workspace 的 2 runs × 5 rounds 已实际执行并结束，运行命令为：

```bash
uv run python .lunar/real-eval-20260908/ccswitch.py deep
```

两次逻辑 run 都在首轮 subject 以 `process_nonzero_exit` 退出，分别耗时 495.668 秒和
75.177 秒；没有 subject receipt/harness workspace，没有完成评分的 round，`lunar_best`
为 null。不能将这两次失败解释为质量分 0 或零模型消耗。首轮 smoke 的独立结果仍有效，
但本次没有得到演化提升证据。

事后纯本地复核发现 run 1 的原始公开文件未变，但新增了 `subject/case/solve.py`，违反
冻结 public projection 的文件集合；run 2 的同项检查通过。新增文件若走后验校验必被拒绝，
但由于检查在 `agent.run()` 返回后，无法仅凭当前文件断言它就是历史退出的直接原因。
失败后再次极小模型请求成功，响应仍为 `gpt-5.6-sol`；这只证明当前连接可用，不能排除
历史瞬时接口故障。独立只读审查确认以上证据边界。

当前诊断缺口已由真实失败暴露：`effect_trial._default_executor` 将 stdout/stderr 送入
DEVNULL，`_invoke` 统一记录 `process_nonzero_exit`，`run_subject_adapter` 又将 runtime
异常压成类型名。下一项 SDD 应补充 score-free、有界、白名单字段的 subject 失败诊断，
保存失败阶段/安全错误类别/退出状态；不要直接保存可能包含凭据的原始 stdout/stderr。
同时明确整个 `case/` 目录不可新增文件，求解代码和产物写在 attempt 根目录或其他允许目录。
先用本地回归区分 public projection 与 runtime/模型失败，再修复并恢复真实试验；保留原始
失败 attempts，不盲目重复消耗调用。此轮没有修改产品实现，仍以 `790c086` 对应实现开展
试验；新增内容仅是本机接入/状态脚本、结果记录和本文档。

汇总说明位于 `.lunar/real-eval-20260908/results.md`。每次新启动/恢复会读取届时 CC Switch
的当前 provider；已经运行的进程环境不受之后全局切换影响。新结果只从实际登记的 round
及最终 report 派生，不改基线、不手填分数、不向 subject 提供私有评分内容。

## 17. WebAgent 记录模型与 GLM 实评（2026-09-08）

用户明确要求“别用这么好的模型，用 WebAgent 已有记录的模型”。选择 `glm-5.1`：离线
报告 `qx9kRYpa6zTQmP` 的 C/E 组明确记载 `webagent loop / glm-5.1`。报告属于 20 case、
12 小时、每组 3 次的聚合实验，不能作为当前单 case 的同模型 baseline。无需再运行 WebAgent、
索取新实验数据或修改已有 GPT baseline。旧 `ccswitch.py smoke/deep` 与 `run.sh` 固定 GPT，
保留供审计，后续不得误用它们启动新的求解。

经用户授权继续只读使用本机 CC Switch。虽然当前 provider 的模型列表没有列出 `glm-5.1`，
实际文本调用与两轮 function-call probe 都成功，响应模型均为 `glm-5.1`；工具探测共 403
tokens。冻结 extractor 仍为 `glm-5.2`，SDK 仍为 `claude-agent-sdk==0.1.81`。

本机忽略目录 `.lunar/real-eval-glm-5.1-20260908/` 保存连接证据、模型选择、profile、冻结
suite、单 case 请求和 `run_single.py`。该脚本只导入旧 CC Switch 脚本的环境加载函数，
不会调用旧 GPT 启动入口。新求解预算为 40 个工具 steps、900 秒、200,000 tokens；无已核实单价，
不编造美元成本或设置虚假的费用估计。Profile canonical SHA-256：
`b2589138335badc4b9ff0fbb27f20f4235b397844e65e122b54b9150d9e587fc`。

现有 `EffectTrialRunner` 要求 requested model 与 baseline model 一致，本次保留该 guard。
独立实评调用现有 `effect-subject` 与 exact `effect-harness`，报告标注
`kind=lunar_single_case_evaluation`、`comparisons_disabled=true`、
`same_model_baseline_available=false`；不是普通/深度 comparative trial 的替代 schema。
subject 成功后才运行原始私有 extractor/evaluator，分数只取自其实际 receipt。

实际 GLM 运行已结束：subject 耗时 900.333 秒、退出码 2，总用时 900.334 秒。
规范诊断为 `stage=model`、`code=timeout`、`http_status=null`，记录到 12 次模型响应事件、
13 次工具结果事件。工具计数包含失败结果的可能性，不能说 13 次工具操作均成功。
没有候选文件、成功 subject receipt 或 harness 目录，0 次评分；质量分未知，不能记为 0。
失败调用用量与返回模型链不完整；连接探测确认同名模型，但不能据此补造本次运行的
provider_observed 成功回执、token 数或费用。

事后复核 request/public projection、sidecar 与采集副本、启动时所有产品 Python 源文件
SHA 均一致，原 GPT baseline 未改动。工具执行已开启，最小环境中的 `python3` 可正常
启动；没有证据断言具体工具错误、provider 断线或某次读取导致了超时。过程不保存原始
模型/工具正文，因此不能重建前 13 次工具操作。结果与本地核验分别在 `results.md`、
`report.json`、`postmortem-checks.json`；`started.json` 拒绝对已启动目录重复执行。

2026-09-09 用户纠正了此前“先取得正常解”的优先级：未产生正常解可能是合理的测量结果，
应结合已有真实评测数据判断。当前目标改为在明确、冻结的预算下测量 Lunar 的完成率、
有效解比例和质量，允许失败成为正式样本；不以取得成功为停止条件。下一批应预先冻结
配置与尝试次数，同时保留全部成功/失败；把进程完成、extractor 完成、evaluator validity、
质量分与用量分别统计。变更 prompt、工具能力或预算时，另立明确的变体和假设，不把“不断
重跑直到成功”的 best result 代替总体表现。只对确定性复现的缺陷做修复；早落盘、预算提示
和更长 timeout 目前都只是待验证假设。本轮已完成两次预先冻结的新 attempt，结果见第 20 节。

## 19. 按真实历史数据解释无解（2026-09-09）

重新复核已有离线报告 `qx9kRYpa6zTQmP`，其中 `webagent loop / glm-5.1` 的 C 组有效解
比例为 57.9%，E 组为 93.0%；表中平均分分别为 0.478、0.854。这个数据证明 WebAgent
也并非始终取得有效解。报告没有提供该指标的超时、运行错误或格式错误细分，不能把有效解
比例的补数称作超时率，也不能推断当前 `supply_chain_inventory` 的失败概率或历史结果。

两组均为 20 case、每组 3 次取平均、12 小时演化，并从 agent build 产物开始；E 组还在
演化期间使用真值评估器。单解“评估”上限为 10800 秒，不等同于 subject 求解预算。
Lunar 本次是从公开输入冷启动的 normal subject，整轮预算为 900 秒，harness 尚未运行。
因此既不能拿 57.9%/93.0% 作为当前单 case 的匹配成功率，也不能通过简单时长比例推定
Lunar 应有表现；尤其不能为了贴近 E 组而把私有评估器内容交给 subject。

本次应记为一个在指定预算内未完成的真实样本，尚无证据表明它是实现缺陷、模型不可用或
框架劣势。无解不写成成功，也不当成质量零分或代码 bug。结构化复核在本机
`.lunar/real-eval-glm-5.1-20260908/historical-context.json`。

## 20. 两槽固定预算测量结果（2026-09-09）

为避免“重跑到成功”，新建了独立 campaign
`.lunar/real-eval-glm-5.1-20260909/`，预先冻结两个 normal slot：同一
`glm-5.1`、profile、公开 case、prompt/adapter、40 tool steps、900 秒和 200,000 token ceiling。
2026-09-08 的单次 exploratory pilot 不进入这两个 slot 的分母。两个 slot 并行执行，使用同一
授权 provider 配置；并发限制已写入 summary，不能把它们解释为完全独立的时序重复。

两个 slot 均在 subject 阶段退出码 2，耗时分别约 310.289 秒和 250.987 秒；Feature 061
诊断均为 `stage=runtime`、`code=budget_exceeded`，各观察到 14 次模型响应事件和 15 次工具
结果事件。这个诊断不说明具体是哪次工具、是否为 provider 故障或是否触发 token ceiling。
两个 slot 都没有 subject receipt、候选文件、harness 目录或评分。

固定分母汇总为：planned 2、terminated 2、process success 0、subject receipt 0、harness
started 0、scored 0、valid 0、failed 2、unresolved 0；`valid_solution_rate=0/2` 是完成率
统计，不是质量分 0。overall/quality 的 `n=0` 且值为 null，usage known 为 0，不能声称
token 消耗或费用为零。结构化汇总为
`.lunar/real-eval-glm-5.1-20260909/summary.json`。

这批结果仍不能证明 Lunar 框架劣势：样本只有两个、subject 是冷启动、历史 WebAgent
实验条件不同，而且本次没有进入 evaluator。后续若继续，应先重新冻结新的变体和样本数；
不能在同一 campaign 中改 prompt、预算、工具后补位，也不能把成功样本挑出来替代失败样本。

## 18. Feature 061 安全失败诊断（2026-09-08）

新增 4096 字节上限的严格 score-free sidecar，绑定执行前 request SHA、normal/deep 模式、
run/round，保留固定阶段/错误码、有限模型/工具计数和可选 HTTP 整数。normal/deep runner
只在 subject 失败时验证并采集到 attempt 的 `diagnostics/`；缺失、伪造、超大、陈旧、
symlink/FIFO/其他不安全文件均不改变原 process 错误。分类或发布自身失败也保留原异常。
没有保存原始 stdout/stderr、异常正文、模型/工具内容或密钥；评分、成功 receipt、记录与
resume schema 保持兼容。两种 subject prompt 明确整个 `case/` 树不可新增、修改或删除。

原始 HEAD 上新增 9 项回归全部先失败；最终全仓 634 项测试、Ruff、compileall、build、
Feature 061 Specify prerequisites、diff 检查通过。独立代码审查无阻塞问题；真实 GLM
超时也成功生成并采集规范诊断。诊断不保存完整失败用量，计数只代表可观测事件。

## 21. WebAgent 分支审查与 Feature 063（2026-09-09）

已 fetch WebAgent，`reference-engine-v2.5/base` 从 `465af9d` 更新至当天 `e24df25`。盘点全部远端分支，
深入检查 base、memory_card `865a270`、layered-compaction `5197081` 及演化/角色分支。
完整结论见 [分支审查文档](docs/webagent-v25-review-20260909.md)。

本轮实际移植为 Feature 063：从 v2.5 的参数说明丢失修复吸收“验证最终模型请求”的原则。
Lunar 不使用 Zod，只在既有 `LocalToolRegistry` schema 上补齐参数描述：工作区路径、
有界文件预览、完整覆盖写入、无 shell argv、实际单命令 timeout、用户问题限制、记忆作用域。
没有改变执行参数、权限、工具开关、评分或恢复 schema。明确 `read_file` 没有分页，且
旧实现截断 UTF-8 字符时可能解码失败；后续可在分页功能中单独复现和修复。

4 项 provider HTTP 边界回归在旧实现全部失败；实现后 40 项聚焦测试和 638 项全仓测试通过，
Ruff、compileall、build、Specify 和 diff 检查通过。测试覆盖 command/memory 四种开关组合
与最终请求中的描述；随后用非默认 timeout/output limit 检查实际配置文案。独立审查未发现
阻断问题。本轮模型响应来自本地 HTTP fixture，没有真实模型调用或新评分。

下一步优先做整轮/单命令预算及增量 checkpoint 的 SDD。普通 registry 默认 30 秒，但 effect
subject 实际是最多 300 秒，不能把 WebAgent skill 的固定 10 秒余量照搬。Lunar 命令结果
当前非流式，也不保证 SIGTERM 宽限。checkpoint 不等于成功 receipt，更不能自动补分。
上下文压缩、稳定 project memory scope 和输出尾部预览有价值，分别按后续需求设计。
WebAgent LC 的原生工具配对和迁移后测试尚不充分；result store 注释的不可覆盖也不是其
普通 writeFile 的文件系统保证。不要照搬这些实现或把分支设计表述成已验证效果。

Feature 063 改变了模型可见上下文，未来实评必须新建并冻结变体、attempt 数和统计口径。
仍使用用户选定的 `glm-5.1` 和现有 exact harness；已记录的失败不补位、不改成零质量分。

## 22. Feature 064 预算感知与候选保存（2026-09-09）

`AgentLoopRuntime.run` 使用 model profile 时，每次模型请求会在复制的 system 消息里生成
当前预算提示：本轮剩余秒数、可用工具调用数、已配置的累计 token/cost 余量，以及当时可用
的单命令上限。未配置的花费上限和未开放的命令分别为 null，不编造缺失 usage 或价格。
提示不追加进历史、transcript 或 memory；isolated 和无 profile 的模型上下文保持原样。

命令执行通过 context-local deadline scope 使用本轮绝对 monotonic 截止时间，每次启动前
重新计算 `min(command_timeout, remaining)`；嵌套只能收紧，异常退出恢复，不改 registry
本身的固定 timeout，保留旧 execute 三参数接口。全局调用仍有原来的前后 profile 检查。
这属于协作式 timeout，不保证进程树取消、SIGTERM 宽限、流式输出或精确墙钟强制中止。

共同的 `write_file` 改为同目录唯一临时文件 → 完整写入/flush/fsync → 原子替换。失败时
保留旧候选且不报告 artifact，尽力清理临时文件；强制杀进程可能留下未登记临时文件。
已有文件保留权限，新文件为 0600；原子替换只改变该路径，其他硬链接仍指向旧内容。
这不是自动多文件 checkpoint，生成的长脚本仍须主动实现自己的增量保存。

同时本地确定性复现并修复 `_run_command` 的超时输出类型 bug：TimeoutExpired 中只有
stdout 或 stderr 为 bytes 时，原本与空字符串拼接产生 TypeError，丢掉已有输出；现在
先分别解码再组合，仍返回失败工具结果。没有扩张 Feature 061 sidecar 保存内容，既有
字符计数截断器、read_file 分页/UTF-8 截断问题本轮没有修改。

失败测试先验证 12 项预算/命令测试中 10 失败、2 通过；首批 8 项原子写测试中 5 失败、
3 通过；2 项普通 profile HTTP 测试在提示缺失时失败，4 项兼容用例通过。另补 2 项部分
写入中断测试及 1 项端到端失败候选测试，共新增 29 项。170 项聚焦测试及全仓 667 项测试
通过，Ruff、compileall、build、Specify 和 diff 检查通过；独立审查无阻断问题。

端到端 fixture 在第二次模型响应累计 token 超限前已保存候选和摘要，验证文件保留、
subject receipt 缺失、harness 未调用、逻辑 run 失败、分数/usage 为 null，诊断仍为
runtime/budget_exceeded。所有模型返回来自本机 HTTP fixture，没有外部模型调用、WebAgent
执行、公司平台查询或新真实评分。2026-09-08/09 的 campaign 和统计分母保持不变。

## 23. Feature 065：预算感知变体真实测量（2026-09-09）

预注册提交 `cb590aa`，产品实现 `6189e50`。新 campaign 为
`.lunar/real-eval-glm-5.1-variant-v2-20260909/`，在两个全新兄弟 attempt 目录各启动一次。
保持之前的 parallel=2、`glm-5.1`、40 tool calls、900 秒与 200,000 token ceiling；suite/
公开文件、private case/harness、SDK 0.1.81 和 extractor `glm-5.2` 均保持相同。runner
改为共享一次 CC Switch 环境快照，启动前核对冻结源码和输入；没有新模型连接探测或补跑。
manifest 不随状态更新，观测写到独立 started/terminated/report 文件。

| 项目 | Slot 1 | Slot 2 |
| --- | --- | --- |
| subject 耗时 | 299.895 秒 | 264.173 秒 |
| subject 退出码 | 2 | 2 |
| 诊断 | runtime/budget_exceeded | runtime/budget_exceeded |
| 模型响应/工具结果事件 | 11 / 12 | 13 / 14 |
| 新增文件 / 成功 receipt | 0 / 无 | 0 / 无 |
| harness / 分数 | 未运行 / null | 未运行 / null |

两次失败均占槽，planned=2、failed=2、valid=0、scored=0、unresolved=0。`valid_solution_rate`
为 0/2，表示完成率统计；overall/quality n=0 且值为 null。失败完整 usage 与费用未知，
不能当作零，也不能将事件次数换算成 token 消耗。本次无需也没有运行 extractor/evaluator。

独立离线审计通过：35 个源码文件、14 个冻结输入、57 个历史证据文件、22 个观测 SHA
链均一致；public projection、private case/harness 和历史 campaign 未变。最终进程检查
未发现本批 runner/subject/harness 残留。原产品 667 项测试已于 Feature 064 通过，本轮
没有改产品代码，执行了本机脚本语法、只读预检、Specify 和 diff 检查。

预注册 manifest SHA：`7bc9df8abb895312a24d707afcd8aa708642472a3d9dd1515ad83c738e0abe7b`。
summary SHA：`7dec7eef0b97bba8547c1ef44535259f648439a4a4884f9991311d22f5db9c9a`。
完整说明、机器汇总与审计分别为该 campaign 的 `results.md`、`summary.json`、`audit.json`；
`summarize.py --check-only` 可离线复核，`run_campaign.py` 已有 started marker，不能重启。

本批没有观察到新工具说明和预算提示改善完成率。这只有两个并发样本，包含多个改动，
且没有进入 evaluator，不能推出整体框架劣势、某项改动无效或已定位 provider 故障。
前批 0/2 与本批 0/2 是两个独立配置的分母，不合并、不挑成功、不重跑到成功为止。

## 24. Feature 066：有界预算失败证据（2026-09-09）

UsageLedger 在 token/cost 超限前生成不可变 accepted/observed 快照，经专用异常传到
AgentLoop 和 subject observer。超限仍拒绝入账，observed 包含触发响应；恰好达到上限
的工具响应已入账但停止执行，两个快照相同。最终文本恰好上限仍允许成功。原先 token
优先顺序、累计费用分方向向上取整、账本提交时机和模型/工具事件计数均保持。

仅类型化预算失败发 sidecar v2：保留原 v1 字段，新增严格 budget 对象，记录 limit、state、
maximum、accepted_usage、observed_usage、trigger_recorded 和固定 usage_completeness=partial。
每个快照含 input/output/total tokens、可选 profile cost_micros 与 rounds。数值上限为
10^15，rounds 为 10^6；无法表示的上限或整份快照为 null，不裁剪成伪精确数字，也不限制
运行时原有整数算术。费用是配置价格的推算，不是 provider 账单；部分响应观测不是完整
失败用量。缺失/无效 usage 不生成预算数值，异常文本与任意附加属性不能冒充类型化证据。

v1 继续严格读取、原样采集，其他失败继续使用 v1。v2 校验精确字段、整数范围、累计关系、
触发状态及上限关系，沿用 4096 bytes、安全排他发布和执行前身份绑定。非权威诊断不改变
process 失败、receipt、harness、score、resume 或 promotion。normal 本机 HTTP 回归验证
候选保留但没有 receipt/harness/评分，完整 usage/cost 仍为 null；deep 验证第二轮失败
仍保留前轮分数，恢复使用新 attempt，旧诊断字节不变。

失败先行：首批诊断测试 10 failed / 36 passed，账本新增测试 5 failed / 11 passed，
集成目标 2 failed / 1 passed。最后共新增 59 项用例，全仓 726 passed（30.35 秒），
Ruff、compileall、build、Feature 066 Specify 和 diff 检查通过；独立审查无阻断问题，
另跑相关 229 项测试通过。规格、方案和验收见 `specs/066-budget-failure-evidence/`。

本轮没有真实模型调用、WebAgent 执行、公司平台查询或历史结果回填。没有新的测量结论，
Feature 065 的 0/2 与 null 分数仍原样保留。旧 campaign 的源码 SHA 审计针对其冻结版本，
当前实现已经变化，不能为通过旧脚本的当前源码检查而改写 manifest 或历史 summary。

## 25. Feature 067：新诊断真实测量与 token 触发证据（2026-09-09）

预注册提交 `9c00b88`，产品源码 `01c541e`；新 campaign 为
`.lunar/real-eval-glm-5.1-budget-diagnostics-20260909/`，两次独立 normal attempt 在全新
兄弟目录各启动一次、共享一次 CC Switch 环境快照并行执行。与 Feature 065 相比仅源码
诊断变化，prompt/工具行为、glm-5.1、40 tool calls、900 秒、200000 tokens、公开输入、
private case/harness、SDK 0.1.81 与 extractor glm-5.2 保持相同；没有连接探测或补位。

| 观测 | Slot 1 | Slot 2 |
| --- | ---: | ---: |
| Subject 耗时（秒）/ 退出码 | 488.371 / 2 | 522.781 / 2 |
| 明确触发项 / 状态 | max_total_tokens / exceeded | max_total_tokens / exceeded |
| 已接受累计 input / output | 159471 / 20096 | 184628 / 13492 |
| 已接受累计 total / rounds | 179567 / 11 | 198120 / 12 |
| 含触发响应累计 input / output | 185141 / 29582 | 210116 / 28596 |
| 含触发响应累计 total / rounds | 214723 / 12 | 238712 / 13 |
| 触发前剩余 tokens | 20433 | 1880 |
| 触发响应 input / output | 25670 / 9486 | 25488 / 15104 |
| 模型响应事件 / 工具结果事件 | 11 / 12 | 12 / 13 |
| 保留普通文件数 | 3 | 1 |
| Subject receipt / harness / 分数 | 无 / 未运行 / null | 无 / 未运行 / null |

两个触发响应都未入账（trigger_recorded=false），快照固定 usage_completeness=partial。
费用与完整失败用量仍未知，事件计数不包含触发失败的模型响应，不通过事件或差值补造
完整账单。Slot 1 保留 analyze.py、analyze2.py、analyze3.py；Slot 2 为 solve.py。
只检查文件名、类型和大小，未读取正文或另行执行，不能宣称已有有效候选或补跑评分。

固定分母 planned=2、started=2、terminated=2、failed=2、valid=0、scored=0、unresolved=0；
有效解比例 0/2。overall/quality n=0 且为 null；usage_known_attempts=0，total_tokens_known
为 null。两个 v2 budget diagnostics 单独计数，不混入完整 usage；历史分母和结果不变。

确定性事后算术显示：两个最后请求的 input tokens 已分别超出剩余额度 5237 / 23608，
尚未计入当轮 output。观测累计输入占比约 86.22% / 88.02%。这支持优先验证上下文输入
开销管理，但没有原始消息/工具正文，不能定位具体读取或证明归档/压缩必然有效；新增
文件和更长运行时间也不能归因于诊断功能。只确认本批 token 触发项，不回填以前失败。

独立预启动/最终审计通过：35 源码（与实现 git blob 相同）、14 输入、95 历史文件、
22 个观测 SHA 链及新版汇总一致；预注册提交先于启动。最终无本批进程残留。本轮产品
源码未改，沿用 Feature 066 的 726 项通过测试，执行了本机脚本语法、无调用 readiness、
预检、部分用量/旧版/未决汇总回归、Specify 与 diff 检查。

Manifest SHA：`41479e3b5d97ea3e2635aea0dc1ae831b18d15bbe746e0f002163826f8553e5f`。
Summary SHA：`7c90a35bf958306d6d030019093f42e2e4f0ea4f0d98bb6252e4af9fb30f05cb`。
Audit SHA：`1d19768cabe8d9e9cca229f19447894842e80f7cc1c69056425ebb68a5ac1674`。
完整结果、汇总、审计和派生算术分别位于本机 campaign 的 `results.md`、`summary.json`、
`audit.json`、`budget-analysis.json`。`summarize.py --check-only` 为只读复核；启动器有
started marker，不能再执行。未来代码变化不应导致改写本批 manifest 或历史源码锚点。
已完成：独立预启动审计通过，两个槽各启动一次。钣金案例约 49.1 分钟完成并评分
0.999999；邮政案例约 90 分钟仍未提交有效回执，最终按预注册超时失败保留。该结果
说明“WebAgent 高分 case”在 Lunar 充足预算下可以做出至少一个有效解，但不保证每个
case 都在一次 bounded run 内完成。旧 GLM-5.1 失败 campaign 未改写、不补跑。

## 26. Feature 140：持久化候选生成回执（2026-09-19）

已完成并待提交推送。原生候选生成在 parser 接受 draft 后发出一个有界
`agent_candidate_generation` 事件，成功事件绑定 candidate ID、source bundle SHA-256 和
`tool_steps_used + tool_steps_remaining == max_tool_steps`；失败或 unknown 事件不携带候选
身份或源码摘要。controller 使用真实 run/task 身份，Store 以 run/task/budget 生成确定性
事件 ID，在同一事务内幂等写入，并拒绝同一预算的不同 payload、跨 run task、schema/stage
篡改和私有诊断字段。

Feature 140 定向测试、Feature 139 离线套件、Ruff、compileall 和 diff 检查已通过。带
`PYTHONPATH=.` 的全量回归收集后有 24 个旧 `measurement123` setup 失败，均因其固定的
历史 product commit 与当前工作树不同（`ValueError: product_changed`）；历史证据没有被修改，
需要从固定 checkout 单独复验。当前没有 provider/evaluator 调用、生成源码执行或 Feature 139
真实登记。完成推送后才能重新评估 Feature 139 的 registration gate。

## 2026-09-23 Feature 153 T153-03/T153-04/T153-05 完成

在 T153-01/T153-02 的 provider-free journal 与 preflight 之上完成 staged publication transaction、exact-match resume 和故障边界回归。新增 `producer_bundle_staging.py`：按系统派生的 `evolution/producer-batches/<journal_id>/` 写入候选 source tree、`record.json`、`receipt.json`、archive/state staged snapshot、manifest 与 durable marker；持有 workspace publication lock，在首个目标移动前把 marker 原子切换为 `unknown`，提交成功后写入 terminal/final journal 并删除 marker。source/record/receipt 的 manifest descriptor 包含 SHA、size，并在可用时绑定 device/inode/mtime/ctime；提交和恢复均复核 no-follow 字节与身份。

混合批次保留已知 `rejected` 项，只按 journal 计划顺序一次发布 `admitted` 子集；全 rejected 不修改 archive/state。未知写入、commit 边界、marker、源字节、receipt、archive/state 或身份变化均 fail-closed。新增 `producer_bundle_recovery.py` 的只读 exact-match resume：复核 plan/authority/preflight/journal/manifest、staged/final candidate tree、terminal after-digest，拒绝 prepared journal、unknown marker/state、重复发布和篡改证据，不重新调用 producer/evaluator。`CandidateArchive` 在 unresolved producer marker 存在时统一拒绝普通读取/写入。

新增 staging、recovery、marker guard focused tests；Feature 153 组合回归 40 项通过，当前全仓回归通过（`pytest -q --disable-warnings`，exit 0），Ruff、compileall、diff check 和旧名称扫描通过。T153-06 launcher/scheduler、external producer/provider campaign 仍按规格延期；本轮没有启动真实 producer、provider 或 WebAgent。

## 2026-09-24 Feature 156 本地进程生命周期继续推进

在 `codex/feature-156-producer-lifecycle` 分支，已实现 provider-free 本地 producer 的一次性
attestation 消耗、进程登记后放行、受限输出采集、结果文件证据和终态回执。此次补上主进程
退出但后代仍留在登记进程组中的清理：runner 在等待管道期间及时清理该组，保留首次
SIGTERM/SIGKILL 清理证据；缺失 owner、复用 PID、非组长等情况仍拒绝发信号。真实后代
fixture 覆盖继承管道、重定向管道和忽略 SIGTERM。

专项 `tests/test_producer_process.py` 31 项通过；进程所有权相关核心组合 51 项通过；
Feature 157 请求证据 8 项通过；全仓离线回归 7345 passed、1 skipped。Ruff、compileall、
`git diff --check` 通过。没有运行真实
provider、evaluator、外部 producer campaign 或 WebAgent；默认调度未接入该 runner。

Feature 156 仍未达到外部接入验收：macOS 上对脚本按已验证 FD 的 `/dev/fd` 执行不可行，
当前 Darwin 已改为私有 `UF_IMMUTABLE` 字节快照并绑定快照摘要；非 Darwin 仍按路径
`Popen`，存在最后核验与内核打开之间的替换窗口。请求级超时尚无
可信逐请求证据，任意 producer 是否遵守 gate 也不能由父进程证明。SDD 已加入执行字节
绑定、trusted bootstrap 和 hostile pre-gate 负例的明确验收项。Feature 157 已定义
cooperative request evidence DTO，但仍未接入 Feature 156；文件声明不能冒充 host-observed
enforcement。上述问题解决前，不把 Feature 156 标为完成或合入默认调度。

Feature 157 提交为 `9f79e4a`，已推送到当前分支。它提供严格绑定 launch/journal/run/
parent/task、intent 和两项预算的有界请求事件 DTO，支持 complete/partial 覆盖与固定摘要；
评估结果明确是 `cooperative_declaration`，不能冒充宿主强制的 request timeout。Feature 156
仍需 controller-owned evidence pipe 或受控 producer SDK 后才能接入该证据。

## 2026-09-24 Feature 158 trusted producer bootstrap contract

新增 `producer_bootstrap.py` 与 provider-free 专项回归。`TrustedBootstrapDescriptor`、
`TrustedBootstrapLaunch`、`BootstrapHandshakeFrame` 和 `TrustedBootstrapEvidence` 使用固定
协议版本、严格 canonical JSON、大小上限、身份字段校验和自摘要；握手帧绑定 launch/intent
摘要，拒绝重复键、字段漂移、摘要篡改及非 target-started 帧携带进程身份。

`TrustedBootstrapSession` 实现 ready → release → target-started → terminal 的确定性状态机，
独立记录 ready 观测，拒绝错误 token、重复 release、提前 target、重复 target、target 身份
漂移、提前 EOF、终止帧乱序和终止后的迟到帧。target 启动后的 terminal 帧保留 passed 证据；
未完成的 ready/release 仍为 unknown，协议失败为 failed 并保留固定 failure code。

Feature 158 专项 16 项、Feature 156/157 组合 55 项通过，Ruff、compileall 和 diff 检查通过。
当前只完成 DTO、解析器和确定性会话模型；尚未启动真正的 Lunar-owned bootstrap 进程，没有
实现 allowlist/跨平台 exact-byte runtime、registration fsync 后 gate release、hostile direct
producer 负例或 Feature 156 生命周期接入。因此 T158-02 至 T158-06 继续待办，不接入默认
调度，也不把 cooperative fixture 当作可信 bootstrap 证明。

## 2026-09-24 Feature 158 provider-free trusted bootstrap fixture

新增 `trusted_bootstrap_runtime.py` 与专项回归。受控 Lunar-owned bootstrap 现在先校验
fixture-only descriptor，再发出 `bootstrap_ready` 并阻塞在私有 gate；父进程在注册回执完成
文件和目录 fsync 后才写入一次 gate token。bootstrap 重新检查 target 字节摘要，启动一次
同一 process group 的 target，并发出 `target_started`/`terminal`。结果保留 registration、
launch/intent 绑定、target group identity、target exit code 和固定状态；deadline、target
替换、目标启动失败、重复 gate、提前 EOF、非法 timeout 以及 hostile direct-producer 均
fail-closed。父进程异常清理使用已登记的私有进程组，不写 producer 文本或可变诊断摘要。

本轮 Feature 158 专项为 **35 passed**（runtime 19、state machine 16），Ruff、compileall 和 diff check 通过。运行时保持
`fixture-only`，没有通过包级默认导出或 scheduler 入口接入，避免 `python -m` 重复导入告警。
运行时成功路径会对已登记的私有进程组执行一次 owner-checked cleanup；deadline 或清理
不确定时保留 unknown 证据并再次尝试清理。T158-04 仍未完成：尚未把 runtime 接入 Feature 156 正式 registration/cleanup/recovery，
一次性 target PGID 观测也不能证明 target 或后代此后从未脱离进程组；
也没有非 Darwin descriptor-bound exact-byte 执行；因此不能接受外部 producer、真实 provider、
WebAgent 或 campaign 验收。

本轮组合回归 `tests/test_producer_bootstrap.py`、`tests/test_trusted_bootstrap_runtime.py`、
`tests/test_producer_process.py`、`tests/test_producer_request_evidence.py` 和
`tests/test_process_ownership.py` 共 **94 passed**。全仓 pytest 在当前未安装项目 CLI 的
解释器环境中有 4 个既有 installed-CLI/effect-adapter 收集后失败，原因是找不到
`Path(sys.executable).parent / "lunar-evolution"`；未涉及本轮代码。

## 2026-09-24 Feature 156/158 deadline-bound cleanup follow-up

本轮继续沿现有 SDD 收紧生命周期预算边界。`cleanup_registered_process()` 新增可选的绝对
monotonic `deadline`，TERM 与 KILL 两阶段共享同一个截止时间；截止后不会继续等待，仍存活
的进程组保留 `cleanup_unverified`/`unknown` 语义。trusted bootstrap fixture 的正常路径和
异常收尾都传入同一 deadline，最终 leader `wait()` 也保持有界。

审查同时修正了两个安全边界：producer process 的 cleanup 现在把全局 deadline 传到底层，
并在允许已退出 leader 时先调用 `poll()`；trusted bootstrap 异常收尾不再绕过 owner-checked
cleanup 直接调用 `process.kill()`。新增回归覆盖绝对 deadline 传递、已退出 leader 观测以及
owner 丢失时不得直接 kill。定向回归共 78 passed；Ruff、compileall 和 `git diff --check`
已通过。Darwin immutable snapshot 测试仍可能产生 pytest 清理警告，这是测试快照的系统
不可变属性，不影响通过结果。

这轮没有扩大声明范围：T156-05/06/09/11/11b/12/13/14 与 T158-04 仍未完成。请求级超时
仍是 producer 协议声明，非 Darwin 仍缺 descriptor-bound execution，trusted bootstrap 仍是
fixture-only，尚未接入 Feature 156 正式 registration/cleanup/recovery 或默认 scheduler。
没有运行 provider、WebAgent、外部 producer 或真实 campaign。当前工作区在提交前包含上述
deadline 实现、测试和文档更新。

## 2026-09-24 Feature 156/158 gate fault follow-up

trusted bootstrap 子进程现在把 target 路径与文件检查推迟到 gate 放行后。新增 fixture
验证放行前移除 target 时仍先收到 `bootstrap_ready`，放行后才报告
`target_start_failed`。Feature 156 新增登记后、放行前子进程退出和 gate 写入失败两项
故障回归；两者都没有成功输出或终态回执，恢复时返回 `recovery_required`。

T156-13 的 capture、signal、cleanup、pre-gate exit 和 broken-gate 故障矩阵已完成。
T156-09 的完整生命周期矩阵、T156-12 的正式 trusted-bootstrap 接入、T158-04 的
registration/cleanup/recovery 身份绑定等仍未完成。Darwin 使用私有 immutable snapshot
绑定执行字节；非 Darwin 仍有按路径执行的替换窗口。请求级预算还缺宿主观测的可信证据，
因此当前实现仍是 provider-free fixture，不接入默认 scheduler 或外部 campaign。

独立复核还发现放行后的 target 身份检查可能因非法文件直接退出；现已改为发出固定
`target_start_failed` 帧，并用多硬链接 target 回归覆盖。Feature 156/157/158 及进程所有权
五套组合测试通过；Ruff、compileall、`git diff --check` 通过。没有运行真实 provider、
WebAgent 或 campaign，也没有重新跑全仓回归。

## 2026-09-25 Feature 158 registration binding DTO

继续 T158-04 的窄范围推进：新增 `TrustedBootstrapRegistration`，将 launch/journal/run/
parent/task、intent、attestation、bootstrap descriptor、target executable identity、
bootstrap PID/PGID 和 gate protocol 绑定到严格 canonical digest。解析器支持 exact-schema、
非 canonical JSON、摘要篡改、进程身份边界和 launch identity drift 拒绝；同时导出到包级
API。该 DTO 只验证登记载荷形状与跨协议绑定，不读取登记文件、不检查 PID/PGID 存在、不执行
清理或恢复，因此 T158-04 的正式 Feature 156 生命周期接入仍未完成。

Feature 158/156/157/ownership 组合回归通过，Ruff、compileall 和 `git diff --check` 通过。
没有运行真实 provider、WebAgent、外部 producer 或 campaign。

## 2026-09-25 Feature 158 registration DTO fixture接线

将 `TrustedBootstrapRegistration` 接入 trusted bootstrap fixture 的实际登记写入点：运行时
现在通过 DTO 构造登记载荷，在 durable registration 发布前按完整 `TrustedBootstrapLaunch`
做 exact binding 校验。登记顺序回归同时解析落盘载荷并确认 PID/PGID 与 launch 绑定一致。

这完成了 T158-04 的 fixture-level registration binding 证据，但尚未接入 Feature 156 的
生产 runner、恢复读取和正式 scheduler，因此仍不扩大外部 producer admission 范围。

## 2026-09-25 Feature 158 registration binding DTO

沿现有 SDD 补上 T158-04 的窄身份边界，但没有声称完成 Feature 156 生命周期接入。`producer_bootstrap.py`
新增 provider-free `TrustedBootstrapRegistration` DTO、构造器和解析/验证函数。DTO 对
`TrustedBootstrapLaunch` 的 launch/journal/run/parent/task、intent、attestation、bootstrap
descriptor、target identity 和 gate protocol 做严格字段绑定，并记录 bootstrap PID/PGID；
`registration_sha256` 覆盖全部非摘要字段，canonical JSON 要求固定字段集合、拒绝重复键、
摘要篡改、非 canonical 文本、无效 PID/PGID 和 launch 字段漂移。

新增 Feature 158 focused registration 回归，覆盖正常 round-trip、launch 身份漂移、PID/PGID
边界、canonical/digest 篡改；`tests/test_producer_bootstrap.py` 共 24 项通过。该 DTO 是纯
校验/数据模型，不读文件、不检查进程、不调用 provider，也未改 scheduler 或现有 producer
runner 行为。T158-04 的正式 registration/cleanup/recovery 接线、T156-09 完整矩阵、非 Darwin
descriptor-bound execution 和宿主请求级证据仍未完成；没有运行真实 provider、WebAgent 或
campaign。本轮改动已随 `cda59a9` 和 `df95820` 提交并推送。

## 2026-09-25 Feature 158 fixture evidence recovery

继续 T158-04 的 fixture 级收窄：登记与 bootstrap evidence 都已能以严格 canonical JSON
解析，并检查自身摘要。fixture 新增纯读取恢复 API，从 workspace 到 journal 持有逐级 no-follow
目录句柄，在同一 journal 句柄下完成 bounded、稳定 inode 读取并复核目录身份后，
强制 registration 绑定到输入 launch，并要求 evidence 的 launch 与 registration 摘要精确匹配。
通过或失败的终态 evidence 返回 `evidence_available`；缺失登记、缺失终态 evidence 或 unknown
evidence 返回 `recovery_required`。该路径不 spawn/relaunch、不检查或 signal PID/PGID，也不清理
进程。回归覆盖成功/失败终态、缺少登记或 evidence、unknown、文件和上级目录 symlink 替换、缺失摘要和
已重新摘要的绑定篡改。Feature 156/157/158 与进程所有权组合回归通过，Ruff、compileall
与 `git diff --check` 通过。

T158-04 仍保持开放。Feature 156 production runner 的 post-crash owner check、受权 cleanup 和
正式 recovery integration 尚未完成，fixture 的 `RegisteredProcess.owner_check` 不能授权故障后的
信号操作；没有扩大 scheduler、外部 producer、WebAgent 或真实 campaign 的接入范围。

## 2026-09-26 Feature 158 formal attempt cross-record observation

新增只读 `verify_trusted_bootstrap_attempt`，显式核对正式消费 claim、production bootstrap
登记和可选终态 evidence。Feature 156 claim 的 `executable_identity` 是目标程序完整 stat
元组摘要，正式 bootstrap 登记的同名字段是 bootstrap 完整 stat 元组摘要；两者分别由已核验
attestation 与 descriptor 推导，不能直接相等比较。验证器还绑定 launch/intent/attestation、
一次性 consumption、登记和终态 evidence 的摘要链；缺失或 unknown evidence 只返回
`recovery_required`。它不读文件、不检查或 signal 进程，也不写恢复回执。

新增重新摘要后的目标/bootstrap 身份互换、跨 journal、evidence 替换、缺失/unknown 和
fixture-only 拒绝回归。T158-04 仍开放：正式 runner 尚未产生这些 bootstrap 记录，现有 Feature
156 恢复路径仍按目标身份解释登记字段，不能直接接入该验证器或授权 cleanup。后续需先完成
平台字节绑定的 bootstrap 启动与目标交接、正式登记发布和终态证据，再扩展恢复语义。

## 2026-09-26 Feature 158 durable formal-attempt observation

新增只读 `observe_trusted_bootstrap_attempt`，从批次 journal 稳定读取一次性消费 claim、正式
`process-registration.json` 与可选 bootstrap evidence，并从 nonce 哈希命名的台账读取对应
claim。两条目录链均以 no-follow 句柄持有，文件读取有大小与 inode 稳定性检查；两份 claim
必须字节相同，再交由跨记录验证器做 canonical、自摘要和 launch/target/bootstrap 绑定。
缺失或 unknown 终态 evidence 仅返回 `recovery_required`，缺失或替换 claim、台账、登记则拒绝。

这只说明持久记录在读取时一致，不启动或检查进程，也不授权信号、清理或重试。Feature 156
正式 runner 尚未写出并消费这些 bootstrap 记录，平台执行字节绑定及故障后恢复仍待实现；
T158-04 保持开放，不能据此宣称对外 producer 或 scheduler 已可用。
Feature 156/157/158 与进程所有权的五套组合测试通过（2 项跳过），Ruff、compileall 和
`git diff --check` 通过；未运行真实 provider、外部 producer、WebAgent 或 campaign。
## 2026-09-26 Feature 156 provider-free capture matrix

在 Feature 158 Darwin 快照原子发布修复提交 `9017535` 后，补齐本轮 T156-09 的两个高风险
provider-free 观测点。`_capture` 在一条 stdout 或 stderr 超过上限后继续使用 selector
并发排空两条管道；每条流仍只保留上限内摘要，观测字节数饱和为 `limit + 1`，因此不会因
先超限的一条管道让另一条满管道阻塞。新增 fixture 同时写满 stdout/stderr，专项进程和
ownership 回归通过。

新增 hostile pre-gate fixture 在读取 gate 前写入持久副作用，并在 gate 后正常完成。该用例
明确证明普通 `run_producer_process` 只能记录 gate 顺序，不能证明任意 executable 在 gate
释放前没有工作；这仍是 T156-12/T158-04 的负例，不是可信 bootstrap 证据。环境、shell、
session、stdin 约束也在回归中显式断言。

本轮专项 `tests/test_producer_process.py` 与 `tests/test_process_ownership.py` 通过，Ruff、
compileall、`git diff --check` 通过。提交为 `53a3076 Complete producer capture acceptance matrix`。
推送因当前环境无法连接 GitHub（SSH 22 refused，HTTPS 443 unreachable）未完成；恢复网络后
执行 `git push origin codex/feature-156-producer-lifecycle`。T156-09、T156-05/06、T158-04、
T157-05/06 和真实 provider/campaign 验收仍保持开放，未扩大外部 admission 范围。

## 2026-09-28 Registered native acceptance runner and lifecycle budget slice

完成并推送 `b43615e`、`d891517`：新增唯一显式入口 `tools/run_acceptance.py`，入口只使用
标准库，在新的 `-I -S` 子解释器中加载登记 checkout 的完整 Python 源码清单；pinned loader
逐文件检查 no-follow regular file、inode/size/mtime/ctime 和 SHA-256，拒绝不完整清单、缓存
字节码和已加载的安装包。凭据只通过子进程环境传递。入口在缺少 loader 时于 child spawn 前
固定失败，相关测试已覆盖。

正式 native runner 已接入单次 attempt claim、材料复核、preparation 后 runtime/observation
binding、请求/观测 token 上限及固定结果留存；新增只读六阶段 campaign audit 和 create-only
audit publication/recheck，并新增可信 bootstrap registration 的 live owner、ready frame、
recovery-lock inode、bootstrap/target 字节绑定与 handoff 校验。producer transport 支持共享
单调 wall deadline，runtime 请求会计在未知 token 用量时 fail closed；native bootstrap 只向
target 转发显式 broker fd，不转发控制器环境或凭据。

专项回归：入口、campaign audit、native runner、pinned loader、trusted bootstrap registration
与 request transport 共 61 项通过；compileall、Ruff、`git diff --check` 通过。该切片已推送
到 `origin/codex/feature-156-producer-lifecycle`，工作区干净。

范围边界保持不变：尚未创建新的真实 campaign、未调用 provider、未运行真实 model attempt，
也未把 producer bootstrap registration 接入完整 Feature 156 cleanup/recovery 或 Feature 157
production journal。T040 的真实一次 attempt、独立 postrun/holdout audit、T156-05/06/09/12/14、
T157-05/06、T158-04 的完整生产接线仍开放；下一步必须从新的 registration、冻结材料、clean
`origin/main` 和唯一 campaign root 开始，离线准入与 runner 全部通过后才能启动真实验收。

## 2026-09-30 Native lifecycle audit increment

继续在当前 `codex/feature-156-producer-lifecycle` 分支推进 T158-04 的可观测性切片。原生
attempt 的 deadline sidecar 现在同时绑定 `launch_sha256` 与 `attestation_sha256`，因此只读
恢复和 cleanup recovery 都会拒绝换绑到另一份有效预算的 sidecar。

新增只读 `audit_native_trusted_lifecycle`：先验证正式 native process terminal，再按同一
attempt 复核可选 output capture 与 broker journal。没有 capture 时返回 `process_only`；有效
capture 返回 capture 摘要和 request coverage，但仍保持 `publication_eligible=false`；capture
receipt、broker journal 或其他持久证据改变时返回 `recovery_required`。若底层恢复只有
recovery/unknown 记录，不会再被误报成 process terminal。该 API 不 spawn、不 signal、不 cleanup、
不 publish。

本轮补充了 process-only、有效 capture、capture receipt 篡改和 broker journal 篡改回归，
并同步更新 Feature 158 data-model/tasks/validation。专项 native attempt 回归通过，Ruff、
compileall、`git diff --check` 通过；Darwin immutable snapshot 测试仍可能产生 pytest 清理
warning。没有运行 provider、WebAgent、外部 producer 或真实 campaign。

T158-04 仍未闭合：正式 Feature 156 `execution-receipt.json`、native terminal 与 broker journal
的生产绑定、publication admission、scheduler 接线以及 post-crash owner-checked cleanup/
recovery 仍待实现。

## 2026-09-30 Native execution-audit sidecar

在不复用正式 `execution-receipt.json` 的前提下，增加了可选的
`native-trusted-execution-audit.json` create-only sidecar。只有 process terminal、同一 attempt
的 output capture、deadline sidecar 和 registration 全部重新验证后才会写入；记录并绑定
launch/intent/attestation、registration、deadline、terminal、capture 摘要和 broker coverage，
固定 `publication_eligible=false`。缺少 capture、重复写入或任何证据篡改都不会得到 sidecar。

新增回归覆盖完整摘要链、create-only 冲突和 process-only 拒绝写入，并同步 Feature 158
data-model/tasks/validation。该 sidecar 只是后续正式接线的只读投影，不能替代 Feature 156
execution receipt，也不改变 scheduler、publication 或外部 producer admission。

同时增加了 sidecar 的只读 recovery verifier：它先重新验证底层 terminal/capture/deadline/
registration，再检查 sidecar 的固定字段、自摘要和逐项绑定；缺失、改写或仅重新计算自摘要
的 sidecar 都会被拒绝。

随后把 deadline 摘要继续绑定进 `native-trusted-process-terminal.json`。恢复会用当前 retained
deadline digest 重建 terminal；即使攻击者把 deadline sidecar 换成同一 launch 下另一份自摘要
正确的预算，也会得到 `native_trusted_recovery_terminal_invalid`。相关 native attempt/output
回归、Ruff、compileall 与 `git diff --check` 均通过。

## 2026-10-01 Producer lifecycle composition wrapper

On `codex/feature-156-producer-lifecycle`, the native trusted scheduler is now composed behind
the public `producer_lifecycle` API. `run_native_trusted_lifecycle` performs one provider-free
native attempt, persists the formal execution receipt, projects strict output preparation, and
optionally invokes the existing publication transaction when the caller supplies a strategy.
`recover_native_trusted_lifecycle` is read-only and revalidates retained evidence without spawning
or consuming another attestation. The preparation DTO retains native run/recovery observations
and reports request/broker/publication coverage explicitly; the cooperative entry point remains
unchanged.

Focused lifecycle and scheduler tests pass after the projection double fix; Ruff, compileall and
`git diff --check` are the required follow-up checks. This is an orchestration boundary only.
Feature 156/158 still have open production gaps: integrated bootstrap registration and
post-crash owner-checked cleanup/recovery, complete host-observed broker enforcement, and real
scheduler/campaign wiring. No provider, WebAgent, external producer, or remote evaluator is run.

## 2026-10-01 RSI transfer promotion composition

Feature 160 now includes an explicit provider-free `RSILearningController.promote_transfer_regression`
composition entry. It freezes the controller's current memory and supplied parent snapshot, runs the
local frozen transfer regression, checks snapshot/CAS and solver/verifier/curriculum/judge fingerprints,
then uses `MemoryPromotionAdapter` for the explicit `shadow -> approved` gate and optional
`approved -> active` step. Repeated calls do not rerun the suite or append duplicate governance
revisions. If a process dies after `shadow -> approved`, a fresh controller can resume the durable
`approved -> active` edge from persisted holdout/baseline evidence without replaying the regression.

The clean-room verdict bridge is also committed: `CleanRoomAdmissionGate` accepts only a strict
provider-free pass with matching episode/source/dependency/task/evaluator provenance and idempotently
records `observed -> verified`; it does not mutate `RSIMemoryStore` or skip candidate/shadow gates.

Focused RSI promotion, transfer, governance, clean-room, Ruff, compileall, and diff checks pass.
These are local fixture capabilities only; default automatic holdout scheduling, real evaluator/Actor,
external producer lifecycle, and real OpenEvolve/Shinka campaigns remain outside this handoff.

## 2026-10-03 Native deadline guard merged

PR #3 (`f7f547f`) is merged into `main` after the Ubuntu Python 3.11/3.12/3.13 CI matrix passed.
The native independent deadline guard is now on `origin/main`: intent/parent/RSI deadlines are
mapped once to an absolute native clock, the guardian supervises the lifeline and deadline, and
children recheck both before `exec`. The guard preserves `unknown/recovery_required` when terminal
evidence is missing. Remaining P1 work starts from this clean main: bind scheduler-backed execution
receipts to one RSI request's request/memory/launch/plan/candidate/evaluation/publication provenance
sidecar, retaining per-episode intent/attestation/journal isolation.


## 2026-10-03 Scheduler-backed native RSI composition

Feature 160/T160-35 now has a provider-free scheduler composition slice. `NativeRSISchedulerContext`
and `NativeRSISchedulerProvider` validate the already-admitted request/memory input descriptor,
recheck the immutable execution plan and launch/attestation/bootstrap/manifest/evaluator/environment
bindings, pass the request's original absolute deadline into the native scheduler, and map one
published same-journal candidate into the existing candidate, execution, evaluation and publication
receipt DTOs. Entry-point source and same-attempt output-capture digests are retained when available;
detached or all-rejected publication remains rejected. The native gateway exposes a stable wiring
fingerprint, and `PracticeEpisodeRunner`/`RSILearningController` require the native gateway and
controller to share the same durable ledger and memory snapshot.

Focused native gateway/plan/candidate/controller/scheduler tests pass, with Ruff, compileall and
diff checks clean. This is still local fixture composition: the context requires pre-staged native
launch inputs and does not claim external worker ownership, real evaluator authenticity, or real
OpenEvolve/Shinka campaign acceptance. The next acceptance slice is a full local native fixture
launch through this provider and read-only recovery, followed by updating T160-35 only after that
end-to-end evidence exists.

## 2026-10-03 Native RSI local acceptance continuation

Feature 160 T160-35 local composition is now implemented on branch `codex/native-rsi-local-acceptance`:
`NativeRSISchedulerProvider` performs read-only plan/recovery, strict retained evidence checks,
create-only provenance sidecar persistence, original deadline/cancellation propagation, and exact
receipt projection. `NativeRSISolverGateway` anchors the provenance and plan digests into the durable
`SolverResult` and validates evidence again during replay. `RSILearningController` reconstructs the
historical memory snapshot from immutable run/checkpoint history before cached native replay and
fails closed on retained/result drift. Local native E2E and controller replay suites pass; no remote
models, WebAgent, official evaluator, or external campaign were run. Remaining scope is external
worker ownership/authenticity, official evaluator/real campaign acceptance, and full CI/PR merge.


## 2026-10-04 Feature 169 local evidence boundary

Feature 169 local provider-free slice is implemented on `main` through commits `23f6018`,
`2a2df70`, and `a7a34a1`. `ExternalWorkerEvidenceStore` records immutable worker profile pins,
claim/heartbeat/terminal lifecycle through the RSI hash-chain callback journal, cleanup-gated terminal
states, and unknown quarantine. `OfficialEvaluatorProfile`/`OfficialEvaluationReceipt` binds evaluator
code/config/contract/task/holdout/seed with candidate source/execution/publication and raw verdict.
Native gateway mapping now requires both worker completed evidence and independent evaluator pass evidence.
The scheduler provider emits the same local fixture evidence, preserving native E2E replay. Remote evaluator,
external project authentication, multi-host ownership, and real OpenEvolve/Shinka campaigns remain out of scope.
