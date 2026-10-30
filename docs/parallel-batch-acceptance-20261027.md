## 12f987fb 唯一 Linux mixed 终态（2026-10-28）

- 原返回码 -15、timed_out=true、600.015900308 秒；缺 focused.xml 和 terminal
  loaded-lunar-modules.json。2523 源文件与归档 pre/post 匹配；28 个收取原件的
  哈希和大小经独审匹配。独审只证明保全，不改变失败结论。
- 后段 400–600 秒各有 40 个 main/worker 样本。main 全部在 owner publication
  service/handle，其中 28 次包含 rejection history；worker 全部在 mailbox request
  等待。末样 596.316 秒为 retain/acknowledge provenance → reserved history →
  rejection receipts 文件重读，没有进入 driver settled-terminal。不能推定 child
  序号、栈频次的耗时比例或死锁；无 stack completion，最后约 3.68 秒未知。
- PID 端点 400.000442–595.000365 秒累计 195.04 thread-group CPU 秒，leader
  runtime 187.793701 秒、runqueue 0.149491 秒。这不是函数级耗时。
- 原件：主区 ignored `parallel-batch-20261027/final-mixed-12f987fb-prepared/execution`；
  `independent-terminal-review.json` SHA 为
  `b90050a2ae5892911bcdb749c5faff81f909e021b93743639f252f9b9290445b`，
  `diagnostic-window-summary.json` SHA 为
  `5b64ed9660efb345d52cc6f74cee92eb0e76e69ec483c715b3ffaac33840a65a`。
- 778 项 focused/静态和局部 micro 通过仍不关闭 P0；本产品 source 不重跑，不启动
  已知失败的完整 CI，未合 main。P1/P2 真实可信生产接线与隔离验收仍开放。

## P0 后继：778 unique 全过，唯一 Linux mixed 待执行

720c唯一mixed原结果为600.031874664秒、rc=-15、timed_out=true，未生成JUnit/
terminal origins；2519 Git源文件和archive前后匹配。主区ignored
`parallel-batch-20261027/final-mixed-720c787d-prepared/execution`保留原件。
120栈样本延续至596.308162秒，最后进入settled-terminal/history读取；worker多次
等待mailbox。PID在400.000393–595.000346秒观察端点间累计195.88 thread-group
CPU秒、leader runtime161.691587秒、runqueue0.187999秒。这些不能归因到函数，
不能证明全部child完成；无completion record，最后约3.7秒仍未知。原source不重跑。

后继共享同次fresh prefix解析，新增小型exact JSON独立副本/C编码和明确code/limit
漂移门；不缓存验证/SQL/FS结果。集中16文件结果在`p0-json-prefix-collected-61rztvo_`：
778节点全过，rc0，157.992478167秒，零fail/error/skip，2523源码记录前后相同。
首个`p0-json-prefix-focused-x5_5mzts`在collection时因超大整数自动参数id而rc2，
0实际用例执行；仅补显式id后运行本次完整选择。原失败保留，不伪造union/成功JUnit。
`p0-json-prefix-static-s82at34j`保留实际Ruff/compileall命令及rc0。此前377/828不累计。

`runtime-tree-canonical-micro-x43pjjun`保留旧AST、产品builder生成wire与局部计时：
10文件/15,752B与266文件/93,086B样本bytes一致，median CPU分别
340.176→198.431µs、1753.208→1110.836µs，single-call调用数22,805→1,895、
123,669→11,111。产品source前后SHA一致；系统Python3.9在计时前import失败原日志
另存，实际采用既有miniforge3.13。不能据局部数据推算整例时长或解除P0。

新clean source仍需唯一600秒/零retry Linux mixed及完整CI后才可合main。
P1/P2已有四项软件维持原provider-free边界；accepted build/custody、trusted collector
sink、installed bridge/独立anchor跨重启保管、账户transition和guardian异常durable
证据/真实断线仍未验收。production/online=false，无WebAgent、模型或远程/公司evaluator。

## 前批集中回归：377 unique 全过，Linux mixed 待执行

本轮在同一集成source收齐四项功能后回归：compiler depfile捕获与输入比较、显式
in-image模块collector、installed账户只读预检、独立原anchor认证的native restart inspection。
默认入口不变；restart保留原deadline，仅recover(cleanup=False)/audit，不返回执行权威。

