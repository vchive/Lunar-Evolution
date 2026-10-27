# Actual Zig support preparation and explicit subsequent links

Status: implemented software draft; focused execution and real pinned-Zig
validation are pending. This is not a complete configured CPython build.

## Problem

The complete pinned Zig inventory already contains all 19,546 regular files.
Adding another inventory does not solve its driver's generated musl/CRT/runtime
archive dependencies. The old dependency consumer correctly refuses cache
products that were not previous declared outputs. The original concrete links
use `-lc`, `-lm` and `-lpthread`, which permit the driver to generate support in
its private cache during each link.

## Fixed executable preparation

`run_zig_support_preparation` calls the original v3 runner with exactly three
fixed C sources and four commands under its original absolute deadline. The
first three stages compile a target assertion, a main which references musl
pthread/math APIs, and signed 128-bit division to require compiler runtime
support. The last stage links them statically using the pinned Linux x86-64
musl Zig and writes the actual LLD depfile. It never executes that ELF. It
retains the original attempt, process report and errors and does not retry.

After successful original report/FD readback, the function bounds and observes
the original attempt-local global cache with no-follow traversal. Only the
original LLD-reported `crt1.o`, `crti.o`, `crtn.o`, `libc.a` and
`libcompiler_rt.a` become support outputs. All five must appear exactly once;
the original three objects must also be reported, and an external input,
unknown support name, link/special cache entry or changed cache refuses. Cache
inspection is limited to 32,768 entries, 512 MiB total and 128 MiB per file.
These are explicit supported Zig 0.16 shapes, not discovered allowlists.

The exact support bytes are read back and copied create-only into a separate
`sealed/lunar-support/` root, mode 0400. The canonical observation binds the
original preparation, source-fixed recipe, actual persisted process report,
actual LLD report, complete pinned toolchain inventory, cache inventory and
original generated cache paths. Original inputs, snapshots, outputs and report
are rechecked before returning. Ordinary private files are not immutable
custody; the word `sealed` names the export directory only.

## Real downstream consumption

`prepare_cpython_explicit_support_recipe` accepts the observed bundle, retains
all original compiler/freezer/source/configuration commands and adds these
previously generated products to the next recipe's toolchain snapshot. The
caller must stage the returned `toolchain_additions` beside the same pinned Zig
tree in a fresh input root. The original execution runner and actual dependency
consumer then copy/read/check these exact files like other toolchain inputs;
the bundle is not a callback and does not bypass their original readback.

Both original CPython static links use `-nostdlib`, explicit CRT head/tail and
an explicit libc/compiler-runtime archive group. They contain no implicit
`-lc`, `-lm` or `-lpthread`. The versioned successor manifest binds the support
observation digest. Its original LLD consumer requires the actual final linker
input set to equal the entire explicit set. An extra input is refused even if
it is independently pinned elsewhere in the toolchain inventory. An unresolved
or newly generated cache artifact cannot approve itself by its current digest.
The default dependency-recipe API and subset comparison remain available.
All newly emitted `zig cc` vectors use executor-owned `ZIG_LIB_DIR`; the illegal
old `--zig-lib-dir` pair is refused rather than silently rewritten. See
[the real-driver correction](zig-driver-resource-root.md).

This is a two-attempt build graph: support generation produces recorded bytes;
a later original CPython attempt consumes an explicit protected snapshot of
those prior products. It does not claim the first generation attempt had
immutable input custody. A bundle can express observations for comparison; its
Python type or digests are not an authentication or admission capability.

## Required follow-up and configuration boundary

The support generator currently uses the original trusted-tool local runner.
Podman's private `/tmp` cache is ephemeral and this implementation deliberately
does not claim to export it. The new downstream recipe can select existing
Podman custody, subject to that backend's real limits. Its current 32-command /
8-GiB full-tree replay limit still cannot accommodate complete CPython; this
change does not enlarge that budget or claim full build execution.

The complete target `pyconfig.h` remains an independently reviewed input. Three
C assertions cannot establish all Autoconf answers. A future real configuration
route needs the original pinned CPython configure/template/scripts, explicit
Linux x86-64 musl tool wrappers and independently reviewed cross-run answers,
then original process/custody evidence and exact generated header readback.
No host Python header or hand-written expected macro set substitutes for that
execution. Configure can execute shell/compiler probes and therefore cannot
be inserted into the current finite compiler/ar/freezer consumer as a parser
extension.

Focused tests use an explicitly inert native helper to exercise the actual
runner, cache files, original report, exported products and downstream actual
consumer. They do not execute Zig, CPython, a solver, a model or an evaluator.
They cover missing/external/symlink support refusal, pre-dispatch cancellation,
bundle drift/authority rejection and exact downstream linker-set refusal.
The initial real Zig case failed at the first compile because of the illegal
`cc --zig-lib-dir` vector. Its original failure is preserved. The corrected
source still needs one new single-attempt software validation before its
particular support-cache names are claimed observed.

All immutable-generation, driver-input, configured-closure, image/runtime,
production-admission and online-publication claims remain false. This code
closes an executable generation-to-explicit-consumption software path, not the
remaining configuration, full-build or production acceptance gates.
