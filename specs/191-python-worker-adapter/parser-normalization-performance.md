# Pure binding parser normalization performance

Status: implementation slice; local validation and independent review pending.
This continues Feature191 Phase A; it does not change the admission contract.

## Existing contract and measured problem

The [spec](spec.md), [plan](plan.md) and [validation](validation.md) require an
exact, bounded, canonical binding parser with no filesystem, process, network or
budget effects. Public DTO serializers validate caller-owned mutable material;
sidecar, context, gateway, fingerprint, inode and CAS gates retain their existing
checks.

A warmed-import read-only profile of one existing 26,195-byte inert binding measured
0.086825 seconds with cProfile before this slice. One outer parser call invoked the runtime-manifest parser
11 times and the manifest validator 18 times; one nested DTO validator ran 1,927
times. This is a detached parser measurement, not attribution of the complete
mixed acceptance run. Native sampling provides C symbols, not Python function
names, and proves no full-run speedup.

## Smallest implementation boundary

`parse_python_producer_binding` constructs fresh exact child DTOs from strict
bytes or text, then constructs and validates an exact `PythonProducerBinding`.
Its final canonical comparison currently calls public `to_dict`, immediately
repeating the outer binding validator against that detached parser-local object.
Use the existing private `_to_dict_unchecked` projection only for this final
comparison. Child serialization, construction validation, digest checks and
the exact canonical comparison remain mandatory.

No parsed-object cache or caller-supplied validation marker is introduced. Public
`to_dict`, `to_json` and `digest`, `_sidecar`, `_context`, `_assert_ledger`, live
configuration/source checks, file pins, historical replay and CAS are unchanged.
The frozen release source and its running mixed tests are separate from this
worktree. Production admission remains false.

## Tasks and validation plan

- [x] Establish the existing Feature191 contract and parser-only scope.
- [x] Change the final private parser projection and document its detached scope.
- [x] Add byte/text canonical and refusal coverage, no-effects traps and public
  serializer rejection of same-wire callback collections.
- [x] Run 162 focused binding/runtime, sidecar, scheduler/context, gateway and
  identity tests; all passed (warnings were pytest temporary-tree cleanup only).
- [x] Verify five classes: no-effects equivalence; malformed/noncanonical wire;
  identity/deadline/budget mismatch; callback-bearing DTOs that appear to emit
  the same bytes; live inode/configuration drift and between-read mutation.
- [x] Compare baseline/candidate cProfile against the identical inert raw bytes;
  warm imports first and preserve profiler overhead and attribution limits.
  Baseline: 0.086825 s; candidate: 0.050686 s (41.58% lower in this single
  detached call). Outer `PythonProducerBinding.__post_init__` calls changed 2→1;
  runtime parser calls changed 11→7 in the measured path. This is not a full-run
  speedup claim.
- [x] Run Ruff, compileall and `git diff --check`; independent review remains
  pending.

Use existing `test_python_producer_binding`, `test_python_producer_binding_store`,
`test_producer_python_runtime`, `test_producer_python_runtime_tree`,
`test_rsi_python_scheduler_inputs`, `test_rsi_producer_gateway`, and identity
focused tests. Do not rerun the long mixed tests to validate this parser slice.

The new no-effects case forbids filesystem observations and mutation, runtime
verification, process creation and network access after fixture preparation.
The public serializer matrix mutates a parsed DTO with a tuple subclass carrying
callbacks but retaining the same apparent items; rejection must precede callbacks.
Timing is an ignored measurement report, not a flaky product-test threshold.

## Acceptance limits

A matching parser wire/result/refusal matrix and measured reduction establish
only local parser equivalence and performance. They do not authorize dispatch,
native runtime admission, release CI completion or merge, and do not substitute
for the original mixed XML/SQLite/source audit.
