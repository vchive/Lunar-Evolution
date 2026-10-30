<!-- completion-fresh-batch:start -->
## 当前执行点：P0–P2 软件合批已补验，长链与生产接线仍开放（2026-10-28）

`11761700250457c06e7a2adc0d41d4082ffca261` 唯一 mixed 在原600秒预算下超时：
600.031756874秒、rc=-15、零retry。原件和来源检查匹配不能代替缺失的JUnit与终态；
不重派该HEAD。PR #190旧CI失败保留；未锁依赖使pytest9.1.1升级到9.2.0，改变5个
历史参数ID并触发hostile bytes收集回调。本批改为uv.lock锁定安装，并为新增hostile
参数指定ID，历史源码/2318节点/SHA不变。

本轮并行软件已集中回归：

- 首轮tree `8c0f2e59d1084b1e3730f586cc2a19607c013d8d`，53文件1809 unique：
  1788 pass / 20 fail / 1 Darwin skip，228.130秒。18项夹具argv指纹/输入不一致，
  1项Shinka合成图缺SQLite头输入；另1项重复JSON暴露实际异常未归一化。
- 正规修复夹具，产品有限归一化OpenEvolve解析错误，补齐原native输入的solver与
  contract/evaluator/environment/memory复核；不放宽门。后继tree
  `565f138c0fa523209697add7025e66f1d9e0ab6f` 受影响12文件355/355 pass，
  18.761秒、16 workers、零retry。27顶层原件、26引用、源码前后、collection与模块
  来源独审通过；这不是所有首轮节点在后继tree重新执行。
- 本机唯一Darwin节点一次实际pass，2.345秒，非skip，前后源码/index保持一致。
  两轮Linux与Darwin按原节点去重汇总另存证据，不直接累加pass数。
- 完整Ruff、compileall、staged/unstaged diff check通过。

P0交易层统一callback后的完整owner postgate；普通history SELECT从`3+3R`降为
`2+2R`，常见callback whole-history链5次降至4次。最终完整重新SELECT、物理材料、
拒绝材料两端fresh观察保留；不能由focused结果推断600秒mixed已达标。

P1默认关闭的`fixed-producer-lifecycle-v1`已实现FD197原attempt通道、并发有界
读取、固定producer实际读入/broker/commit采集与原captured-envelope材料核对。
FD198仍solver前关闭，两个通道共用原deadline。source与sealed inode分别绑定。
但真实固定producer仍缺面向generic capture的`producer-result.json`交付：正向
原件链测试明确使用inert seam，不能宣称实际solver闭环完成。该缺口需版本化原输入
接线，禁止host凭摘要补造envelope。

P1 pycache有限预建目录的Linux inotify诊断已测：瞬时cache、目录拓扑、watch丢失、
overflow和deadline。原native写能力enclosure/quiescence未接，无accepted完成路径，
不清`original_pycache_observation`。真实隔离build/runtime、accepted build custody/
runtime根、生产CLI仍未验收。

P2前批同UID SSH EOF、receiver暂停和独立guardian deadline实测证据保留；独立账户、
blocked-storage和whole-group cleanup部署验收仍开放。
5090gpu普通Linux和/tmp可用；本机补普通平台缺口，macOS不能代替指定Linux隔离/
独立账户验收。`production_admission=false`、`online_publication=false`。
不运行模型、WebAgent、远程或公司evaluator。后继clean HEAD唯一600秒/零retry mixed、
完整CI/main仍待实际结果；本节不声明全部P0–P2完成或已合入main。

证据在主区ignored `parallel-batch-20261027/`：
`completion-fresh-gates-union-k13i71q0/`、`completion-original-affected-8pjd16yh/`、
`darwin-denied-egress-original-p_cagj44/`、`final-mixed-11761700-prepared/execution/`、
`CI190/diagnosis-and-fix.md`。以下历史记录不能覆盖本节失败/未完成边界。
<!-- completion-fresh-batch:end -->

<!-- current-p0-p2-batch:start -->
## 前批记录：P0–P2 软件合批补验后待 mixed 的历史快照（2026-10-28）

本批完成 P0 单次 fresh reference context 复用和单个 owner 操作内历史 wire 纯比较
复用，P1 原 preparation envelope bytes/解析 DTO 绑定，以及 P2 原 receiver 暂停时
独立 guardian deadline 测试。fresh SQL/JSON、完整 admission row parse/matcher、真实
目录 inode 与历史材料两端观察仍逐次执行；detached DTO 不继承原读取证明。