原始六文件结果：377节点、347pass/30fail、零skip/error、rc1、57.978726959秒；2519
源文件前后相同。所有30fail均由新collector测试helper在改变synthetic closure后没有刷新
描述中的closure SHA触发，原生产parser正确拒绝。仅修该测试文件；一次受影响回归72节点
全过、rc0、1.075133583秒、同2519源文件前后匹配。最新不同节点仍377，全过；两份XML、
原返回码和源码inventory保留，不累加为449，也不重复上批828。

原件均在主区ignored `.lunar-evolution/validation/parallel-batch-20261027/`：
`final-six-focused-g92m9_i4`、`final-six-affected-_mmxat4t`。原静态style失败同样保留；
最终Ruff/compileall、staged diff及独审单独绑定真实命令和当前source。

当前仅关闭上述provider-free软件检查；不声称真实CPython/solver执行、immutable custody、
trusted live sink、生产worker部署、账户transition、远端cleanup或发布验收。新clean HEAD
仍需原600秒/零retry Linux mixed，成功后才启动完整CI。5090gpu隔离权限门按原选择保留。

## Latest source successor: 828 distinct focused nodes

The only head1bb mixed run has naturally failed at600.0158098859247 seconds,
raw returncode-15, timed_out=true, without `focused.xml` or terminal actual
module origins. All2,494 Git files and full archive inventories match before and
after. Evidence is retained under ignored
`parallel-batch-20261027/final-mixed-1bb66721-prepared-w704hnlr/execution`;
independent review is `final-mixed-1bb66721-independent-review-k3k95qlm`, review
SHA`de0ef0617dafac5d6cec8d3029c9937ae96f46bde16316149c209834e3995fe8`.

The120 original PID samples span approximately595 seconds with597.09 thread-group
CPU seconds. The later180–595s interval still records416.69 CPU seconds. Large
rchar/syscall counts do not mean physical disk reads or identify a function.
The354 own-stack samples stop honestly at180.094s; last420-second stacks and
execution stages remain unknown. No unique root cause or deadlock is established.

The successor software batch adds the reserved class-static event digest memo,
explicit whole-deadline-v3 sparse collector, expanded fixed installation/startup
descriptions and worker-local original-context inspection. The concentrated
15-file run `final-software-batch-focused-5riuwhm5` passed828 nodes, rc0, no
fail/error/skip,38.82826054s. Its original Ruff rc1 with7 style issues is retained;
compileall rc0. Five style-only files changed, then only three affected test
files were run in `final-software-batch-affected-p5eqxn5e`:147 passed, rc0,
19.18351688s, zero fail/error/skip. These are the same147 initial nodes; the
latest distinct union remains828, not975. Both runs retain actual raw XML,
launch/selection/result and identical2,504-record before/after source snapshots.
Final project Ruff and compileall return0. Staged diff is checked before commit.
The independent latest-node review is
`final-software-batch-independent-review-yz32l733/review.json`, SHA
`db05f96bd7a952820f0cf5a560e1aaf59d79dd92cc7ea86503bc0fbf736a6a74`; its
pointer-only union SHA is
`8489bb4530cd8fb0489fd9284d57420c85d8493f437209e3dd1fa00ff2becb0a`.
No synthetic JUnit or replacement successful process result is generated.

Source preparation, synthetic descriptions and native fixtures grant no actual
solver/runtime/production acceptance. No model, WebAgent or remote/company
evaluator ran. The final clean source's original-budget Linux mixed/full CI,
accepted build/custody/live collector/native CLI, installed worker bridge and
restart resolver, account isolation and independent guardian crash evidence
remain open. Environment limitations do not close the remaining software tasks.

Earlier results below are retained for their original sources.

# P0–P2 actual acceptance — 2026-10-27

## Latest integrated source / native-origin batch

This successor retains the f8 ledger connection repair and adds exact official
Linux subprocess/calendar import proofs, explicit optional compression absence,
real POSIX/socket C/direct-header source pins, independent concrete-recipe input
checks and a default-disabled registered observer with original creation-FD pins.
The original syscall policy is unchanged. Both real source-only solver profiles
prepare: OpenEvolve has 93 frozen modules/33 native units and Shinka has 103/43.
The independent source review is
`p1-source-profile-independent-review-4fsq9qqd/review.json`, SHA-256
`7e4a67ae42af167088d9ee35fb03a218f451529dcc1e8ba72175b710825ddd31`.
Its final recipe follow-up SHA-256 is
`ab9e1b982b8fa775499032dcae52958341ea63c2965da6602548782cdfc9b9cd`.
No upstream Python, compiler, solver, model or evaluator ran in this source check.

