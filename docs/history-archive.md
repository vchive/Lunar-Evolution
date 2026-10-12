# Historical evidence archive

Lunar Evolution uses the Python package `lunar_evolution` and the `lunar-evolution` command.
Original campaign records describe earlier product revisions. They were retired from the
current file tree during Feature 145; their contents, recorded scores, registration hashes,
and Git history were not rewritten as results of the renamed product.

[The archive index](history-archive.json) identifies 844 original files at Git commit
`c6947fdfbf43d84e83cc29cc215e7bc0250db83a`, recording every file's original size and SHA-256.
It covers 35 historical evidence/script directories, 73 test files, and 3 support files.
The original paths remain meaningful within that archived checkout. They are not active
paths or launch authority in the current product.

## Regression phases

Run the complete regression entry point from a full Git clone:

```sh
.venv/bin/python tools/run_tests.py --junit-dir .lunar-evolution/test-results
```

The entry point runs three separately reported phases:

| Report | Product and evidence | Required tests |
| --- | --- | --- |
| `current.xml` | Current working tree and `lunar_evolution` imports | Entire current test collection |
| `archived.xml` | Fixed migration baseline above | 2294 original historical tests |
| `frozen123.xml` | Original registration commit `5560eb9f67463badc31fed17e309bb5dc1dabf8f` | 24 original registration tests |

CI runs these same checks in independent roles for each Python version. The focused
gates remain separate, the entire current collection is partitioned into three file
shards, and the two historical phases run together. To run the explicit roles locally:

```sh
.venv/bin/python tools/run_tests.py --suite current --shard-index 0 --shard-count 3 --junit-dir .lunar-evolution/test-results/current-0
.venv/bin/python tools/run_tests.py --suite current --shard-index 1 --shard-count 3 --junit-dir .lunar-evolution/test-results/current-1
.venv/bin/python tools/run_tests.py --suite current --shard-index 2 --shard-count 3 --junit-dir .lunar-evolution/test-results/current-2
.venv/bin/python tools/run_tests.py --suite history --junit-dir .lunar-evolution/test-results/history
```

Each current shard assigns a complete test file by SHA-256 of its UTF-8 path modulo
three, validates the selected collection and JUnit case identities, and retains a
`current-shard-N.xml` plus its inventory summary. All three shard sets must be disjoint
and cover the entire current inventory. History retains its original reports and
`history.summary.json`. These role reports describe actual executions; they do not
replace a missing role or pretend to be a monolithic `current.xml`. The default complete
entry point above continues to produce its original three reports.

The historical test collection contains exactly 2318 unique nodes with a registered collection
digest. Exactly 24 nodes requiring the earlier registered product are deferred to their original
commit; no historical test is dropped or silently skipped. The original registration manifest's
77 product, 14 measurement, and 69 historical file pins remain unchanged.

Historical checkouts are temporary detached worktrees outside the current repository directory.
Their package identity is read from their own packaging metadata. Each gets its own virtual
environment and actual editable console launcher, so the original runtime identity checks remain
effective. Import isolation, file inventories, collection counts, JUnit results, and cleanup are
verified. The historical phases run offline test fixtures; they do not invoke providers or launch
campaigns, and passing them does not claim a new model score.

## Installation prerequisites

Use Python 3.11 or later and `uv==0.11.8`. Install the current development package using this same
installer before running the entry point, so its shared cache contains the build and test wheels:

```sh
python -m pip install 'uv==0.11.8'
python -m venv .venv
uv pip install --python .venv/bin/python -e '.[dev,lint]'
```

Historical environment creation uses offline installation and the current pytest version. A
missing cache entry fails explicitly instead of fetching dependencies or bypassing a historical
check. CI must retain full Git history and publish each role's reports and source/import
provenance separately.

## Private local evidence

Machine-local state and raw campaign evidence are preserved separately outside the repository.
They are not uploaded by the test runner or copied into its temporary checkouts. Existing evidence
may bind absolute paths, process identities, or file identities; moving an archive does not grant
permission or establish validity for resuming those executions. New product state starts in the
newly named state directory. Consult the migration handoff for the local archive location.