统一 Linux 27 文件：tree `43831e5314342b432a42c2e779ab684e4fb97b33`，766 unique，
746 pass / 20 fail / 0 skip，产品运行 85.553500984 秒。18 项在测试夹具向 slotted
owner 赋方法时失败；另外两项分别为替换共享文件读取 helper 触发原安全门，以及旧
fingerprint 字段预期未更新。仅修三个测试文件，并增加新 helper alias 漂移参数；
产品 src/tools 字节与 mode 未变。tree `95594bd03ce002348cdeb50f1afca70bf80b1c1b`
受影响三文件 54/54 pass，7.880675622 秒（外层 9.222155750 秒），零 retry。
最新去重为 767 项通过，不把原 746 与补验 54 相加；原 20 失败保留。
Ruff、compileall、staged/unstaged diff check 全过。原归档、manifest、JUnit、16
worker collection 与模块来源逐项收证；来源一致性不是 immutable bytecode custody。

P2 同 UID 实际 SSH transport EOF 用例已执行一次并观察到预期机制：双端 reference
fsync 后只断开原专用 local SSH，未发 G，远端原 controller 通过 EOF 进入既定 finally；
watcher exit78、D=false，原 reference/request 与 custody 保持一致。原 20 秒预算不重置；
execution/cleanup 仍 unknown，全部生产/隔离/whole-group authority=false。三固定 C
源和显式 compiler 编译的 trusted-local 镜像已独审一致，不宣称 build authenticity。
暂停测试和 EOF 均不代表实际 blocked fsync、网络黑洞或 controller SIGKILL 验收。

上一提交 `a691f56ab366d2e15e3be755a03b819efb528e8d` 的唯一 mixed 在
600.0163290952332 秒超时（rc=-15、零 retry），无 JUnit/主运行 loaded-origins。
原失败与有效 v2 字节独审均保留，不重派该 HEAD。新 clean HEAD 的唯一 600 秒 mixed、
随后完整 CI/main 尚待完成。合批通过不等于 P0 长链验收已通过。

P1 仍缺原 computation/pycache 采集、accepted build custody/runtime 根四项；真实
隔离 build/runtime、真实 solver/生产 CLI、独立账户部署、实际 blocked storage 仍未
验收。5090gpu 普通 Linux 回归可用；macOS 可补普通平台检查，不能替代指定 Linux
隔离/账户证据。`production_admission=false`、`online_publication=false`。
不运行模型、WebAgent、远程或公司 evaluator。

原件在主区 ignored `parallel-batch-20261027/`：
`envelope-stall-history-union-wuce45hb`、`envelope-history-fixtures-affected-5sljtnj7`、
`actual-ssh-disconnect-prepared-c4cjcjbe`、`final-mixed-a691f56a-prepared/execution/`。
前者证据独审区分真实测试失败与通过的来源检查；mixed 首版 audit 的 prepared/actual
launch 路径选择错误原样保留，由 v2 修正，不改变原执行失败结论。

以下是前批记录，不能替代上述后继尚待完成的验收。

## 前批记录（2026-10-28）：去重 759 项通过，随后 a691f56a mixed 超时

| 优先级 | 已实现并有回归证据 | 仍未关闭 |
| --- | --- | --- |
| P0 | owner 操作内有界 checkpoint history 纯投影；fresh SQL/JSON、最终 admission row/ref matcher、文件观察保留；constructor 指纹修复后的四文件 165 节点通过 | 新 clean HEAD 唯一 600 秒、零 retry mixed；通过后完整 CI/main。旧超时保留 |
| P1 | build 主错误/持久化错误分离、显式 pinned standalone linker；原 native observation → handoff 接线已测，相关新旧接线在第三轮通过 | expanded facts 所供原对象关系 inspection/export 的 45 项已通过；真实 computation/pycache 采集、accepted build/runtime 根、生产 adapter/admission/CLI 仍缺，不能据 DTO 或 fixture 宣称完成 |
| P2 | 同 UID controller-exit/receiver-kill 工具；原 reference 保管/只读恢复；后继补 exact watcher 提前退出观察、cleanup 前原状态诊断 | 两个实际故障用例和 fault 文件 69 项已通过；旧 host watcher mock 修正后单文件 9 项补验通过；独立账户/vault、SSH 硬断线、blocked-storage、whole-group cleanup 部署验收仍缺 |

