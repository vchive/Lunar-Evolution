# Feature 194: parallel offline release regression

The existing three-version CI serializes focused gates and the complete current,
archived and frozen suites. Retained PR45 timing shows3–4seconds queueing versus
143.8minutes execution in the slowest lane; focused52.6 and full91.0minutes.
Parallelize execution without deleting, deduplicating or weakening any check.

Each Python3.11/3.12/3.13 lane has five independent roles: focused, current-0,
current-1, current-2 and history. All focused commands/count gates remain intact.
Current roles collect the complete current checkout, assign each canonical test
file by SHA256(path UTF8) modulo3, and keep all its parametrized/class nodes in
one shard. Selected re-collection and retained JUnit keys must exactly match the
expected subset with no duplicates. Every file/node is assigned exactly once;
three independent shard sets must be disjoint and union to the exact current
inventory in independent final-source audit. Skip IDs/reasons retain the existing
platform contract. Report names identify actual shards, never a fabricated full
current.xml. Historical source/pins/import checks and the sole allowed complete
archive retry remain unchanged. Existing all/native-e2e entry points still work.

Add explicit current/history suites to tools/run_tests.py. Current requires a
valid shard index/count before effects; other suites reject shard flags. Each
current role records current commit/import origins, full and selected inventory
digests, selected files/nodes, shard index/count and actual JUnit summary.
History reports only its actual archived/frozen executions with runner checkout
provenance. Full all continues to perform the original three phases.
The new current/history roles require unused XML/summary paths and refuse an
existing report rather than replacing prior failure evidence. Their summaries
are create-only; an unrelated per-job provenance file may share the result folder.

Artifacts and annotations are role-specific and retained even after failures.
Each exact final source requires its own complete CI plus independent source/
raw/tree/phase audit. Collector role sets are closed:3versions x5roles, exact
per-role phases and no missing/extra/duplicate shard/case evidence. No approval
or evidence may be copied from another commit or matrix role. No remote evaluator,
provider, actual solver or real sealed CPython build/runtime is introduced.