The original 15-file run has 750 real cases: 738 passed, ten failed, two platform
skips, process return code 1, 52.639910583 seconds. Two synthetic native recipe
fixtures omitted an existing include directory. Eight new observer assertions
incorrectly required successful group cleanup from an exited child. Product
cleanup correctly retained unknown. Repairs observe the real cleanup primitive,
check every durable field and retain callback/closed-gate witnesses. A separate
POSIX exact-unit strengthening adds six negative cases.

The final four affected files have 242 passed, zero failures/errors/skips, return
code 0, 6.868898417 seconds. An intermediate 242-pass run before fixture-import
style repair is retained but does not add distinct cases or replace final bytes.
The latest union is **756 distinct nodes: 754 passed, two original platform skips,
zero failure/error**. Original XML/return codes are never rewritten. Both skips
are existing Linux-only producer tests on macOS, retained by exact node/reason;
Linux acceptance remains necessary. All runs have unchanged source inventories.
Final project Ruff, compileall and staged diff checks pass.

Evidence in primary-workspace `parallel-batch-20261027/`:

- `socket-real-source-1owpkr8z/`: actual dual-profile source-only preparation;
- `source-native-concentrated-ms3slqz5/`: original failing raw run;
- `source-native-affected-gqwy8ky2/`: retained intermediate passing run;
- `source-native-final-affected-sivm6ne2/`: final actual 242-node repair;
- `source-native-latest-union-sagnl2nu/focused-union.json`: pointer-only descriptor,
  SHA-256 `1afba59f973309d5186915944ca8887e4cc9c3e3a5d63f8617f4f76bda6452c5`;
- `source-native-final-static-zbpskxxq/`: original final static commands/results;
- `p2-creation-pin-independent-review-5sctjgp2/review.json`: P2 source review,
  SHA-256 `028b036459ec54df87823803ddf0159e1d0cd29f8a1d49133f739824bcc299d1`.

The clean successor still requires its own original 600-second/zero-retry mixed
run and complete CI. The source-only preparation does not establish transitive
C/header/config/link closure or isolated build/runtime acceptance. The observer
does not wire an installed external worker or prove crash cleanup, isolation or
real hard-disconnect behavior. It is synchronous trusted code; deadline checks
cannot preempt a callback that never returns. Existing 5090gpu KVM/privilege
blockers remain, with no host-Python fallback. Production/online remain false.
The older actual runs below retain their own original conclusions.

The tested source is clean commit `df81a46c3f394818d7675d7090f8d8db47ca01c5`.
The preceding local regression covers 1,050 distinct cases with all latest
outcomes passing; its original fixture failures remain retained. See
[local regression](parallel-batch-validation-20261027.md).

| Scope | Actual result | Remaining boundary |
| --- | --- | --- |
| P0 Linux `three-child-mixed` | Failed at 600.0162667399272 seconds; original process return code -15, timed out | No completed JUnit or terminal module origins; no merge or timeout-resolution claim |
| P1 fixed runtime/source recipe | Source generation and synthetic regression completed | Real solver source closure, reviewed target configuration, isolated build, ELF/image/startup, lifecycle and production CLI remain open |
| P2 fixed inert cross-host SSH | Passed, original return code 0, 122.10051275 seconds total | Does not establish candidate isolation, real network partition handling, remote cleanup or native publication |

## P0 original-budget run

The new head was run once on `5090gpu`, with the original 600-second execution
budget and zero retries. All 2,449 archived Git files and executable bits match
execution preparation and source inventories before and after the run. The SSH
driver and evidence retrieval succeeded; the actual test did not complete.

The v2 diagnostic contains 354 continuous samples over the first 180 seconds,
followed by a truthful `duration_limit` stop at 180.2542288871 seconds. The
separate completion record is absent because pytest did not return through the
runner's finalizer. Neither this observation window nor successful evidence
retrieval changes the timeout result. The known-PID accounting window spans
594.997504817 seconds with 597.19 seconds of thread-group CPU; children and
termination-time cleanup are not established by that observation.

Main-thread samples repeatedly reach ledger history/reference checks and
binding/runtime/record digests; worker samples mostly wait for the owner mailbox.
These are sample frequencies, not CPU-time shares or a complete causal account.
The ancestry optimization has not resolved the timeout. A subsequent source
change must have its own focused regression and actual acceptance; this failed
head is not rerun to seek a passing result.

Retained primary-workspace evidence:

