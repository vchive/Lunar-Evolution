# Same-command native support export

This explicit Feature 193 successor exports the fixed Zig seed link's support
cache observations before its command container exits. It reuses the original
four-stage pinned build runner. It adds neither another runner nor a shell,
ambient interpreter, automatic support selection or a production runtime.

## Execution contract

`assets/native_support_export.c` is a source-owned input whose bytes are checked
against a fixed expected source SHA256 in the Python composition. This pin is
not independent toolchain or custody approval. The original `configure` stage
compiles this helper as a static Linux x86-64 executable. Its executable output
must pass the existing original runner's output readback and subsequent prior
executable acquisition before the `link` stage may execute it. `freeze` compiles
the fixed probe, and `compile` compiles the existing fixed main and division
sources. No generated seed is executed.

The helper has exactly nine argv items, including argv[0]:

```text
helper zig global-cache local-cache seed bundle probe.o main.o div.o
```

All supplied paths are explicit absolute paths, have bounded printable ASCII
components without whitespace, backslashes, colons, empty components, `.` or
`..`, and have no ancestor/descendant overlap with another argument. Every
parent lookup uses directory FDs and `O_NOFOLLOW`. Input image/object leaves
must be regular files. Existing output names and even empty existing cache
roots are refused. The helper claims the seed and bundle with `O_EXCL` and
creates both original cache roots with mode 0700. Failed partial outputs are
retained; there is no overwrite, implicit retry or cleanup that erases failure.

The production composition selects only the original `podman-snapshots-v1`
backend, with fixed `/tmp/zig-global/native-support` and
`/tmp/zig-local/native-support` arguments. The original image supplies the two
cache parent directories; both new child roots must still be absent. Existing
parent contents remain outside the new cache inventories. It has no
trusted-local production fallback. Direct helper unit fixtures may provide
explicit fresh temporary cache paths; they are a different acceptance scope.

The existing custody runner's graph preflight remains strict for its default
dependency-capture profile. This new graph requires explicit
`command_profile="native-support-export-v1"`, only with recipe v3 and the fixed
snapshot backend. Its separate graph validator compares the helper source,
original three seed sources, finite environment and every stage/argv/output
against the source-owned expected graph. There is no fallback after the default
validator refuses a graph. The link command declares its two actual outputs,
seed and binary bundle; it does not fabricate a captured linker depfile. The
original custody/report format and all-false driver-closure boundary remain.

The helper forks exactly one fixed command:

```text
zig cc -target x86_64-linux-musl -static -o seed probe.o main.o div.o -lm -lpthread -lc
```

It supplies a finite child environment: C locale, UTC, source epoch zero,
`HOME=/nonexistent`, the two cache paths from argv, `TMPDIR` equal to the local
cache, and `ZIG_LIB_DIR` equal to the explicit Zig executable's parent plus
`/lib`. It reads no ambient environment to choose tools, flags, cache paths,
libraries or inputs. The child remains in the original runner's process group.
The original absolute deadline, interrupted state and cleanup owner cover both
linking and exporting. Waiting or scanning creates no renewed budget.

After the original Zig child exits zero, the seed must be a nonempty regular
executable no larger than 16 MiB. The existing consumer separately applies its
static ELF gate. In the same helper/container lifetime, two bounded complete
inventories cover both caches. Every directory and regular file is retained in
the inventory; links, FIFOs, devices and sockets are refused. A cache path is at
most 480 bytes. Both caches share 32,768 entries and 512 MiB of regular file
content; a single regular file is at most 128 MiB. All limits are fixed in the
pinned source, without production runtime overrides.

Each file hash is computed from a no-follow opened regular FD. Before/after FD
and named-entry comparisons bind device, inode, mode, link count, size, mtime and
ctime for that read. Directory/root identity and metadata are also checked.
The second sorted inventory must exactly match the first, including all file
hashes and directory records. These observations detect disagreement and do
not prove that no unobserved write occurred between observations.

All regular files with one of the following basenames are exported, preserving
their cache and complete relative path. Multiple `crt1.o` identities are kept;
none is implicitly preferred:

```text
crt1.o crti.o crtn.o libc.a libzigc.a libubsan_rt.a libcompiler_rt.a
```

A candidate must be nonempty and have no executable permission bits. Export
reopens the original cache path without following links and repeats its
identity/hash comparison while copying. The complete binary bundle, including
metadata and candidate bytes, is limited to 128 MiB, matching the existing
runner output-file limit. The helper fsyncs, makes the bundle mode 0400 and
reads its original held output FD back, comparing size, bytes hash and named
identity before success. The Python consumer separately validates the wire and
the original runner's output pins.

## Binary wire v1

All unsigned integers are big endian. There is no padding or trailing data.

| Field | Bytes | Meaning |
| --- | ---: | --- |
| magic | 8 | ASCII `LZSUP01` followed by LF |
| entry count | 4 | Total directory and regular file rows, at most 32,768 |
| candidate count | 4 | Number of candidate regular rows |
| global root | 5 | `present:u8=1`, complete `st_mode:u32=040700` |
| local root | 5 | Same fixed original root shape |

Rows follow in strict `(cache index, relative path ASCII bytes)` order. Cache
indices are global 0 and local 1. The root itself is represented by the header,
not a row. Every non-root parent directory must have its own directory row.

| Row field | Bytes | Meaning |
| --- | ---: | --- |
| cache index | 1 | 0 or 1 |
| kind | 1 | Directory 1 or regular file 2 |
| path length | 2 | 1 through 480 |
| mode | 4 | Complete original `st_mode`, including type and permission bits |
| size | 8 | Original regular size; zero for directories |
| digest | 32 | SHA256 of every regular file; all zero for directories |
| path | path length | Strict relative ASCII path |
| candidate content | size, when applicable | Present only for a regular row with one of the seven fixed basenames |

The consumer rejects invalid types/modes, bounds, paths, ordering, duplicates,
missing parents, counts, candidate sizes/hashes, truncation and trailing bytes.
It reconstructs the complete two-cache observations and all candidate bytes.
Detached parsing authenticates no generating tool or historical filesystem.

## Acceptance and retained boundaries

Focused coverage must include hand-authored positive/negative wires, the actual
pinned C helper compiled with the local C toolchain and an inert Zig substitute,
static source/recipe selection, no seed execution, multiple CRTs, path/type and
bound refusals, existing-output refusal and legacy API compatibility. All software
is completed before one centralized affected regression; no agent independently
runs a real compiler, Zig, solver or benchmark campaign during implementation.

A later original rootless acceptance run must retain the exact source,
recipe, toolchain, container, command outputs and original runner reports. Unit
fixtures or a successful native export do not establish immutable input custody,
complete implicit driver input closure, configuration approval, full CPython or
freezer/static ELF acceptance, sealed startup, installed ownership, producer or
production CLI acceptance. `immutable_generation_verified`,
`driver_inputs_verified`, `configured_closure_verified`, `installation_accepted`,
`support_selection_accepted`, `production_admission` and `online_publication`
remain false. Prior failed/unknown/skipped observations remain retained.

## Retained validation (2026-10-30)

Final source `5ea6210d` passed 496 unique cases in 14 complete files, including
83 native-export cases, with no failure, error or skip. Runtime was 9.228404
seconds including the wrapper; 2,758 source files and Git executable-bit
projections matched before and after. Static checks passed. The earlier 495-case
result belongs to its earlier source and is not counted again.

The initial real rootless run failed in 63.977149 seconds at create-only cache
acquisition because the original image already supplied both parent roots.
Its original report, stderr and 117 finite originals are retained. The final
source fixes this by selecting fixed fresh child roots. Its single real run
completed in 103.894995 seconds under the original 120-second deadline, with
zero retry: 6 candidates / 13,968,568 bytes. Static helper and seed validation,
actual report and output readback passed; no seed was executed. This is the
same-command export boundary, not full build or runtime admission. Evidence is
in primary ignored `validation/native-support-export-20261030/`.
