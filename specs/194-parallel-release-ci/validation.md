# Validation contract

Test runner selection/control code with mocks, local inert XML and local pytest
identity fixtures. The runner uses the installed pytest JUnit address mangling
helpers; it does not add a product dependency. Partition conservation must hold across reordered collections and
file/class/parameter nodes; malformed/empty/duplicate inventories refuse.
Invalid shard bounds and flags for other suites refuse before I/O or spawn.
Existing role XML/summary/retry paths refuse without changing their bytes; new
summary publication uses create-only writes and retains prior failed evidence.
Selected collection and retained JUnit must exactly match expected case keys,
including duplicates/missing/extra nodes, failure elements and report counts.
Current metadata must identify the actual source checkout/imports and shard;
history must retain original archive/frozen source pins and allowed retry only.
All-suite existing tests remain required and may not be rewritten merely to
match implementation. Run focused tests, Ruff, compileall, YAML matrix/step/
annotation/upload checks and git diff --check after the relevant changes.

Remote final-source acceptance independently requires all15roles for all three
versions with correct source/tree/checkouts/imports, complete focused phases,
three current shard XMLs with disjoint exact-case union, archived/frozen phases,
known skip sets/reasons and original retry rules. Old pending CI stays bound to
its old source and cannot approve this matrix. Until that audit, runtime and
production capabilities remain unchanged and production_admission=false.

## Local validation on 2026-10-12

Python 3.11.15 passes 116 new shard/control cases plus 84 disjoint existing runner
and annotation compatibility cases: 200 unique passes, zero failures/errors/skips.
Python 3.13.12 independently passes the same 116 new cases; those repeated cases
are not added to the unique count. Source/test pins are unchanged across replays:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| `tools/run_tests.py` | 32221 | `c936aa2a535ccb72a6640eeb20bac3e6f4764988eb33899e5b3cd1963a413430` |
| `tests/test_regression_runner_shards.py` | 25636 | `55e36fccdf06695e766383c1e638a302f3fc22be2574eae5227ac41f758ef217` |

An independent full collect-only check finds 14600 unique nodes in 444 files.
SHA256/path modulo three assigns 4379/5159/5062 nodes in 145/158/141 files;
the three sets are disjoint and union to the complete inventory. Independently
constructed JUnit case keys are unique and match pytest's mapping. This is
collection evidence, not execution of the complete current or history suite.
The canonical inventory SHA256 is
`fd6eaa51e3742271c12816720e98b9669ee9019470c3a9ba4b9c070b2953a9e1`.

Whole src/tests/tools Ruff, compileall and diff checks pass. Static workflow review
confirms 15 independent roles, the original focused run body byte-for-byte intact,
47 focused XML phases including the new 116-case runner gate, complete role
annotations, create-only per-job provenance, whole-role artifacts and valid bash/
Python syntax. Independent runner review found no blocker; original all/native,
archive/frozen pins, collection and retry helpers retain their behavior. XML path
freshness is a preflight gate in an isolated CI checkout, not cross-writer locking;
summary writes alone have exclusive creation. Do not claim global XML race safety.

Original intermediate failures remain retained. The first child attempt used an
outdated mocked index fixture (69 passes/13 failures); its fixture was corrected.
Root's first replay used basetemp inside the primary checkout, so nested pytest
inherited the wrong rootdir and produced 115/116 and 83/84 passes. Replaying with
external /tmp basetemp gives the final passing results without product changes.
Old compatibility files were not edited. Retained ignored reports under the primary
checkout `.lunar-evolution/reports`:

- `parallel-release-ci-root-1791747609791679000` (original root failure);
- `parallel-release-ci-root-corrected-1791747693760268000` (final root replay);
- `parallel-release-ci-independent-and-original-1791747773720097000`;
- `parallel-release-ci-collection-1791747644509008000`;
- `parallel-release-ci-workflow-1791747730561796000`.

PR45 timing provides only an estimate: three current shards' largest retained
case-time sums are about 32–38 minutes per Python version; focused remains about
42–53 minutes. New CI queueing, elapsed speedup and acceptance are unmeasured.
Final-source remote CI, independent artifact/source audit and merge remain pending.
No real toolchain, CPython, provider, solver or remote evaluator ran.

## Current-1 high-descriptor fixture repair — 2026-10-12

Retained original artifacts identify `select.select` descriptor-limit refusals
in native fixture helpers, not a failed F01/F03/F04 comparator. PR52 run38169372402
has six py3.12 current-1 descendant failures; PR53 run38170726943 has one py3.11
independent-guardian descriptor refusal and one unrelated-worker wait timeout;
PR55 run38173032524 has two py3.11 plus six py3.12 descendant descriptor refusals;
PR56 run38173757590 has one py3.11 descendant descriptor refusal. The retained
failures report descriptors1024,1189 and1447, beyond Linux select's FD_SETSIZE.
Other current-1 version artifacts contain no failed cases.

A test-only `_native_pipe_wait.pipe_readable` uses `DefaultSelector` to wait once
with the original supplied timeout. It closes its selector on success/refusal,
leaves caller pipes open and unread, and preserves readable EOF. The four native
fixture modules use it for frame, acknowledgment and controller-output waits.
No native C source, runtime, ownership gate, runner retry policy, deadline or
production admission rule changes.

Python3.13 local validation passes seven new pipe regressions and five existing
worker process ownership cases,12 unique cases with zero failures/errors/skips.
Only local inert pipes and worker fixture commands ran; no CPython/static build,
sealed runtime, external solver or evaluator ran. Ruff, compileall and diff checks
pass. The PR53 worker timeout did not reproduce and is not declared fixed by the
descriptor repair; it remains visible in retained failure evidence. The ignored
main-workspace `current-shard-ci-repair-20261012` report retains all12 downloaded
current-1 artifact directories, original logs/XML/summaries/provenance, run metadata,
failure inventory and final focused XML/log. Own final-source Linux CI and
independent raw/source/tree audit remain pending.
