# PB-03h integrated raw/source/import/XML/tree audit

This audit records the provider-free focused acceptance for the integrated
PB-03h candidate. It is deliberately separate from the full GitHub Actions
matrix and from the online owner bridge. The fixture does not call a model,
solver, WebAgent, remote evaluator, or company evaluation service.

## Frozen source and working tree

The audit ran in `/private/tmp/lunar-brs-pb03h-main-integrated` at commit
`bd1d195dd4997b7de52211963d537e2f82ec5d35`, tree
`0eb2c6da3fa68c0bfba5cb0d9636d0dde55a713f`. The checkout was clean before the
run. All 2,065 tracked regular files were present, and every working-tree
SHA-256 matched its immutable Git blob (2,065/2,065; zero mismatches). The
audit did not create tracked files. Ignored raw materials are retained under:

```
.lunar-evolution/reports/pb03h-integrated-audit-20261016/
```

The machine-readable audit record is `report.json` in that directory. Its
SHA-256 is `ca8e4961835c442dd9fc2197681d4c17a7a895d0ad524780df1f70be1b097b58`.

## Focused inventory

The exact three groups are disjoint and contain 72 unique pytest node IDs:

| Group | Command | Cases | Failures | Errors | Skips | XML SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Success evidence facades | `tests/test_rsi_brs_success_evidence_facades.py` | 38 | 0 | 0 | 0 | `5f21222958f922dbde7eb494d545cf736bd4d7a5d2af676c476e97529ebee3c5` |
| Original-owner before evidence | `tests/test_rsi_brs_owner_before_evidence.py` | 31 | 0 | 0 | 0 | `35d7e9bcddcb9fa3afea60721b66be6440d2cecd3dc95e6a23a5b50595be9019` |
| Compatibility selectors | Three explicit selectors from the prior owner/checkpoint suites | 3 | 0 | 0 | 0 | `f3be9c5146f5c8f6ccc900182703418ad66a5ef7c7b85d8708e2e3572d748471` |

The canonical sorted inventory SHA-256 is
`42c4bd77de64d735b2deb8dcae3d2e18adf3280a3d9b9908ddb958b57808b31d`.
The three compatibility selectors are:

```text
tests/test_rsi_producer_staging_capsule.py::test_shared_evidence_accounting_is_pure_and_bounded_before_read
tests/test_rsi_python_brs_selected_service.py::test_actual_selected_service_acknowledges_and_settles_only_first_original_intent
tests/test_rsi_publication_lineage_checkpoint_kernel.py::test_original_drs_owner_uses_one_captured_head_cas_and_only_lineage_delta
```

## Reproduction

Use short temporary roots because the native fixture enforces a bounded path
budget. `PYTHONPATH` is explicit so imports resolve to this checkout rather
than an installed package from another worktree.

```bash
mkdir -p /tmp/pb03h-audit/{tmp,home,xml,logs}
export TMPDIR=/tmp/pb03h-audit/tmp HOME=/tmp/pb03h-audit/home
export PYTHONPATH="$PWD/src:$PWD/tests"
python -m pytest -q tests/test_rsi_brs_success_evidence_facades.py \
  --junitxml=/tmp/pb03h-audit/xml/group-success.xml
python -m pytest -q tests/test_rsi_brs_owner_before_evidence.py \
  --junitxml=/tmp/pb03h-audit/xml/group-before.xml
python -m pytest -q \
  tests/test_rsi_producer_staging_capsule.py::test_shared_evidence_accounting_is_pure_and_bounded_before_read \
  tests/test_rsi_python_brs_selected_service.py::test_actual_selected_service_acknowledges_and_settles_only_first_original_intent \
  tests/test_rsi_publication_lineage_checkpoint_kernel.py::test_original_drs_owner_uses_one_captured_head_cas_and_only_lineage_delta \
  --junitxml=/tmp/pb03h-audit/xml/group-compat.xml
ruff check src tests tools
python -m compileall -q src tests
git diff --check
```

Observed exits were zero for all three pytest groups, Ruff, compileall and
`git diff --check`. The XML files, stdout/stderr logs and exit records are in
the ignored report directory above.

## Import and tree checks

The imported package and focused test modules all resolved inside this
checkout. In particular, `lunar_evolution.rsi_python_brs_native_dispatch`,
`lunar_evolution.rsi_python_brs_successor`, `lunar_evolution.rsi_controller`,
and both new focused test modules resolved below
`/private/tmp/lunar-brs-pb03h-main-integrated/src` or `tests`; no foreign
editable installation was used. The source map was compared against the
immutable Git tree after the run and remained byte-identical.

This evidence closes only the PB-03h focused raw/source/import/XML/tree audit.
It does not claim online mailbox composition, rejection C1/P/C2, unknown
reconcile, serial successor integration, production admission, real runtime,
remote evaluation, or multi-machine ownership.
