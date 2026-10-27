# P0–P2 actual acceptance — 2026-10-27

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
