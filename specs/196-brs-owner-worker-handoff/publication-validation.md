# Feature 196 — publication validation matrix

Only local provider-free/inert fixtures are allowed. Keep public native BRS and
production admission closed. Matrices below separate the bounded implemented
refusal from future online owner bridge acceptance.

## PB-01 focused refusal and compatibility

| ID | Scenario | Required assertion |
| --- | --- | --- |
| RF-01 | Named worker helper called directly, in DRS owner scope or unscoped thread | Same fixed `rsi_python_publication_brs_worker_publication_forbidden`; no input parsing, callback, ready, transaction, ledger/workspace write. |
| RF-02 | Actual selected BRS worker before prepared ACK calls named/generic/DRS mutation facade | Fixed refusal occurs before `_plan_snapshot`, `_capture_admission`, native transaction, `_python_admission_inputs` or ready request; SQL/files and gateway count unchanged. |
| RF-03 | Actual selected worker after retained ACK/durable result calls those facades | Existing refs cannot bypass ownership; same zero-effect refusal. Original service completes its sole ACK/result and sibling stays unstarted. |
| RF-04 | Active worker supplies callback-bearing admission plan | Serializer/attribute callbacks remain zero; fixed refusal precedes caller DTO observation. |
| RF-04a | Actual entry source hook, dispatch/checkpoint callback and nested `_execute_intent` suppression | All three mutation facades refuse even when active/dispatch are absent; negative invocation marker restores after return and creates no grant. |
| RF-05 | Named helper gets expired/cancelled control and caller guard | Neither control nor caller guard sampled; fixed refusal leaves original files/rows unchanged. |
| RF-06 | Import compatibility | Named symbol and `__all__` remain; original call signature retained. |
| RF-07 | DRS/direct generic and read-only recovery | Existing publication/admission owner suites remain exact; no read-only resume gate added. |
| RF-08 | Scheduler separate direct route | Original live scheduler BRS worker refuses before direct transaction; pin-only ready/ACK remains permitted. Separate integration ownership/evidence. |

The actual selected fixture uses the existing service/channel, original wave, real
running/result/terminal ledger records and inert gateway. It does not manufacture
success publication. This gate closes no owner bridge task.

## Remaining PB-02/PB-03 online owner bridge acceptance

PB-03b below verifies only the original-BRS before/prepared checkpoint primitive;
PB-03c separately verifies the original persisted policy. The online
mailbox/controller/scheduler composition and complete publication lifecycle in
this matrix remain open; a passing primitive or policy case does not mark the
corresponding online boundary complete.

| ID | Boundary | Required assertion |
| --- | --- | --- |
| OB-01 | Online prepared lifetime | Owner acts while original worker/running episode/started claim remain live; no completed-return or fabricated DRS scope. |
| OB-02 | Success before/prepared | Original owner captures before snapshots and acknowledgment with exact checkpoint CAS/read-back; no latest adoption or extra reservation. |
| OB-03 | Success staged/precommit | Existing manifest/after pins retained before first move; stale checkpoint/prefix/inode/source/control refuses under original lock order. |
| OB-04 | Success terminal | Existing native commit/read-back and owner terminal CAS match exact selected result; only then published head advances. |
| OB-05 | Rejection C1/P/C2 | C1 binds original all-rejected native terminal; P is original create-only provenance; C2 retains its publishing-FD pin; no published head/memory advance. |
| OB-06 | Callback/thread refusal | Worker/nested callback cannot acquire lineage authority, mutate checkpoint or publish; source hooks/waits outside observation mutex; arbitrary worker DTO callbacks remain zero. |
| OB-07 | Unknown boundaries | Partial native evidence, missing before/staged/terminal, C1 without P, orphan P without C2, durable unknown marker or post-write read-back drift preserves original obligation/stale capture; no retry/repair/sibling. |
| OB-08 | Recovery | Exact historical request/memory/claim/pins only; read-only inspection cannot mint owner, acknowledgment or execution authority. |
| OB-09 | Serial successor | Next ordinal uses fresh handoff and verified head after original terminal/result; original M0/reservation retained; duplicate prior nonce/journal/claim/receipt refuses. |
| OB-10 | Public/default compatibility | Existing public native BRS refusal and DRS/single-child canonical bytes stay unchanged. |

