# Known rejection v2 validation

## Controller integration checkpoint — 2026-10-15

Controller mode/history gates, original owner C1/P/C2, mixed terminal and started
inspection, three-way native scheduler recovery and explicit rejection reconcile
are implemented on the independent integration branch. Acceptance remains open.
The PR100 checkout and its CI source are separate and frozen.

The first joint focused run covered 476 distinct cases, zero failures/errors/
skips in 98.41 seconds. Its 787-file before/after source map was unchanged:
`2dbe8d0f8944627d03a14dbe74135817f700885a8d3ac708716289aa8767fd9a`.
Raw XML SHA-256:
`36db823d4666dab8f3e996421b558112debbce9b47980e63a38f12bd435f922d`.
This is an earlier development-source result, not final owner/controller acceptance.

Actual original owner/controller tests then exposed an exact child facade type
mistake, now corrected without relaxing the original provider/ledger gate. A pure
hostile nested DTO probe also established a serializer-before-shape gap in the
new inspector, now covered by terminal/started no-I/O tests. An archive assertion
incorrectly assumed that genesis had no archive; it now compares original bytes.
All failed XML remain retained with their own source boundary.

Final local integration source before long execution: 788 source/test/tool/config
files, map
`275e3f44385ebdce9ec43f7e585ea21d445043db781f33f1e773f2191e9fc85d`.
Final focused covered 478 distinct cases across two non-overlapping XML files,
zero failures/errors/skips; before/after discovery included additions/deletions
and matched the same 788-file map. Joint XML SHA-256:
`b7a2ac149c0a39ada3a19abb69303da31e238a22712ab43f04d330ff30b2084a`;
nested inspector XML SHA-256:
`beffebe3285b7a88a703e01546b6e912c7ae7cda8056cf14539efd79548b9bb9`.
Full Ruff, compileall and diff-check passed. Original terminal/started owner
cases, four successive durable reconcile crash boundaries and RPP/PRP/RRR are
executing in separate inert workspaces. Pending results must not be counted as
passed or combined with the earlier 476/helper results.

Remaining exit: complete original interruption/multicandidate coverage, final
source local results and independent inventory review, synchronize accepted
PR100 main, then final full CI/raw/source/tree audit before release. No runtime
or campaign acceptance is established by any local fixture result.

## Helper checkpoint — 2026-10-14

The independent worktree uses the PR100 product baseline `a62ac647`, retaining
its historical source evidence separately from PR100's later test-only fixes.
No controller/owner integration or complete v2 product acceptance is claimed.

| Scope | Local result |
| --- | --- |
| V2 lineage DTOs, original descriptor pins and v1 compatibility | Passed |
| Immutable native rejection reconstruction, ordered receipts and absence gates | Passed |
| Strict rejection DTO/mapping and original-FD mode-0400 provenance | Passed |
| All six ordered provenance sibling reader/writer conflict directions | Passed |
| Callback-before-I/O traps, including colliding keys and polluted pins | Passed |
| Original process-failure writer pure roundtrip and sibling refusal | Passed |
| Owner C1/P/C2, scheduler/gateway/controller and mixed-chain settlement | Not yet implemented/accepted |
| R-P-P, P-R-P, R-R-R and interruption matrix | Pending |
| Exact final-source full CI, raw/source/tree audit and merge | Pending |

Joint focused execution: 290 distinct cases, zero failures/errors/skips,
13.07 seconds. All process and network dispatch is forbidden by the inert
fixture plugin. The native rejection tests substitute only the lowest bounded
candidate execution/evaluation process seam; persistence and original receipt
reconstruction remain real local filesystem operations. Pure failure DTO tests
never compile or execute a native target and do not establish live authority.

```bash
PYTHONPATH=src:tests PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  -o addopts='' -p test_producer_bundle_rejection_immutable \
  tests/test_producer_bundle_lineage_v2.py \
  tests/test_producer_bundle_lineage.py \
  tests/test_producer_bundle_rejection_immutable.py \
  tests/test_producer_bundle_rejection.py \
  tests/test_rsi_native_rejection.py \
  tests/test_rsi_native_rejection_provenance.py \
  tests/test_rsi_native_provenance.py \
  tests/test_rsi_native_failure_rejection_conflicts.py
ruff check src tests tools
python -m compileall -q src tests tools
git diff --check
```

Source inventory: 781 source/test/tool/config files. Matching before/after map:
`520f5d9c107fbc72d44828edb1d81b66aa0d57c5cacba8cda026e3835ccae50f`.
Raw joint XML: `027ec98908962abdc5883f1b4f7486794df8dc7429cafae56d7efb906ced9916`.
Raw reports remain in ignored `.lunar-evolution/reports/`; separate A and B
cross-reviews verified their original source/XML hashes. Old, interrupted or
different-source evidence cannot close final integration acceptance.

All fixtures retain `production_admission=false`. Real CPython/toolchain,
OpenEvolve/Shinka campaign, WebAgent, remote evaluator and company evaluation
platform execution are outside this checkpoint.
