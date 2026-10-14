# Known rejection v2 validation

## PR101 publication fixture correction — 2026-10-15

The `c75de8c` CI run `38612673297` failed the two parameterizations of the
inert-receipt terminal inspection test on Python 3.11 and 3.13. Its retained
evidence fixture omitted `evidence_sha256`, required by the immutable rejection
reader. The correction supplies that fixture field; production validation and
the real prepared/preflight/terminal, inode, checkpoint and read-only drift
assertions are unchanged.

The original two failures were reproduced locally with an explicit repair-tree
`PYTHONPATH`. After the correction, all 52 publication cases and 31 adjacent
transaction/interruption cases passed: **83 distinct cases**, zero failures,
errors or skips. Ruff, compileall and `git diff --check` passed. Original failure
XML, corrected XML, import origin and a 758-file tracked `src`/`tests` map are
retained under ignored `pr101-focused-repair-20261015`; this scoped map is not the
complete release inventory. An initial command without `PYTHONPATH` imported
the main checkout and is explicitly excluded from acceptance.

This correction has not yet been integrated into the frozen mixed-run source.
PR101 remains draft and its original failed CI is preserved. Final integrated
source CI and the mixed RPP/PRP/RRR acceptance remain release requirements.

## Original local acceptance checkpoint — 2026-10-15

Controller mode/history gates, original owner C1/P/C2, mixed terminal and started
inspection, three-way native scheduler recovery and explicit rejection reconcile
are implemented. RPP/PRP/RRR still run in their frozen workspace. Final integrated
release acceptance remains open; the PR100 checkout and CI source are separate.

| Original local scope | Different cases | Result |
| --- | ---: | --- |
| Joint focused and nested DTO refusal | 478 | Passed, zero failures/errors/skips. |
| Owner terminal and started read-only inspection | 2 | Passed, 659.38s / 586.12s. |
| Original C2 continuous durable reconcile crashes | 1 | Passed, 4315.288s; one unknown retry / one solver invocation. |
| Two ordered candidates / two BundleGroups | 1 | Passed, 942.238s; original ordered receipts and read-only terminal replay. |
| C1/no-P and original P/no-C2 | 2 | Passed, 361.338s / 378.329s; no orphan adoption or retry. |
| Absent/partial terminal and terminal-before-C1 | 3 | Passed, 65.293s / 65.962s / 298.307s; original started/running evidence retained. |
| RPP / PRP / RRR | 3 | Pending; not included in passed union. |

The eleven completed XML files have **487 distinct, non-overlapping cases**,
zero failures/errors/skips. This is a union across explicit separate source maps,
not a claim that one final release source ran all of them. An independent union
check is retained in ignored `v2-closed-local-union-checkpoint.json`.

### Source and evidence boundaries

- Product baseline `9cbf622`, 788 files: map
  `275e3f44385ebdce9ec43f7e585ea21d445043db781f33f1e773f2191e9fc85d`.
  Before/after discovery matched for focused, owner and continuous reconcile.
  Joint XML `b7a2ac149c0a39ada3a19abb69303da31e238a22712ab43f04d330ff30b2084a`;
  nested inspector XML `beffebe3285b7a88a703e01546b6e912c7ae7cda8056cf14539efd79548b9bb9`.
  Owner XMLs `045d5a4bdfec06f73a166982601d6b0679aa330d6e9245a5a51f8b05f2c7455b`
  and `51888d3f7f78e52695c04e8cdf5efaa9985b732719dd5eaff5113b7af82187cd`.
  Reconcile XML `eb51ee490a73bc44c49fda2c3574361e8f3e1a6d6b1486e1397a2c06ac9ef2ef`.
- Corrected dual-candidate tree, 789 files: complete before/after map
  `255a83e65b495f988a0aafa032cbc718b3929a6dd072dcf73b84af3fd06da077`.
  XML `bb9dbbc8d92b50117d8296b8711ff06083df779f870496f64a41d98583587e44`.
  Initial Python-only 771-item discovery is retained as partial; complete 789-file
  rediscovery also verified all immutable tracked blobs against `9cbf622`.
- Late C1/P and mixed tree, 790 files: map
  `b712c80ba88c4ca67fb3e39725e43650409136b50aefc64203919250f3a4d691`.
  Late-boundary XMLs `47269d565107e2e963b6ef5417200811f9f4728ca47bdf96761e8dac9de46c0a`
  and `5dbc7b5bca620a82ebb5322e044135b05cb7dc1572ff48e59fd594922bb3ebf4`.
  Their before/after map is equal; mixed execution retains its own final exit.
- Early-boundary tree, 789 files: runtime map
  `6bfc5f3b72881ccf752a4bcc3c2c0a2e4e98ebf5d385893d8a44a11eae465b78`.
  XMLs `aa9edf9564eb88149b625ba2591035d35b41333edd8cfcaafd3ddf51fad5dfb1`,
  `294e664fcfef2b4b252ca1d1817509ebf922227788ed1df133f3ba6b57764517`,
  `3504f63c32e31ccf7e943b28a4ae7edfe9e8067eb1c96668aab7576fbe3cf7f9`.
  After acceptance only the module docstring was corrected to disclose inherited
  inert receipt/recovery observation seams. AST excluding that docstring remained
  equal (`fafa1a94f9773a33875a5a474459658460833d93a1269cd9279fdbd75ccb252b`);
  final text map `49cee9f2226c39c1e1b3a4d2112bdb8570947c8af157ae963810e54a12998144`.
  Collect3 and static checks passed again; the earlier runtime source is not relabeled.

Original owner checkpoint peaks were 40,644 / 35,931 bytes; reconcile peaked at
41,273 bytes; late C1/P at 35,515 / 35,513 bytes. Reconcile ends running at
`producer_staged`, revision10: it only settles the original failed episode, not a
successor. No reservation, claim, result or reconciliation is duplicated.

The original controller, SQLite, owner/CAS, pins and local evidence paths remain
real. The existing fixture substitutes bounded producer/process/evaluator and
native receipt/recovery observations; this is not real runtime/native authenticity
or producer/model/toolchain/network acceptance. Every test retains
`production_admission=false`. Failed development/collection runs and explicitly
interrupted old mixed runs remain preserved, and are not counted as passes.

Full Ruff, compileall and diff-check passed on the original source windows. The
remaining release exit is final mixed3 evidence, complete source rediscovery,
accepted PR100 main synchronization, final integrated-source focused/static
checks, and full CI/raw logs/ZIP/XML/source/import/tree audit before merge.

### Earlier integration development checkpoint

The first 476-case focused run used 787 files, unchanged map
`2dbe8d0f8944627d03a14dbe74135817f700885a8d3ac708716289aa8767fd9a`.
XML `36db823d4666dab8f3e996421b558112debbce9b47980e63a38f12bd435f922d`.
It does not replace final original owner acceptance. Original execution then
exposed the exact child facade type error, now corrected without relaxing the
provider/ledger gate; hostile nested DTOs exposed serializer-before-shape, now
covered by no-I/O tests. The genesis archive assertion now compares original
bytes. Earlier failed XML retain their original source identities.

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