## Evidence

Focused runs must retain source/install/import identity, exact inventory, raw JUnit,
all exit records, static argv/cwd/logs and source before/after hashes. Do not add
counters from different source hashes into one acceptance claim.

Required current slice checks include `test_rsi_python_brs_publication.py`, existing
`test_rsi_python_publication.py`, `test_rsi_python_admission_owner.py`, and selected
service/checkpoint regressions, plus Ruff over `src tests tools`, compileall and
`git diff --check`. Final-source CI and independent evidence review remain separate.

The final local eight-way run tested commit
`9684c6a773f5293c61201bc189ebc6197b121e91`, tree
`78aa65de6d16d4394365ddd4c0da267b756c5dec`: **261 passed, zero failures,
errors or skips**. Disjoint groups contain 35/28/36/37/29/34/31/31 nodes. All eight
pytest exits, collection, installed-origin, Ruff (`src tests tools`), compileall and
`git diff --check` exits are zero. Source maps before/after are identical.

Inventory SHA256:
`4f8ddcac0338c425d706cd98306bff2d6c88f0629889224d4b53446532fd774e`.
Controller SHA256:
`50c8b97941f7972300cb50714d40c9ee4bf72ed5fe6c5f3220e812f92bd1d63c`.
Publication module SHA256:
`e5da26c0b9ab97df828c4c5326d0d7c6e0f11954674c52e5f7071e917acab485`.
BRS publication test SHA256:
`0a00adde95b58ef8819c36bdd3982dd0acd626bcda8aca8a6a82189908a5f235`.

Raw result, exact inventories, JUnit, stdout/stderr, source/install and all exit
records are retained locally under ignored
`.lunar-evolution/reports/brs-owner-boundary-20261015/final-261/`, and on the
server under `/home/qinzhiqing/vchive/lunar-owner-boundary-final-22fypesh/`.
The original 209-case run at `e4f6a13` had 206 passes and 3 failures because its
global test spy also blocked the legitimate owner admission check after ACK.
Its original raw evidence remains in `failed-209/`; later passing runs do not
reclassify or replace it. The corrected spy checks the worker thread only.

The final documentation/workflow successor leaves all product and test bytes equal
to the tested commit. CI now requires the exact 116-case BRS three-module inventory
and a separate 14-case scheduler join gate. Independent stdlib-only evidence review passed 6,204 assertions: all 2,024 source
files (SHA/mode/size) match immutable commit blobs, exact disjoint inventory and
XML agree, all exits are zero and installed origins point to the remote frozen tree.
The reviewer independently downloaded the same 60 raw files; bytes match the local
copy. Ignored review JSON is
`.lunar-evolution/reports/pb01-final-independent-review-20261015/review.json`, SHA256
`8b81b2f29addbf22fe37c36dd9b5e471a9e5c7b59766fbb89942ea402da62ad3`.
This local run and review do not replace final CI. Future OB cases remain requirements, not test
or runtime completion claims.

A separate local workflow-compatibility run passed the 63 admission-channel and
23 BRS owner cases (86 total, zero failures/errors/skips, pytest exit 0); its XML
is retained beside the final-261 directory as `workflow-compat-86.xml`. Pytest
reported cleanup warnings for old read-only fixture garbage directories. This
supplementary run is separate from the exact 261-case acceptance inventory.

## PB-03b private before/prepared checkpoint acceptance

The frozen product/test source is commit
`309ce16fce58d4b70231a427ad0e1d5a47ce6a2a`, tree
`0fcaa3d362caf8dbab71489278da0bfd7cfd3320`. The final two-process local run passed
**40 = 37 new + 3 original** cases, with zero failures, errors or skips. The two
groups are disjoint and contain exactly 37 and 3 nodes. This is a separate source
acceptance, not an addition to the earlier 261-case or PB-03a inventories.

