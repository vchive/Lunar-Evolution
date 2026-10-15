# Detached runtime tree parser validation performance

Status: local implementation, semantic comparison, focused validation and
independent source review passed. Integration and final-source CI remain pending.
This continues Feature191's existing parser contract; it grants no admission.

## Contract and measured problem

The runtime tree parser accepts exact bounded canonical bytes or text, validates
the declared manifest, directory graph, capabilities and digests, and returns
detached immutable DTOs. Parsing performs no filesystem, source/configuration
hook, process, network, ledger or budget observations.

In baseline `9684c6a`, parsing a tree first calls the declared-manifest parser.
The subsequent tree constructor's `_validate_tree` then validates, serializes and
parses that newly constructed declared manifest again. The second detached parse
cannot discover a new caller input: JSON supplied only plain data, all DTOs were
created inside this parse, and their validators contain no caller callbacks.

An inert single-episode/four-checkpoint `stager.validate_state` profile recorded
88 tree parser calls, 332 declared-manifest parser calls and 553 declared-manifest
validations. The baseline already contains the earlier `66251b0` binding-parser
normalization bytes; this slice addresses the remaining nested tree redundancy.

## Implementation boundary

Extract the original tree membership/shape checks and graph/digest checks into
shared private functions. Public tree construction and `__post_init__` retain
their original order: membership checks, full `_declared_manifest` revalidation
and detached reparse, then graph and digest checks. Build and verify still use
these public gates for caller-owned DTOs.

Only `parse_python_runtime_tree_manifest` uses a private finalizer for its newly
parsed exact declared manifest and newly constructed exact directory DTOs. It
initializes the three frozen fields, runs the same membership/shape and complete
graph/digest checks, and returns the DTO. This skips only the second detached
declared-manifest validation/serialization/reparse within that one parser call.
No parsed-object cache, caller-provided validation flag, authority token or
accepted-preflight cache is introduced. The result has the same exact class,
fields, wire and public revalidation behavior.

This reasoning depends on the existing trusted parser implementation, whose
strict JSON decoder and exact local DTO constructors accept no caller callback.
It does not permit accepting caller-owned DTOs through the private finalizer.
Changes to source/configuration hooks, source reads, live sidecars, inode/content
checks, ready capsules, checkpoint history, final current-state serialization,
deadlines and CAS remain outside this slice.

## Local validation

- [x] Add 27 byte/text roundtrip, exact refusal-code, no-effects and mutated
  public DTO/callback cases.
- [x] Run all 27 new semantic cases against both the original baseline module
  and the candidate; both pass.
- [x] Run 405 focused cases across the new tree parser matrix, existing runtime
  tree/runtime manifest suites and prior binding parser normalization suite;
  all pass.
- [x] Run focused Ruff, `compileall src tests` and `git diff --check`; all pass.
- [x] Preserve bounded single-call raw profiles, input hashes, source manifests,
  fixture inode/content inventories, SQLite dumps and refusal-spy observations.
- [x] Independent root-agent read-only review found no blocking issue in the
  finalizer's exact detached scope, preserved public revalidation order or new
  semantic/refusal/callback tests; no additional test run is claimed by review.
- [ ] Integrate with a release candidate and complete that candidate's own CI.

The exact same retained inert tree input is 11,187 bytes, SHA256
`621ae8e3bb66a59b35620841d129f787508076a44c8d8b1e90b1cfc7a792b1cb`.
One pure parse measured 100,867 → 74,821 function calls and
0.092698 → 0.061552 seconds with cProfile. Both return the exact original bytes,
leave source bytes unchanged, and trigger zero filesystem/process/network spies.
Single-call profiler timings have overhead and do not establish steady-state
throughput or an end-to-end improvement.

For the same validator fixture recipe (separate fresh fixture directories), calls
changed 16,140,170 → 13,852,568. Declared-manifest parser calls changed 332 → 244;
manifest validations changed 553 → 377. The original observation counts remain:
88 tree parses, 66 public binding validations, seven stager configuration checks,
two preflights, 99 component fingerprints, 198 fresh source reads and 180 hook
invocations (including recursion). Attestation supplier calls remain 1 → 1;
the sole supplier call occurred during setup. Source hashes, fixture content and
inode metadata, and read-only SQLite dumps are unchanged by each validation.

Validator wall time was 14.655 seconds before and 1.771 seconds after, but the
unchanged functions also ran several times faster in the second measurement.
Machine load therefore prevents attributing that wall-time difference to this
optimization. Only the reduction in redundant call counts and the identical raw
parser-input comparison are used as performance evidence.

Raw measurements are ignored development artifacts under
`.lunar-evolution/reports/validator-profile-20261015-01/` and
`validator-profile-20261015-02/` in the primary checkout. No long mixed flow,
real Python producer/runtime, solver, model or evaluator was run. Existing
`production_admission=false` and all original acceptance limits remain.
