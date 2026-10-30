# Finite source-directory dependency comparison

## Observed failure

The first approved OpenEvolve full attempt on PR198 software completed all 298
original runner commands: configure1/freeze291/compile4/link2, all returncode0.
The original dependency consumer then refused a compiler depfile containing
`/source/Parser/lexer/../tokenizer/helpers.h`. This is an actual CPython relative
include; its target was already a declared source input. The attempt remains
failed, with its original 3,000-second deadline and zero retry.

All 202 compiler depfiles contain 44,304 dependency entries. Exactly 18 entries
use 12 distinct noncanonical source spellings, from Parser, Python and HACL
includes. Each canonical member and every traversed directory is represented by
the original source inventory. The independent linker comparison already passes.
Original reports, depfiles and failure are retained in primary ignored evidence
`validation/native-support-export-20261030/full-cpython-openevolve-attempt-v2/`.

## Explicit comparison profile

Add `compare_compiler_dependencies_v4_source_directories` with the original v4
arguments and fixed profile `source-inventory-directories-v1`. It accepts only a
source-owned table of these 12 exact relative spellings. It does not accept a
caller mapping, arbitrary path normalization, additional source inputs or a
failure-based fallback. Legacy/v4 entry points remain strict and byte-compatible.

For a listed spelling beneath the exact source root, walk each directory token.
Every ordinary prefix must be a parent directory of a declared source input and
must not itself be a declared regular file. `..` must have an existing directory
to leave and must never escape the source root. Returning to the source root is
permitted; traversing a missing directory or a file is refused. The resulting
member must exactly equal the fixed table's canonical member and already be a
pinned source input. Unlisted spellings, relative aliases, duplicate slashes,
dot components, toolchain/work aliases and root escapes retain their refusals.
Compiler targets, source membership, output order, raw depfile byte pins and
prior-output availability checks remain unchanged. No filesystem is consulted.

The new comparison receipt schema is
`lunar-cpython-compiler-dependency-comparison-v3`. It retains the existing v4
binding and false authority claims, adds `dependency_path_profile`, and records
unique observed `source_directory_aliases` sorted by reference. Each record has
`reference`, `canonical_reference` and the traversed `directories`; returning to
the root is recorded as `@source`. These are inventory relations, not original
directory-inode acquisition or a proof of all compiler reads.

## Original execution composition

Add `run_dependency_checked_build_v4_vfs_retained_source_directories`. It selects
the new comparator explicitly and otherwise calls the unchanged v4/VFS-retained
runner, original report-v6 readback, linker comparator, budget and failure path.
Its dependency receipt uses `lunar-actual-build-dependency-consumer-v5`, the fixed
profile, and the compiler receipt hash. Existing consumer schemas/defaults remain
unchanged. No successful detached comparison relabels the original failed run.

Complete this slice and the separate scheduler owner wiring before one combined
affected regression. Cover all 12 observations, missing/file directory traversal,
unknown/external/other-role aliases, exact pins, original strict refusals, explicit
receipt/version selection, unchanged runner/report identity, deadline and failure
retention. Later actual execution uses a fresh, separately reserved attempt after
software verification. Build/custody/runtime/production acceptance remains separate.