The new cases use the actual selected-service/channel, original wave, running
episode, started native claim and inert waiting worker. They verify exact
before/prepared deltas and distinct admission-reference/evidence-pin CAS writes;
owner/thread/claim/request/source/control/budget drift refusal; bounded detached
wire; genuine descriptor/snapshot/file pins; hooks outside the observation mutex;
live method/helper fingerprints; competing CAS, lost readback and stale capture;
completed-return and original DRS facade refusal. The owner remains private and
first-ordinal only. On that source its BRS policy is pinned at construction;
PB-03c below adds the original persisted pre-wave pin. `production_admission=false`, `online_publication=false`
and the fixture's `producer_multi_episode_publication=false` remain unchanged.
There is no staged/terminal, rejection C1/P/C2, online transaction, reconcile or
successor implementation in this slice.

The three unchanged compatibility nodes are exactly:

```text
tests/test_rsi_producer_staging_capsule.py::test_shared_evidence_accounting_is_pure_and_bounded_before_read
tests/test_rsi_python_brs_selected_service.py::test_actual_selected_service_acknowledges_and_settles_only_first_original_intent
tests/test_rsi_publication_lineage_checkpoint_kernel.py::test_original_drs_owner_uses_one_captured_head_cas_and_only_lineage_delta
```

All seven exits are zero: installed-origin, collection, group-0, group-1, full Ruff
over `src tests tools`, compileall over the same scope, and `git diff --check`.
The run used Python 3.11.15 / pytest 9.1.1, no `PYTHONPATH`, isolated short temp/home
paths and this worktree's editable install:
`/private/tmp/lunar-brs-lineage-owner-kernel/.venv/bin/python`. Interpreter, package
origin and editable direct URL all point to the same worktree. The before/after
maps are identical for all **2,032 tracked files**.

SHA256 records:

| Evidence | SHA256 |
| --- | --- |
| `src/lunar_evolution/rsi_brs_publication_lineage.py` | `f2587b8f30d91e1ffd6ab4e2057133de1a13bc9e87d41819751c9d25fe8ab817` |
| `tests/test_rsi_brs_publication_lineage_owner.py` | `2502b9e11f4ee1bde12e38c0da8eef489f012b4f495da24f3a12c31ff72ac7e7` |
| `inventory.json` | `9c85e229669871f312180388c80e3594e135baf39c5b3b44a9e8b71677817b6e` |
| `result.json` | `55f55ec595f86c7407dca6bc6b24558bedc72c69bcbd044fdb634dff46346bf8` |
| `group-0.xml` | `27ac85b3fbbbefeeb53e3b722d2adf818254f037fbee97bfe9d239f9c1897f74` |
| `group-1.xml` | `6a8cf48e58ff82ac4f31ea31d19d5c5323aa1c4246700a4e8a4617327a78b189` |

Raw XML, exact inventories, argv/cwd, exits, stdout/stderr, installed-origin and
source maps are retained in the ignored directory
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/reports/brs-lineage-owner-kernel-20261015/final-40/`.
The same task's stdlib raw/source verification passed **6,165 assertions** covering
the immutable commit/tree, exact four-module 37+3 inventory, raw XML/exit agreement,
installed origin, and every SHA/mode/size entry against the immutable git blobs.
This is source/evidence verification by the implementing task, not an independent
agent's raw review. Its script is
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/reports/brs-lineage-owner-kernel-20261015/audit_final40.py`
(SHA256 `9013c3f8a152398de1fbc0097b51be0d4c160205cb5980502893affcd99d42a3`);
the output is the sibling `final40-review.json`
(SHA256 `031b7943da3d268d40c5b0e376f19b7ffdf527cc3f568edd37846abbb61ec013`).
Separate independent code review of the frozen commit passed with no blockers.
Neither local acceptance nor code review substitutes for final integration CI.

### Preserved development and review failures

Earlier raw runs remain under the same report parent and are not final-source
acceptance. `development-1` through `development-4` each retain 0 passes/1 failure;
`development-5` retains 19/1 and `development-6` retains 25/1. They preserve their
original argv, source hashes, exits, timing and raw output. `development-7` passed
37 cases on the source before the final shared-budget binding amendment; its count
is also separate from the final 40.