- `release-closeout-20261025/final-mixed-v2-latest-node-bsicbjw6/`;
- independent `independent-df81-mixed-review-n09xllk_/review.json`, SHA-256
  `4858b809290fc3e88ebc00eac3fd7a8d57e896ea45c88c7dfd59f522d4acd03d`;
- `df81-mixed-stack-analysis-20n4jauj/frequency.json`, a derived frequency
  analysis of the retained original stack JSONL, not another execution.

## P2 fixed inert cross-host run

The initial uncompressed installation attempt failed before the local relay,
ledger or native claims were created. Its original return code 1 and
120.12141545885243-second duration remain retained. A separate read-only probe
completed and found its fixed remote installation absent at observation time;
this does not rewrite the original uncertainty or prove historical absence.

An independently allocated installation used gzip source transport, with bounded
decompression and the same complete per-file size/SHA inventory checks. The
installation SSH took 110.15710583 seconds, within its unchanged 120-second
limit. Product execution limits were unchanged. Its 293 installed source files
match the tested commit; inventory SHA-256 is
`2fca4d15ab7ddd25638bdc2d7140e1aa3a0eba49d1faec00b4b118640ae47db1`.

Two real SSH episodes each invoked the fixed harmless producer exactly once.
The direct episode authenticated its HMAC receipt. The second sealed its remote
response before a relay discarded it; reconciliation performed only inspection
and appended authenticated origin evidence. Its original settlement and
transport remain `unknown`. Duplicate dispatch was refused in both cases.
Both native claims remain `started`, with no native results or admissions.

Secret provisioning used the separate trusted SSH private-stdin channel and
private key files. No key bytes entered product wire, argv, environment,
receipts or public evidence. Production admission, native success, publication
authority, candidate execution, provider/model calls and remote cleanup claims
are all false. The installed host namespace is not an observed boot attestation.

Retained primary-workspace evidence:

- `parallel-batch-20261027/external-worker-ssh-inert-execution-ko0_7_uh/`
  preserves the first failure and its append-only capture-metadata correction;
- `external-worker-ssh-inert-gzip-execution-uvpu_kqg/` preserves the actual
  successful stdout, stderr and return code;
- `external-worker-ssh-inert-independent-review-g77jewmp/review-final.json`,
  SHA-256 `3484885631fdb940940ede09297ddde8c104dd33a5a610d1397c130dabdc0ae6`.

Actual local competing-wrapper/controller tests and interruption/reopen tests
also passed in the retained focused XML. This closes only the single local
authoritative ledger's competition/interruption verification. Untrusted-worker
account isolation, genuine network partitions, remote cleanup and any future
multiple-controller ownership remain separate open tasks. The diagnostic
`ssh_*_returned.elapsed_seconds` fields measure individual SSH calls, not a
shared cumulative stage clock.

## Subsequent source changes and concentrated regression

After retaining the failed `df81a46c` run, the next source implements only exact
persisted event-row expected-digest reuse and four source-pinned imported
stdlib selftest exclusions. Fresh SQL, JSON decoding, current stored digest
comparison, lineage and authority checks remain. Both changes received
independent source review. They do not by themselves close the mixed timeout
or either complete solver runtime.

The concentrated 14-file run had 382 distinct real nodes: 380 passed, two failed,
zero errors/skips, return code 1, 481.9929135 seconds. Source inventories before
and after were equal. The two failures came from new tests restoring inherited
JSON decoder methods onto the instance, which correctly disabled subsequent
cache use. A precise test-only cleanup repair leaves all product guards intact.
Only that affected file was rerun: 55 passed, return code 0, zero errors/skips,
0.69128475 seconds, equal source inventories. The latest unique-node union is
382; the other 13 files were not reexecuted. No synthetic JUnit or rewritten
return code is used.

Evidence under primary-workspace `parallel-batch-20261027/`:

- `record-source-focused-prepared-ce29lvnc/`: original result/XML, XML SHA-256
  `6ae6da6a6f9daccf331d7796da8fa143ddd5e2cbd54dfbe88c3e6e09e1b787ac`;
- `record-source-affected-sy9w69cx/`: actual 55-node repair, XML SHA-256
  `1e4f0e37b62726bd4c2fe5ce02e6c5190856d3ccd70adeaec4bd19721e84579f`.

The project CI command `ruff check src tests tools`, compileall and diff checks
passed. An earlier local invocation mistakenly selected all E rules; its
existing-style failures are retained separately and no bulk formatting was
performed. A new committed source still needs its own original-budget mixed
run before complete CI and any merge.

