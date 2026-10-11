# Implementation plan

1. Extend the existing pytest runner with pure deterministic file-shard
   selection, JUnit case-key verification, explicit current/history entry points
   and role inventory metadata. Preserve all/native-e2e and historical behavior.
2. Add focused runner tests for partition conservation, class/parameter identity,
   selected collection/JUnit drift, provenance, CLI refusal before effects,
   historical pin/retry behavior and all-suite compatibility. Use mocks/local
   inert XML and a local pytest identity smoke; no full historical execution is needed for these unit tests.
3. Expand the existing workflow matrix with five roles per Python version.
   Keep the focused shell body/count gates intact, split annotations/artifact
   paths by role, and run current/history independently without needs edges.
4. Prepare the final-source collector for the15job role matrix. Compare each
   job checkout/import/commit/tree to source; compare exact shard case-key unions
   and existing skip sets/reasons to independent frozen source inventory.
5. Run focused tests, Ruff, compileall, YAML/role checks and diff checks. Retain
   original failures. Commit/push once the combined bounded slice is reviewable;
   independently audit its own complete CI before dependency-order merge.

Measured PR45 timings are a baseline, not a promise. File hashing can create
uneven shards;15jobs may queue under repository quotas. Do not claim an observed
speedup before the new source's actual CI. Focused remains a repeated independent
check; deduplication or removal is outside this feature.
