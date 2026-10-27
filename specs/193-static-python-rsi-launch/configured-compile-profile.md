# Fixed compiler compatibility with the observed configuration

Status: minimal SDD continuation, 2026-10-28. Software changes are prepared for
the consolidated regression; this is not acceptance of the configured header,
build, support libraries or runtime.

## Problem and source evidence

The native configuration observation for CPython 3.13.12 / Zig 0.16 /
`x86_64-linux-musl` produced `pyconfig.h` with `WITH_MIMALLOC=1`. Its original
58,752-byte header has SHA256
`c300e7c60168ea35f2761aa4b1876bd0d9f306f1236297dc5a6e767126d862f3`.
The original 134,915-byte Makefile has SHA256
`7c43f3acb7bbb1de20d503596a12c6d709f2c9261663d8acd3d3d8b65240fe28`.
These identify observations, not independently accepted configuration inputs.

Makefile line 106 includes `Include/internal/mimalloc` in
`PY_CFLAGS_NODIST`. The fixed compiler vector previously included only
`Include` and `Include/internal`, so it could not resolve these actual source
include forms:

- `Objects/obmalloc.c:14-24`, under `WITH_MIMALLOC`, includes
  `pycore_mimalloc.h`, `mimalloc/static.c` and `mimalloc/internal.h`.
- `Objects/mimalloc/static.c:16-17` includes `mimalloc.h` and
  `mimalloc/internal.h`; both resolve from `Include/internal/mimalloc`.
- `Include/internal/pycore_mimalloc.h:43-45` includes the reviewed mimalloc
  header subtree. Its existing internal include root remains necessary.

These exact originals match the retained CPython source inventory
`3dd46b11d31635a940a31db104ddc9b4aa6cbeb8a03a6f315985beaf7339e190`:

| Source | Bytes | SHA256 |
| --- | ---: | --- |
| `Objects/obmalloc.c` | 109977 | `e9986a253c03c7057deaea4a9a9b828fd1f50a8c11a755f154cc12368d3bf7f0` |
| `Objects/mimalloc/static.c` | 1278 | `9cda0f1e5c182c11f1cd568ea78b4fe78be32108e9a3d4fa998727408baf1240` |
| `Include/internal/pycore_mimalloc.h` | 1637 | `22dddb17cf4bcd34949b44eeabf93ca8bfb435b9d5aa0da1b2f212ef5d0e3cae` |

The inventory already contains 36 mimalloc-related ordinary files. The reviewed
shared graph already compiles `Objects/obmalloc.o`, and actual Makefile lines
2004-2021 associate the included mimalloc implementation with that single object.
No additional mimalloc translation unit or object is required by this repair.

The observed `BASECFLAGS` at Makefile line 86 also supplies
`-fno-strict-overflow`. Its actual nondist flags at line 92 include
`-fvisibility=hidden` and `-Werror=implicit-function-declaration`. These affect
overflow optimization, symbol visibility or acceptance of undeclared functions;
the existing `-std=c11` and `-fno-strict-aliasing` do not replace them.

## Requirements and implementation boundary

1. Every generated compilation of the configuration probe, shared/native units,
   same-source freezer units and target units uses the fixed
   `-I @source-dir/Include/internal/mimalloc` root and those three exact flags.
2. The finite dependency-command grammar accepts only those three additional
   flags. Arbitrary Makefile options, response files, plugins, ambient search
   roots or caller-proposed flags do not become accepted.
3. Preserve the configuration header and its separately supplied expected pin,
   existing pymalloc/mimalloc selection, fixed source/object graph, role defines,
   explicit getbuildinfo constants, and same-source C freezer.
4. Preserve input directory availability validation. A missing declared mimalloc
   subtree is refused before execution. Synthetic tests explicitly declare a
   synthetic member in that subtree; this does not authenticate a real header.
5. Keep all configured-closure, custody, installation and production claims false.

This is a source-owned minimum semantic compiler profile, not a general Makefile
importer. Warning-only flags and source-local include differences are not blindly
copied. Actual compiler depfiles, the complete link closure and final ELF still
need their original validation. In particular this repair does not add implicit
`-ldl`, infer musl archive coverage, accept a support bundle or modify its layout.

## Consolidated validation

The recipe tests must cover all compilation roles, unchanged single-object
mimalloc aggregation, unchanged independently pinned header bytes, and refusal
when the declared mimalloc include subtree is absent. The existing actual
concrete-generator command-graph test checks compatibility with the finite
consumer. Existing refused compiler-option tests must remain in the affected
batch, along with concrete, compiler/linker dependency, configuration generation,
socket/subprocess profile and Zig support tests.

Run these affected tests once after the parallel compatibility changes are
integrated, with Ruff, compileall and `git diff --check`. No compile or target
execution is established by synthetic recipe tests; real configured build and
runtime acceptance remain separate gates.
