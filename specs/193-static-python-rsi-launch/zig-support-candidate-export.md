# Explicit support candidate export and selection

## Scope

Continue Feature 193 with an explicitly selected trusted-local successor. The
old five-file support preparation, its failed/unknown attempts, and PR196 remain
unchanged. This route generates candidates without the crashing Zig `cc` linker
depfile option; it does not claim to capture that generation link's actual reads.
The original three seed sources, fixed complete Zig inventory, fresh workspace
and caches, original absolute deadline and zero retries remain mandatory. The
seed ELF is never executed.

## Generation and finite export

`zig_support_candidates.py` prepares the three original compiles and a static
seed link without capture, then dispatches the original v3 local runner once.
It reads back the original report and every output, checks original and snapshot
inputs, inventories both caches through bounded no-follow reads, and exports
nonempty, nonexecutable candidates with one of the seven finite support names.
Both caches share entry/byte bounds. Export records retain the complete cache
identity and relative path; two different `crt1.o` candidates remain distinct.
An observed basename admits a file only to the candidate set, never to a profile.
An empty candidate set is an observation, not successful support acceptance.

The canonical, independently hashed observation binds preparation, full toolchain
inventory, recipe, report, actual seed/objects, both cache inventories and exact
export bytes. Export is create-only with final FD readback and cache comparison.
No generated digest supplies source authentication or immutable custody.

## Independent selection and actual direct capture

`zig_support_selection.py` accepts the complete original Zig manifest, a separately
pinned PR196 direct-LLD profile, independently pinned candidate bundle, and explicit
pairs `(profile support path, candidate export path)`. It requires a bijection
onto every profile support row, exact bytes/size/executable pin equality, and the
original Zig row. It never chooses by basename or constructs an accepted profile
from current cache bytes. A candidate can be mapped to a role only when its
recorded support name also matches that role. Duplicate or missing mappings,
profile/inventory/bundle drift and authority claims refuse before staging.

Selection stages only `zig-lld/support/` in a fresh namespace beside the original
toolchain; original inputs and all additions are read through no-follow FDs before
and after. A partial staging failure is retained and cannot be overwritten.

A separate fresh direct-capture attempt recompiles the same three seed objects
and invokes the independently pinned `zig ld.lld` profile once, under the caller's
original deadline. It retains and reads back the actual runner report, objects,
ELF and genuine depfile. Both target and dependency set must exactly equal the
original seed target, three objects and every selected support input. The output
must pass the existing static ELF64/x86-64 no-interpreter/no-dynamic check. No
generated ELF executes, supplied depfile, verbose trace, automatic retry or fallback
can satisfy this gate. This function can fail when a declared profile is unsuitable;
it does not broaden the support set or infer a replacement.

## Boundaries and validation

This trusted-local implementation cannot export Podman's ephemeral per-command
`/tmp`. An isolated generator still requires a separately pinned, reviewed native
same-command exporter and real custody evidence. Complete configured CPython,
freezer, startup, solver, CLI and account/ownership acceptance remain separate.
All immutable-generation, driver/configuration, installation, production-admission
and online-publication claims stay false.

Develop all related software before one combined focused regression. Tests use
native inert helper processes through the original runner, preserve ambiguous
candidate identities, exercise strict selection and actual direct-capture report/
ELF/depfile refusals, and never run Zig, CPython, models, solvers or evaluators.
Then run Ruff, compileall and `git diff --check`. Real support-bearing acceptance
requires a new finite attempt with independently selected real profile pins; unit
fixtures cannot supply that evidence.

## Observed software and real-process results

Software tree88664bd0 was frozen before regression. Eight complete files passed
260/260 on Linux3.12, including41new cases, with no errors/skips/retries. Source
bytes/modes for2750files matched before/after. Ruff, compileall and diff checks
passed. The original focused group becomes721 while83groups/65zero-skip remain;
total expected coverage is7460. An external quiet-level assertion initially refused
before any test body; correcting that harness did not alter repository source.

One fresh actual candidate generation then used the complete fixed Zig inventory
and original120s deadline, finishing in47.601920s with zero retries. All four
commands returned0. It exported six candidates/14,157,612B: two distinct `crt1.o`
files and four archives. There was no `crti.o` or `crtn.o`. Bundle SHA256:
`ecd8af6d4341227cdb7ac157dd2fb0bcf6956993431f01069a4f1ec864e1a28f`.
The actual4,480,016B seed passed the static ELF check and was never executed.
42finite original files were collected and independently hashed. Large toolchain/
cache trees were explicitly excluded; their absence from the archive supplies no
immutable-custody evidence. An initial external script import refusal dispatched
no Zig commands and is not a failed seed execution.

After that observation, a separate explicit input declaration fixed the smaller
CRT's full export path and all four archives to the five support roles. Both CRT
symbol tables define `_start` and `_start_c` and require `main` and
`__libc_start_main`; this review is a selection rationale, not proof of which CRT
the generation driver consumed. The declaration uses prior output-derived pins,
not authenticated toolchain acquisition. Profile SHA256:
`4b39c32749dcc5e478477f5ac632185842e3c4d581f0d98eaba3109d9375868c`.
It was fixed before the separate direct-capture dispatch, without fallback.

The direct attempt created a fresh private toolchain copy, preserving the original
toolchain and all prior attempt snapshots. Under its own original120s deadline,
zero retries, it completed in33.617588s. Its actual1,484B depfile matches the exact
target and eight inputs: three newly compiled seed objects and the five selected
support files. The actual4,471,536B static ELF was not executed.38finite originals
were collected. Capture evidence SHA256:
`5d528f452ae9977a1b7fe1b341c087764b3695b7a92cada394ff85f58612c39b`.

These results establish the trusted-local support-generation/export and separate
direct-consumption path for the observed graph. They do not establish isolated
generation, complete compiler/driver reads, configured CPython, runtime/solver
acceptance or production admission. Original failures/unknown outcomes remain
unchanged. Local evidence: primary ignored
`.lunar-evolution/validation/zig-support-export-20261030/`.
