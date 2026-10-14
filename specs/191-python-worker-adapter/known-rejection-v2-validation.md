# Known rejection v2 validation

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