Independent review found a genuine late-gate defect before the fix: a callback
after the inner selected-pins check could append a same-payload no-op revision and
advance the wave head, allowing latest-head adoption. The retained reproduction
`review-noop-before-fix.xml` has **0 passes/1 failure** (`DID NOT RAISE`), SHA256
`33b02ca0e10992e7691132983340899adf8b1599bcfb33eeed70d01742b39b9d`.
Its stdout/stderr are retained beside it; original product/test bytes remain in
`review-noop-before-fix-source/` (product SHA256
`4da169b0d714518cb485a4ce2885cefe7c360fc4b10e96e20a83e3da7ff4877a`,
test SHA256 `3d62b5ac792416aecd3b3d3f52123646fe7a1736136bbcb5bec47f7e966f9a88`).
The fix captures the exact adjacent reference head/payload before callbacks,
rechecks both after them, rereads the whole unchanged history and adopts only that
captured pair. The final inventory includes
`test_late_owner_gate_cannot_adopt_a_same_payload_new_reference_revision`; its
injection is at the late controller gate continuation. The original failed result
is preserved and is not reclassified by the later passing run.

## PB-03c original pre-wave policy acceptance

The frozen product/test source is commit
`399958c79e21fb300c661bd3366c58f21f24d546`, tree
`4892b1c0ae6290353cb92629657aa72a5d4bbc9a`. The final four-process local run passed
**402 = 21 new + 381 original** cases, zero failures/errors/skips. Disjoint group
sizes are exactly 73/166/134/29; the complete twelve-module inventory is:

| Group | Module under `tests/` | Cases |
| --- | --- | ---: |
| 0 | `test_rsi_brs_prewave_policy.py` | 21 |
| 0 | `test_rsi_brs_publication_lineage_owner.py` | 37 |
| 0 | `test_rsi_publication_lineage_checkpoint_kernel.py` | 15 |
| 1 | `test_rsi_python_brs_selected_service.py` | 28 |
| 1 | `test_rsi_python_brs_selected_settlement.py` | 85 |
| 1 | `test_rsi_python_brs_owner.py` | 23 |
| 1 | `test_rsi_python_brs_publication.py` | 30 |
| 2 | `test_rsi_python_publication.py` | 52 |
| 2 | `test_rsi_python_admission_flow.py` | 54 |
| 2 | `test_rsi_publication_lineage_owner.py` | 28 |
| 3 | `test_rsi_fingerprint.py` | 19 |
| 3 | `test_rsi_resume_contract.py` | 10 |

The new tests verify persistence before any worker, identical original policy in
the create-run record/fingerprint/all checkpoints, all existing recomputation
boundaries, missing/changed original/fingerprint/intermediate/latest pin refusal,
old-run refusal without backfill, JSON-only locked historical checks, pin-only
selected service compatibility, and unchanged DRS/provider-free/multiworker field
selection. Fixtures block subprocess execution and network connections. The legacy
child/publication flags remain false in the genuine BRS fixture. The policy is
non-authorizing: `production_admission=false`, `online_publication=false`.

All nine exits are zero: installed-origin, collection, four pytest groups, full
Ruff over `src tests tools`, compileall over the same scope, and `git diff --check`.
Python 3.11.15 / pytest 9.1.1 used this checkout's own editable install at
`/private/tmp/lunar-brs-prewave-policy/.venv/bin/python`, no `PYTHONPATH`, and short
isolated temporary directories. Package origin and direct URL agree. Before/after
source maps match all **2,038 tracked files**.

| Evidence | SHA256 |
| --- | --- |
| `src/lunar_evolution/rsi_brs_publication_lineage.py` | `c64f8cccffa2a85c18538bd5435d337cd3f6530eee951ebeee7bd22c82dae8ac` |
| `src/lunar_evolution/rsi_controller.py` | `86f6d3e11cd84e8c3248494f2ed44904e4e76ed2cfe1e8b9b90ec35b19fe80f1` |
| `tests/test_rsi_brs_prewave_policy.py` | `e724311d257d0acd2d9fbd8f014c9506b34a63608f22dfc0c211e56f95365ecc` |
| `inventory.json` | `00e0c4e065f6aac34c066e30062bc65b4fe4b7e93f3f6beb7cef99c8860db08a` |
| `result.json` | `9f229e688a6ec33625f0a92c327e550a4ebda36e8dc11a33cc5eaf7c7a0f6b3d` |
| `group-0.xml` | `330451488c54089e27344c02102d5280b8a9d272197eff10c261b66565bf8447` |
| `group-1.xml` | `4ca6303be522e511ff221c6c9867068be5cf5b3224570ab2c6d0249198179e56` |
| `group-2.xml` | `c514e6992102f74da1adb5ee478420cdb50e885237a59bd4cc7168e06c12c1d3` |
| `group-3.xml` | `202e0708a4e587567c7e9cfb4b8df573ae2348e882df78b911d57fa68901eac6` |

