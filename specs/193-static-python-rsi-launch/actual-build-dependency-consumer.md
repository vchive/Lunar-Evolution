# Actual build-output dependency consumer

This opt-in continuation joins the existing process executor to actual
compiler/linker dependency-file consumption. It does not provide accepted
build custody, prove complete compiler-driver input consumption, create a
production installation, or enable the production RSI CLI. The original
concrete recipe, compiler-only recipe and v1/v2/v3 runner defaults are unchanged.

`prepare_cpython_link_dependency_recipe` calls the original compiler dependency
recipe, retaining every `-MD` capture. For the same-source freezer and final
static-image link it adds the explicit arguments
`-Xlinker --dependency-file -Xlinker @work/link-dependencies/<target>.d`.
The bounded create-only dependency file is an output of that exact command,
in the same observed group as its executable. Unsupported toolchain options
fail the original command; there is no fallback to an ambient linker.

The new canonical manifest binds the original recipe/manifest hashes, successor
recipe hash and every compiler/link capture's stage, command index, target,
dependency output and explicit link-input vector. Before dispatch, the consumer
requires independent recipe and manifest pins and recomputes that complete
capture projection from the actual executable plan. Missing or altered capture
arguments, outputs, stage identities or capability claims refuse. The larger
v3 profile and original output/file/deadline limits are retained.

`run_dependency_checked_build` actually invokes `run_pinned_build_v3` once.
It accepts no caller output inventory or callback that can manufacture an
execution report. It consumes the original returned report and requires every
stage/command to have completed successfully, with its direct child reaped and
every declared output observed. It compares the persisted `report.json` bytes
with that original report before reading results.

The consumer walks no-follow directory/file descriptors, streams every original
input, private snapshot and declared output, and matches the original plan or
execution-report size/digest/mode. It checks descriptor identity/metadata before
and after each read and reopens the leaf to reject a replacement during that
readback. Original report pins are never replaced with current observed digests.
Only bounded declared dependency files are retained in memory. Inputs and
outputs are rechecked after both comparisons, before create-only evidence is
written. All reads/writes use the original absolute deadline and cancellation
callback; no comparison budget, retry or recovery execution is introduced.
Filesystem reads and fsync remain cooperative operations, not an independently
enforced hard deadline.

The existing compiler comparator checks all real `-MD` files. The new linker
comparator accepts the main make dependency rule and optional empty rules for
exactly its prerequisites, including ordinary make escaping. It requires the
original target and every explicit object/archive input. Each reported input
must resolve within the original disjoint source/toolchain snapshots or to a
declared output of an earlier command. Ambient libraries/CRT, undeclared Zig
cache/compiler-support products, future/current outputs, traversal, extra or
missing artifacts and mismatched report pins refuse. An observed cache input
is a closure gap; it is never automatically inventoried or approved.

On success the attempt retains `dependency-output-inventory.json`,
`compiler-dependency-comparison.json`, `linker-dependency-comparison.json` and
`dependency-report.json`, with their digests joined to the original report.
The result reports completed comparisons only. On process/readback/comparison
failure it raises a fixed `BuildDependencyError` carrying the original execution
report when available, preserves that report and all existing attempt files,
and emits no successful dependency report. Partial evidence writes remain
partial; no existing file is overwritten or removed.

The compiler/linker generated these dependency assertions. This mechanism does
not prove every compiler-driver/helper/cache read, link semantics, transitive
archive member use, configured-header correctness, immutable input custody or
descendant cleanup. In particular, a successful comparison cannot turn ordinary
workspace copies into an accepted build boundary. Both result and retained
evidence keep `immutable_custody_verified`, `driver_inputs_verified`,
`implicit_link_inputs_verified`, `installation_accepted`, `production_admission`
and `online_publication` false. Complete implicit input closure, accepted custody,
real isolated image/startup/solver/lifecycle acceptance and production per-episode
CLI composition remain separate work.

Validation is centralized after source freeze. New tests exercise prospective
recipe/refusal vectors and actual original-runner processes using an inert local
C helper that writes test objects, images and dependency files. These are real
process/output/readback tests, not actual CPython, Zig, static-image, solver or
LLD acceptance. They retain original process failure and post-execution source,
output/report/symlink drift, undeclared cache inputs and the shared deadline.
