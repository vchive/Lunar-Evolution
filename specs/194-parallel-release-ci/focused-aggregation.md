# Focused gate aggregation — continuation, 2026-10-27

## Scope and supersession

The user's latest instruction is to reduce repeated regression execution while
keeping required coverage. This continuation supersedes Feature 194's original
requirement to run focused tests a second time in independent pytest processes.
The original documents and old CI evidence describe their original source and
remain historical records. No old run or collector changes shape retroactively.

Python 3.11, 3.12 and 3.13 retain six current shards, three explicit heavy nodes
and the complete history role: 30 execution jobs. Their runner, original JUnit,
failure annotations, source/import provenance, history pins and sole permitted
archive retry remain required. This change does not add retries or skip tests.

Three lightweight focused-gate jobs depend on all execution jobs and run even
when an upstream job fails. An unsuccessful upstream result refuses the gate.
Each gate downloads only its own workflow run's version-specific artifacts and
consumes the nine original current/heavy reports. It never invokes pytest or
collects tests. History remains a required upstream execution, with its original
artifacts and validation. A missing history job cannot produce a green workflow.

## Contract

Keep the 78 original focused selections in a reviewed manifest. Its 62 explicit
test-count/zero-skip gates retain those exact counts and zero failures, errors
and skips. The 16 groups without explicit counts retain their existing skip
semantics; they must match the freshly collected full inventory and have no
failures or errors. Do not invent a zero-skip requirement for those groups.

For all nine reports, require exact role, workflow run/attempt, Python version,
checkout commit/tree/parents, executable and the existing two bootstrap import
observations. Require agreement between job provenance and runner summary.
Recompute full/selected inventory digests, deterministic file-shard and explicit
heavy selection, original JUnit digest, case-key set and XML counters/elements.
Reject missing/extra/duplicate roles, nodes, inventory disagreement or failed
reports. The nine case sets must be disjoint and union to the full inventory.
Each focused file must exist in that inventory. Reuse the runner's pytest
case-key mapping, including class and parameter identities.

Write a create-only derived JSON receipt identifying the original input hashes,
source and every group count/skip identity. Do not generate focused XML or call
the receipt another test execution. Source/import records remain bootstrap
observations, not proof of immutable code consumption or runtime acceptance.

The independently repeated process/order configuration is deliberately removed.
All required test nodes still execute on all three Python versions. One old
focused group used an external basetemp and disabled pytest's cache provider;
its source/AST/synthetic-namespace tests have no cache-plugin or process-order
requirement, and all 31 cases also passed in the original complete shards.

## Plan and validation

- [x] Preserve the existing selections/count rules in a 78-group manifest.
- [x] Replace the repeated focused role with three read-only aggregation jobs.
- [x] Implement exact original-report/source/shard/group validation.
- [x] Add synthetic positive and negative tests, with no full regression run.
- [x] Run the new tests once, Ruff, compileall and diff checks.
- [ ] Independently review the new gate and its own final-source CI evidence.

Negative tests cover upstream failure, missing/extra roles, source/run/import
drift, inventory/digest/partition drift, missing/duplicate case keys, hidden XML
failure/error/skip elements, explicit-count or zero-skip failure, preserving the
16 groups' allowed skips, and create-only output with unchanged raw inputs.

Historical run 40271759811 (head 717049b7) retained 77 focused reports per version:
8,082 executions, 7,918 distinct nodes and 164 within-focused duplicate executions.
Every focused node appeared in the same-version current/heavy original reports,
with identical pass/skip outcomes and skip reasons on all three versions. The
focused suite-time sums were 3,091.103, 4,375.701 and 3,256.501 seconds respectively.
These are historical repeated runner work, not a measured future wall-clock
speedup. Current configuration adds 58 cases and one group; its own CI remains
necessary. No provider, remote evaluator, company benchmark or real case runs
are part of this continuation.

## Local implementation validation

One Python 3.13.12 invocation passed all 58 new synthetic cases, with zero
failures/errors/skips (JUnit suite time 0.463 seconds). Original local report:
`/tmp/lunar-ci-focused-aggregation-20261027.xml`, SHA256
`acb82e94f6fe892456458e12ccb87ac56cd69d2af9a67fcea7176b887aaca2b9`.
Focused Ruff and compileall passed. YAML parsing, both checkout parent-history
settings, 30 execution plus three derived jobs, always-run failure gate, embedded
Python syntax and all shell-body syntax passed static checks; diff check passed.
No existing regression test, CI job or real case was executed for this change.

Independent review found and corrected two errors before that invocation: the
derived checkout also needs full parent history, and every XML skip element must
be the unique direct status of a testcase. A suite-level or nested skip cannot
be counted in the report while disappearing from the focused zero-skip gate.
The latter now has three explicit synthetic negative cases. Provenance binds the
complete interpreter version string as well as its version family/executable.
Own final-source CI and external collector adaptation remain pending; these
local synthetic checks do not establish that remote acceptance.


## Integration count reconciliation — 2026-10-30

The three original focused jobs in run40909497309 refused upstream failures
before reading the manifest; they did not prove the manifest correct. Independent
inspection of all three original full26402 inventories found exactly two stale
group counts: rsi-python-scheduler-inputs81→97 and independent-guardian82→101
(host9 + independent73 + readiness19). These are previously added case bodies;
no test ID, file membership, skip rule or required group is removed.

Update only those counts and the real-manifest assertion, keeping 83groups and
65 zero-skip gates, expected sum7366. The regression group263 is unchanged.
The combined Linux focused batch on tree28f7164b passed all complete aggregation
file cases among409 collected (408pass, one unrelated Darwin-only skip), with
original exact JUnit and source unchanged. Fresh complete CI and derived
receipts remain required; failed original reports are never rewritten to pass.

## Explicit Zig direct-LLD successor gate — 2026-10-30

The separate opt-in v4 linker profile adds the complete 53-case
`test_static_python_zig_lld_capture.py` file to the existing
`python-rsi-launch-source` group. That group becomes 680; the manifest retains
83 groups and 65 zero-skip groups, with expected sum7419. Initial focused
collection confirms 53 unique nodes and executes zero test bodies. The
consolidated successor software regression and its own final-source CI must
provide execution evidence; collection alone does not. Existing groups, skip
policy, budgets, selection and raw/JUnit/source gates stay unchanged.