The raw XML, exact inventories, argv/cwd, exit records, stdout/stderr, installed
origin, source maps and driver summary remain in
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/reports/brs-prewave-policy-20261015/final-candidate/`.
The implementing task's stdlib-only raw/source verification passed **6,173
assertions**, including every source SHA/mode/size against immutable git blobs.
This is not an independent agent's raw review. Its script is the sibling
`audit_final402.py` (SHA256
`30916c57592f605032b9322e4c80f505e04614c68ea8fdc248a7ac721c981651`);
output `final402-review.json` has SHA256
`2ccfbfa104c940f8416d81247005f89c3d2ae36a4af6a985e7f307cf1ba93007`.
The first read-only audit attempt stalled in piped `git cat-file --batch` and was
terminated without a verdict; its script and attempt record are preserved as
`audit_final402-initial.py` and `audit-initial-attempt.json`. Bounded temporary-file
stdin fixed the verifier invocation. No product/test run was repeated or replaced.

Separate independent raw/source review also passed without blockers. The reviewer
did not run product code or pytest. Its independent stdlib checker verified
**10,756 raw/source assertions**, not additional test cases, including all 2,038
immutable source blobs and unchanged bytes in all 40 raw files before/after review.
The report is the sibling `independent-review/review.json`, SHA256
`9360ef020a79819cb1cad1556fc283462445bd43d4acdfa85b021f84275c846d`;
the script is `independent-review/audit.py`, SHA256
`e043d238659d304883bf91d0b1d9b2672610d71ffedac03a70083d28b2dae1c5`.
Its verdict covers only frozen `399958c`, not the separate terminal race fix.

A durable ignored copy is retained in the main checkout at
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/reports/brs-prewave-policy-399958c-20261016/`.
It contains all 61 original evidence files, the complete 2,038-file immutable
`source/` snapshot, and the four follow-up SDD documents at `40ceabf`. Its
`copy-manifest.json` covers 2,104 payload files with verified SHA256/mode/size;
manifest SHA256 is
`4a618a89f3c574911153c075086158cc5863fa03f3f78b596deed2423a58831a`.
Original argv and historical paths are preserved unchanged. The snapshot remains
available without the temporary worktree; caches and runtime fixtures are excluded.

Separate independent code review of `399958c` passed without blockers. The earlier
21-case development evidence stays in `development-1/` and is not added to this
402 count. The separate selected-owner episode-settlement race fix is absent from
this frozen source; this compatibility pass does not claim that race is fixed.
Combining the two changes requires preserving original `mode`/`plan` fingerprint
arguments in the extracted fixed-pin projection and fresh integrated-source
validation. Final-source CI remains separate.

PB-03c closes original policy persistence only. Online owner transaction/mailbox
composition, staged/terminal lineage, rejection C1/P/C2, reconcile, serial successor
and policy/memory composition remain open; public native BRS remains closed.

## Final integrated Linux checkpoint and wait acceptance

Frozen product/test source
`9d66b2382e85392bc2c134edff998899473e1f84`, tree
`89aed1b7e65ccc2304e9d8bec69b81fd37ec95ef`, combines preparation, checkpoint
kernel/owner, persisted original policy, the actual selected-owner terminal CAS
race fix and the two inert fixture corrections. **265 exact distinct cases pass**
with zero failures/errors/skips, in disjoint groups 78/85/73/29. JUnit group times
are 399.642/951.010/1476.810/2.204 seconds. All 17 collection/install/test/static
exits are zero; the independent own-editable Python 3.12 Linux checkout has no
`PYTHONPATH` during execution. All 2,042 tracked files match immutable Git blob
size/SHA256 and remain unchanged before/after execution and later collection.