四轮结果各自绑定源码，不累计重复用例：

- tree `b335456a`：1035 unique，1022 pass / 13 fail，928.645 秒；11 个 constructor
  fingerprint 失败和 2 个 sleep symlink 失败均保留。
- tree `85a3c4ac`：206 unique，204 pass / 2 fail，103.872 秒；P0 四文件 165 节点全过，
  两个 P2 因 uutils 原镜像 nlink=116 被 sealed gate 拒绝。
- tree `7fca9111`：620 unique，618 pass / 2 fail，53.716 秒；P1 新 observation handoff、
  RSI join、gateway/BRS 接线通过。两个实际 P2 用例各在原 20 秒预算内 controller
  超时，未得到有效 registration/reference。27 原件、26 refs、源码前后、16 个 worker
  collections 及 284 模块来源均核验匹配；测试失败不写成 focused 通过。
- tree `7628e971`：759 unique，758 pass / 1 fail，30.369 秒；新 P1 inspection 45 项、
  P2 fault 69 项（含原两条实际故障）、owner projection 31 项全过。唯一失败为旧 host
  watcher mock 不匹配新的 original Popen gate；不放宽产品门，修 fixture 后只补该文件。
  27 原件、26 refs、16 collections/JUnit/284 模块及源码匹配，失败 worker 无 crash。

后继 tree `e8d91db2` 只改上述 mock 的 5 行及六份文档；src/tools 产品字节与第四轮
相同。单文件 9 项补验通过，外层 5.501 秒，零 retry；最新去重仍为 759 项全过，
不相加成 768，也不声称全部源文件重新执行。原 758/1 结果保留。

第三轮之后，单次 finite sealed-target 诊断（无 pytest/guardian）确认 uutils 的
sleep 在约 0.0426 秒返回 1，明确拒绝 `/memfd:lunar-producer-executable (deleted)`
与 applet 名称不符。controller 持有 ACK writer 隐藏早退，导致原启动等待耗尽预算。
后继保持 sealed/strict R 与原绝对 deadline，不关闭 uutils 安全检查、不提高预算求绿；
改用显式 trusted-local 固定 nanosleep fixture，不声称 source→ELF build authenticity。

最后一次 clean HEAD `a8a70031` mixed 在 600.017935763 秒超时，rc=-15、零 retry；
无 JUnit/terminal module origins，24 原件和源码匹配。400–596 秒 40 个 main 样本中
reserved_history 27、store history observation 9，是栈位置计数，不是 CPU 占比。
新投影覆盖其中部分纯计算；不能由 focused 通过推断新 mixed 达标，不重派失败 HEAD。

实际 case 保留：CPython configure 75.302 秒/900 秒预算通过（44 原件、8 输出）；
Podman 7 命令/4 阶段 inert smoke 5.41 秒通过（210 原件）。它们不代表完整 build/solver。
Zig 0.16 三次 compile 成功，但带 depfile link SIGSEGV；替代拼写亦崩，停止旧 driver
追加尝试。显式 standalone linker 接线通过不代表实际静态 LLD/CPython 构建验收。

5090gpu 的 home/var-tmp quota 已满，独立 tmpfs `/tmp` 已核容量和写入/fsync/readback，
普通 Linux 测试继续可用。无 sudo/KVM、userns/bwrap 失败仍阻塞指定隔离验收；本机
普通测试可补平台缺口，macOS ARM 不能替代 Linux x86 隔离/独立账户证据。
不运行模型、WebAgent、远程或公司 evaluator；`production_admission=false`、
`online_publication=false`。当前尚未合入 main。

原件保留在主区 ignored `.lunar-evolution/validation/parallel-batch-20261027/`：
`joined-runtime-focused-template-_1l2in7j`、`joined-runtime-affected-rogbsp0f`、
`guardian-image-affected-b453dz6g`、`guardian-ready-evidence-union-96l_vob7`、
`guardian-host-ownership-affected-ebf8zous`、
`sealed-uutils-target-diagnostic-9asm3zx1` 及
`final-mixed-a8a70031-prepared`。以下均为历史快照，不覆盖本节。
<!-- current-p0-p2-batch:end -->

# P0–P2 integration, 2026-10-28

## Latest terminal results: mixed failed, installed guardian sidecar passed