The source-only proposal refusal for OpenEvolve records a failure while scanning
`subprocess`; it does not record the imported module name. Static review finds
the first unrecognized Windows `_mswindows` branch reaches `_winapi`; after a
valid branch proof the required Linux `_posixsubprocess` is another gap. The
Shinka scan reaches the absent `_bz2`; `shutil` has an ImportError fallback at
the caller, but the current scan does not prove that transitive initialization
failure. Neither gap is turned into a successful module or blanket exemption.
Reviewed target configuration, isolated real build, expanded installation and
startup, solver lifecycle and native production CLI remain open.


## d152 actual mixed and resource-lifetime continuation

The clean d152 source ran the actual mixed case once after transport preparation.
An earlier fresh directory hit a 300.00648133-second upload timeout before prepare
or driver invocation; that failure is retained. A separate fresh directory then
used an exact-byte, SHA-checked block delta against the read-only retained df81
archive. Its rebuilt complete archive has SHA-256
`eb484771b819a5369e79f074be4a2a820d8eb4897adfdde7f0416996190ecc71`.
Preparation/upload success is not a case result.

The actual case failed: original return code -15, timed_out=true,
600.0333238020539 seconds, no JUnit or terminal module origins/finalizer record.
All 2,452 Git files/executable bits match preparation and before/after inventories.
The 353 own-stack samples truthfully stop at 180.407642 seconds; 120 known-PID
samples span 594.998289 seconds with 596.9 thread-group CPU seconds. Neither
observation establishes children, termination cleanup, timing shares or a complete
root cause. No same-head retry or full CI is launched for this known failure.
Independent terminal review SHA-256 is
`131ba014e0204aab0480dd7677ef826eab2877b80b834ce3437f362e957ae56f`.

The following source fixes a separately established resource-lifetime defect:
all 31 internally owned RSILedger connections now close after their original
transaction commits/rolls back; setup failures close before the original error
propagates. The raw private API still returns a real Connection. No transaction,
fresh read, authority comparison, budget or canonical representation is removed.
This is not yet a demonstrated fix for mixed performance.

The same batch extends the exact pinned imported-only CLI analysis to inspect.
A new real-archive source-only check still refuses both profiles: OpenEvolve now
records the exact observed subprocess.py:81 `_winapi` import, and Shinka records
`_bz2` from bz2.py:17 with another route through calendar.py:700 -> argparse ->
shutil. Original upstream sources are data only; no upstream Python/build,
model, solver or evaluator is executed. This closes one analysis defect, not
complete source/runtime closure.

Concentrated regression: 14 files, 379 unique cases passed, zero failure/error/skip,
pytest return code 0, 11.723235 seconds, unchanged source inventories. Original
Ruff failed only SIM117 in the new resource test. After combining equivalent test
contexts, only its ten affected cases were repeated; 28 distinct existing read-only
and replacement-race cases were added for deterministic-close concerns. That run
passed all 38, zero failure/error/skip, return code 0, 10.896873 seconds, unchanged
source. The latest distinct-node union is **407 = 379 + 38 - 10**; the other 369
passed cases were not reexecuted. Original failure/output/exit codes are retained.
Final project Ruff, compileall and diff checks pass.

Primary-workspace evidence under `parallel-batch-20261027/`:

- `mixed-block-delta-prepared-m8cwpuyc/execution/`: actual original result;
- `d152-mixed-independent-terminal-review-8x4eg2n0/review.json`: independent
  terminal review (SHA above);
- `ledger-inspect-concentrated-k9szduqp/`: original 379-case result and SIM117;
- `ledger-inspect-affected-v_o96wlm/`: actual 38-case result and final static checks;
- `ledger-inspect-independent-gate-15exen56/focused-review.json`: independent
  407-node inventory/XML/style-equivalence review, SHA-256
  `4615ba6b9916526621c1e74b57c85430d40a05d77253e4d9c1bfb7f783bc0ee6`;
- `inspect-cli-real-source-uc63w6v_/`: both retained real-source refusals.

The P2 native-lifecycle follow-up is specification only. Original installed-native
context binding, durable exceptional cleanup, candidate/account isolation and real
hard-disconnect acceptance remain open. No external HMAC/response or numeric PID
raises cleanup/publication authority. Develop the remaining unblocked parts before
freezing the next mixed/full-CI acceptance batch. This continuation has not merged
into main and does not claim P0-P2 completion.