Raw evidence and the independent review are retained at ignored
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/reports/p1-final-integrated-linux-9d66b23-20261016/`.
Root reran `independent-audit.py` successfully. Transport archive SHA256:
`6c39bc08119945703cdf7f3a0f8b45bba71707743c6a2cc2e7b0730c1ca10f5b`.
This is a single integrated-source acceptance; earlier 450/402/121/174/16 source
results are retained separately and are not added to the 265 count.

The original runner `_collect` was then called once in that same checkout for
**collection only**, executing zero additional cases. It retained 16,989 nodes,
SHA256 `380f69413192540e3c4056f5e62830f937e74ff0098d3bbc9a9cb6d65919267d`.
Six ordinary partition sizes 3190/2495/3097/2286/3255/2663 plus three isolated
heavy nodes form the exact disjoint full inventory. The 265 tested nodes and
189/38 workflow gates are exact subsets. The original collector internally sets
its child `PYTHONPATH` to this checkout's `src`; that collection behavior does
not change the separate unset execution environment or represent full-suite
execution. Workflow topology and 56 focused XML annotation paths are reviewed
separately from product/test runtime qualification.

Later documentation and annotation changes keep `src/tests/tools` byte-identical
to the frozen source. Final-source official CI, upstream integration and main
merge remain open. Only local inert/provider-free fixtures were used; no online
publication, production admission, real solver/runtime/campaign or remote
evaluator acceptance follows from this result.

## PB-02c/PB-03d unified final focused acceptance — 2026-10-16

The frozen product/test commit is `01c3bd1222fa6226762dbd65817e0d60d607330e`,
tree `e414add9b3488141bd773599c3fc5ef1d76652be`. Each platform passed the same
**322 distinct cases** with zero failures, errors or skips. The disjoint sets are
179 preparation/mailbox cases and 143 checkpoint cases (70 new, 37 original owner,
21 original policy, 15 shared kernel). The two platforms are not added into 644.

| Platform / group | Python and environment | Observed cases |
| --- | --- | --- |
| macOS preparation/mailbox | Python 3.11.15, own editable venv | 179 passed |
| macOS checkpoints | Python 3.13.12, own editable venv with system-site-packages | 143 passed: 70 + 73 |
| Linux preparation/mailbox | Python 3.12.3, own isolated editable venv | 179 passed |
| Linux checkpoints | Python 3.12.3, separate isolated editable venv | 143 passed: 70 + 73 |

The macOS total combines separate interpreter profiles; it does not claim a
single-profile 322-case run. Plugin autoload was disabled, execution had
`PYTHONPATH` unset, and each package/import/direct URL matched its original own
checkout. All process exits, full Ruff, compileall and diff-check passed. All
2,047 tracked source files stayed unchanged and match the frozen Git bytes. The
exact collection and JUnit case identities agree without omissions or duplicates.
Original checkpoint JUnit durations were 358.308/474.141 seconds on macOS and
609.00/777.43 seconds on Linux; concurrent group durations are not a wall-clock sum.

Canonical sorted-node SHA256 values:

- 179 cases: `8ceeff71199ce89f1c6d0bc8a95e9fef70d6f01177995e2cdb383b221500f5e5`.
- 143 cases: `43ebbf1307093168eb40d2f7d1ef9e22077126a72de916d82a37531c345f3ba6`.
- Exact disjoint 322 union: `a48d4f48ca62e2a5561d19c033892a94ea9516210cc41af0e8e0b60ba13ad819`.

A separate single collection-only invocation of the original `tools/run_tests.py`
collected 17,094 current nodes at that same source; **zero extra cases executed**.
Canonical inventory SHA256 is
`b1b1f55bf173375c1f28a12b779c16b90385e5423ac2e8b7c0ed3ca323756669`.
Six ordinary groups contain 3190/2495/3167/2286/3255/2698 nodes; together with the
three explicit heavy nodes they exactly and disjointly cover the inventory. The
322 focused cases are a subset. The outer environment had `PYTHONPATH` unset;
the unmodified runner's collection child explicitly uses that same checkout/src.
This collection does not claim 17,094 passed tests.

Independent product review passed at the exact frozen source. Independent raw
reviews validate immutable Git bytes, own installed/import identity, exact XML/
collection/exit records and the platform unions. Raw supervisors, source snapshots,
stdout/stderr/JUnit and review JSON are retained under ignored
`.lunar-evolution/reports/brs-combined-checkpoints-20261016/`; original development
failures and the pre-bundle-fix `97bb774` remain separately labelled. Neither old
runs nor different frozen-source counts are promoted or added to this acceptance.

The documentation/workflow suffix preserves all `src/tests/tools` bytes and modes.
CI separately requires the 35-case input and 70-case success-checkpoint gates, both
zero failure/error/skip; all 58 explicit focused JUnit outputs have one matching
annotation path. The final base-main PR still needs its own complete 33-job CI,
actual merge/tree/ordered-parent/import/raw audit, and verified main merge. The
public native BRS refusal, `online_publication=false` and
`production_admission=false` remain unchanged. No actual producer, model/solver,
CPython/toolchain target, campaign, WebAgent or remote evaluator was executed.

## Original-owner retained reader / prepared composition — 2026-10-16

Frozen commit `05cd548f7c4da324342327fabeca1ed68e49907d`, tree
`9d3c530849088e7ac7e5e091268b899d33fc1683`, contains the false preparation
contract correction, retained native reader, explicit prepared-reference pin and
reader → before → reference → evidence composition. The 498 distinct cases form
four disjoint groups: 113 new reader/reference/composition, 143 original checkpoint,
181 preparation/mailbox and 61 compatibility. The exact inventory SHA256 is
`b90786c40236e27176cf33f303177fae62dfbd2bbbf5b2cd23239d3bea3e2aef`.

macOS own-editable Python3.11.15 passed all 498, zero failures/errors/skips; all 16
collection/install/test/static exits were zero. All 2,053 tracked files match frozen
Git blobs and stayed unchanged. The complete raw/source/import/XML review accepted
this focused result; report SHA256
`d13197146f11620292cd0853725d870c50093f37fe89910effcb65ba93f0f94c`.
The same-source independent Linux Python3.12.3 run has completed 113/181/61; its 143
group is still running. Linux 498 acceptance is therefore pending. Original raw,
source snapshots, configs, bundle pins and reviews are preserved in ignored
`.lunar-evolution/reports/brs-owner-evidence-integration-20261016/`.

## Original-owner before retention facade — 2026-10-16

Frozen commit `855b08edd4de3dc0c379b99caa034e42f16efc4b`, tree
`b5052bc3bf779d62067a7a34f462abdb7e88737c`, adds the original owner
`validate_before` / `retain_before` facade. It retains actual bounded snapshots and
the native before descriptor before the original captured-head CAS. Independent
code review accepted the final source after channel/control/final-CAS hardening.
The transaction/staging entry gates remain DRS-only; this is no publication grant.

macOS own-editable Python3.11.15 and Linux own-editable Python3.12.3 each passed the
same 34 distinct cases: the 31-case new module plus 3 explicit original compatibility
selectors. Both have zero failures/errors/skips and all 13 process exits zero,
including full Ruff/compileall/diff-check. All 2,055 tracked files match frozen Git
blobs and stayed unchanged. Exact inventory SHA256:
`6cb5010681fa6c5655ff4581172240b170dcb04972f629f2213cbdb1a4e4e457`.
Mac raw/source/import/XML independent review accepted, report SHA256
`a9b2775bd76b2e76e59bee925bb2ef0876d58068e8cb148416e37824b8a3bee4`.
Linux full raw was transported with archive SHA256
`a2146d1830351c537f96cff8a20542171c7f29529222a9458196ae4c08fe2a06`;
its independent final raw/source review accepted, report SHA256
`3aecb67a8440a7306e7667bc3e1a566c6abb8e71252362a0eb1cdaaf4454a8b4`.
All materials are preserved in
ignored `.lunar-evolution/reports/brs-owner-before-evidence-855b08e-20261016/`.

The 34 cases at 855 are separate from the 498 at 05cd548; neither is added into a
single-source 532 count, and the 855 tree has not rerun the full 498. The workflow
suffix adds the 31-case gate and matching annotation; its 60 explicit focused XMLs
have an exact one-to-one annotation mapping. Product/test/tool bytes remain frozen
through documentation/workflow changes. PR109 remains separately frozen at b6faf226
with 58 focused XMLs and still needs complete 33-job official CI, actual checkout/
source/import/raw review and verified main merge. Only inert/provider-free fixtures
were used; public native BRS, online publication and production admission stay closed.