The single Linux mixed run of `44cdd73ee7ec7e7fb823848c648d91553ebf55e0`
failed at its unchanged 600-second deadline: 600.032415813 seconds, rc=-15,
timed_out=true, no JUnit or terminal module origins. Its source matched the
archive before and after. Preserve the failure and do not rerun that product
source to obtain a pass; this branch cannot merge into main.

The later installed guardian sidecar slice passed its seven-file Linux affected
selection: 154 passing nodes, zero failures/errors/skips, 176.654491586 seconds.
All 13 new sidecar nodes match the frozen test's parameter expansion and passed.
Frozen index tree `e6aa50a6238237c0a4374f679ad93be8c9c64c6d` has 2,566 files /
2,874 manifest entries unchanged before/after and 232 matching loaded Lunar
product-module origins. All 11 top-level regular execution originals were
collected without recursing into fixtures; all 10 result file references match.
This later run does not test or close the earlier mixed failure. Real account
deployment, hard disconnect, blocked storage, whole-group cleanup and accepted
production runtime/CLI remain unaccepted; production/online stay false.

Original records are under the primary checkout's ignored root
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/validation/parallel-batch-20261027/`:
`final-mixed-44cdd73e-prepared/execution/remote-records/` retains the failed mixed
records, with `mixed-outcome.json` in its parent;
`installed-guardian-sidecar-linux-c5efv6z6/remote-records/` retains the passing
sidecar records, with `evidence-verification.json` in its parent. Each execution
ran once with zero retries. Source-path/byte origin checks do not establish
immutable consumed-bytecode custody.

## Prior concentrated batch: idle join, command inputs and durable guardian

The frozen index tree `2482e84d1e94ed4ac5d277194732205d52fe878a`, based on
`be7776bf`, adds operation-local reservation baseline encoding reuse, the private
reserved terminal idle-join hot checks, the explicit build command/input graph,
and an independent native guardian receiver with pre-gate registration pairing.
Actual events and Future completion retain full owner validation. The default
terminal join and default direct guardian paths remain unchanged.

| Concentrated execution | Result | Integrity |
| --- | --- | --- |
| Linux 24 selections, one pytest invocation | 496 pass / 7 Darwin-only skips, 410.777396921s | All 2,563 Git files / 2,871 manifest entries unchanged; 275 loaded Lunar module origins match |
| Local Darwin platform supplement, one file | 9 pass / 1 Linux-only skip, 0.780477958s | All 2,563 source files unchanged |

The seven Linux skips are the actual Darwin immutable-snapshot cases, all passed
by the local supplement. The executions share ten nodes, only two of which
passed on both platforms; the other platform gaps are covered by their respective
execution. The latest cross-platform union is 503 unique passing nodes, with
shared nodes counted once. The natural two-child
published/rejected composition passed in 264.952s. This is not the three-child
mixed acceptance or actual producer/model/evaluator execution. Final project
Ruff, compileall and staged/unstaged diff checks passed.

Evidence is under the same primary-checkout ignored root documented below:
`idle-command-guardian-linux-c6kjwovm/remote-records` and
`idle-guardian-darwin-platform-5_7eh93y`. The Linux result raw SHA256 is
`7d3ab693f69c9490fadb25cc232ede72c6ae3bf64dc3b6ab289970fb4bd8bf34`. Original companion bytes are retained. The archive
SHA256 is `777026b597135b9b759bfd6e9aa8108c994c7048a180cc1649e2e7288427ca5f`.
The frozen tree is not described as a later commit.

The subsequent `44cdd73e` original 600-second, zero-retry three-child mixed is
now failed as recorded above; full CI and the merge gate remain open. The later
sidecar slice closes the installed vault guardian-reference composition gap.
Complete driver/input custody, accepted isolated runtime and production CLI,
actual account deployment and hard-disconnect/cleanup acceptance remain open.
The prior `be7776bf` Linux timeout remains preserved. The ordinary local platform
supplement cannot replace Linux x86 isolation. Production admission and online
publication remain false.

The following sections retain earlier batches and their original results; they
do not supersede the latest terminal results above.

The batch implements three software continuations before concentrated regression:
operation-local staging identity parsing, the opt-in native private collector
sink, and installed wrapper/native bridging with independently retained original
restart anchors. Default protocols and original budgets remain unchanged.
Production admission and online publication remain false.

## Implemented and tested

- P0 retains immutable plain-entry bytes only within one history walk. Fresh
  checkpoint observations, state/policy/capacity checks and the admission reader's
  second SELECT/decode remain. Direct parser/digest drift falls back to the old
  path; scheduler/BRS projections pin the new helpers.
- P1 extends the original native runner with private pipe control v3. The selected
  in-image launcher writes the bounded collector result and closes the pipe
  before solver entry. The host compares original target/image/PID/manifest
  inputs. This is not an acknowledgement gate before solver start or accepted
  build custody. Legacy launcher and v1/v2 remain selected by default.
- P2 explicitly wires the wrapper to the existing native runner and its original
  registered observer. The observer retains the original anchor in a separate
  private installation vault before gate release. A fresh process reads that
  anchor and invokes existing read-only native inspection. There is no generated
  attestation, launch retry, solver-success conversion or deadline renewal.
- README now reflects existing HMAC, durable assignment and fixed SSH support,
  with one authoritative local controller and explicit unknown reconciliation.

## Concentrated results

The original failed `12f987fb` Linux mixed run remains preserved and is not rerun.

| Execution | Actual result | Source check |
| --- | --- | --- |
| macOS 58-file initial union | 2,164 nodes: 1,839 pass, 8 fail, 317 platform skips; 876.705357s | All 2,535 Git source files unchanged |
| macOS 10-file affected union | 461 pass, no failures/errors/skips; 6.782417s | All 2,535 source files unchanged |
| Linux 55-file frozen-tree union | 2,035 nodes: 1,970 pass, 2 fail, 63 skips; 580.047717s | 2,843 archive entries/2,535 files match before/after; all 231 loaded Lunar module origins match |

The latest macOS union is **2,547 unique nodes: 2,230 pass and 317 skips**, not
2,625. All eight original failed nodes passed in the affected run. Linux's two
failures are the original recipe-selection cases; their corrected-source Linux
execution is still pending. Skips are not passing platform coverage.

One genuine integration bug was found: the new recipe branch compared a shortened
launcher path that did not match the source plan's actual fixed path. The fix
makes the opt-in profile compile `runtime/launcher_live_sink.c`; the default
continues to use its original full launcher path. The two recipe failures exposed that genuine opt-in selection bug and an
incorrect default-path assertion. The other six failures were fixture construction:
two unset thread-local cache attributes, two bindings enlarged by the unusually
long test temp root beyond the unchanged 32 KiB cap, and two Darwin C-harness
deadlines using a different clock base. A fresh short private temp root and C's explicit CLOCK_MONOTONIC fix these
fixtures without changing product caps, C marker or Linux deadline semantics.

The first Ruff results are retained. Final project Ruff, compileall and staged /
unstaged diff checks passed after the affected repair. No model, WebAgent or
remote/company evaluator was run.

Evidence is in the primary checkout's ignored directory
`.lunar-evolution/validation/parallel-batch-20261027/`:
`p0-p2-concentrated-local-tc3joq0u`, `p0-p2-affected-local-e2hfu9yz`,
`p0-p2-static-bq3w2vuq`, and `linux-native-focused-draft-3buch_cy/remote-records`.
The Linux archive is frozen Git tree `fa33b03c21315cd6e73db08f1bf1eae4034595f2`,
base HEAD `72c2f973`, archive SHA256
`ce91f6adeaeabfeab48e647a19eb3c6cc511043e55aa0a270c3214670c5551ba`.
It is not described as the later corrected commit.

## Subsequent terminal results and active repair

The corrected-source Linux affected run passed all 235 nodes in 13.244750s,
with no failures, errors or skips. Its 2,536 files and 221 loaded Lunar origins
matched. The latest Linux deduplicated union is 2,035 nodes: 1,972 passed and
63 platform skips. It is not a complete rerun of all nodes at the final commit.

The clean `5bdf6b30` macOS mixed run naturally failed after 253.692564s, inside
the unchanged 600-second, zero-retry budget. The error is
`rsi_brs_reserved_ledger_capacity_exceeded` while finalization reads controller
journal revision 32. All 2,536 files and 271 loaded origins matched. The original
failure is retained and that product source is not rerun to seek a pass.

Inspection found an actual contract mismatch: checkpoint budgets measure compact
UTF-8 JSON, while SQL writers serialize spaced ASCII-escaped JSON; the reserved
reader additionally bounds the full row including metadata. The original short
temporary database no longer exists, so the exact failed payload length is not
known. The continuation fixes encoding and row-capacity prediction without
raising the reader's 128 KiB cap, in parallel with build-dependency consumption
and a fixed distinct-account access probe. Integrated regression follows author
freeze, with unsupported ordinary Linux checks moved to the local machine where
applicable. Actual isolated-runtime requirements remain separate.

Evidence: `linux-native-affected-j2wrukm2/remote-records`,
`linux-latest-unique-independent-audit-5qwt32av`,
`p0-p2-local-batch-preparation-135az0kk`, and
`darwin-mixed-failure-independent-audit-jpsr6pna` in the same ignored evidence root.
The independent mixed audit SHA256 is
`8d0a20a7dd3eeea7e537633209cfb75b2f3d5d9c895b1510b28ca6c1a65a1460`.

## Capacity/build/account continuation: concentrated terminal results

The continuation implements compact UTF-8 checkpoint storage with the unchanged
full-row meter before INSERT, metadata-aware staging reservations and deterministic
non-governed finalization growth prediction. Existing spaced/escaped history stays
readable without rewriting. Scheduler and BRS executable identities include all
new helpers, limits and static controller methods. Unknown governed admission
outcomes still use actual-write guards; whole-flow side-effect atomicity is not
claimed.

P1 adds an explicit successor recipe with bounded linker depfiles and an actual
consumer over the original v3 execution report, persisted report bytes, inputs,
snapshots and outputs. It refuses ambient/unpinned/cache inputs. This is byte
comparison after execution, not immutable build-input custody or complete compiler
driver input proof. P2 adds a root-installed fixed C access probe over the held
helper FD, credential drop, empty environment/groups and original deadline. Its
fixture passes are not genuine root installation/account/runtime acceptance.

| Execution | Result | Integrity |
| --- | --- | --- |
| macOS 23-file union | 692 pass / 1 Linux-native smoke skip; 52.462048s | 2,548 files unchanged |
| Linux first preparation | Refused before pytest, 0 invocations; tar modes differed | Original bytes/types equal; failure retained |
| Linux 23-file union | 691 pass / 2 old fixture failures / 0 skip; 115.013894s | Archive files unchanged; terminal origins match |
| macOS affected fixture file | 2 pass; 1.480895s | Files unchanged |
| Linux affected fixture file | 2 pass; 5.176850s | 2,548 files unchanged; 262 origins match |

The latest unique result is **693 Linux passes**, and **692 macOS passes plus one
platform skip**. The two affected nodes are replacements within those totals,
not two extra cases. Their synthetic absolute paths exceeded the unchanged 32 KiB
binding limit under the long evidence directory; a fixed short private test root
now makes that fixture independent of the runner location. No product cap or
assertion changed. Original results remain retained. The initial Linux installation
refusal was resolved with explicit Git tar.umask=0022; it executed no tests and
was not a failed-case retry.

Final project Ruff, compileall and staged/unstaged diff checks passed. Evidence:
`capacity-build-account-local-z9apm48p`,
`capacity-build-account-linux-5g4e_ctd` (preparation refusal),
`capacity-build-account-linux-install-egvarryv`,
`capacity-batch-affected-local-ps67ebey`,
`capacity-batch-affected-linux-tswy13tx`, and
`capacity-build-account-batch-zc85cyv_` under the same ignored evidence root.
The final clean product source still requires its own original-budget mixed and
complete CI. No current source is reported as merged or production accepted.

## Still open

1. P0: the corrected clean source's original 600-second, zero-retry mixed run,
   then actual Linux completion and complete CI before main. The small parsing
   probe and focused passes do not establish resolution of the repeated timeout.
2. P1 software: actual accepted-build/input-custody consumption, complete implicit
   link inputs and the production per-episode configuration loader/composition.
   Source recipes, descriptions and collector output do not supply those facts.
3. P2 software/design: installed account transition and its actual access/runtime
   evidence consumers; an independently surviving trusted durable guardian sink
   with reviewed acknowledgement/deadline semantics. A parent-owned pipe does not
   survive that parent; regular-file fsync has no hard completion bound.
4. Actual acceptance: isolated x86 build/image/startup/solver/lifecycle, distinct
   account key/state access denial, hard disconnect and abnormal cleanup. The
   5090gpu sudo/KVM/userns/bwrap restrictions affect corresponding environment
   gates; they do not explain away unfinished software. macOS ARM cannot execute
   the current accepted x86 build profile natively. Host Python is not a substitute.

No P0–P2 production-complete or main-merge claim is made by this report.
