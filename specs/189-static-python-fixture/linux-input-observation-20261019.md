# Linux input observation — 2026-10-19

This record captures the first real archive and toolchain input run for
Feature189/193 on `5090gpu` (`worker01`). It is an input and provenance
observation only. It does not enable `production_admission`, publish an image,
or claim a configured build, sealed runtime, solver, evaluator, or campaign.

## Acquired bytes

The worker acquired the following archives and checked the repository profile
size and SHA-256 before extraction:

| Input | Size | SHA-256 | Archive observation |
| --- | ---: | --- | --- |
| CPython 3.13.12 | 22,926,488 | `2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593` | 5,245 members; 108,687,660 file bytes; manifest `27c37b470ee41f0efd765e4a5d2d8617ee462481dadd8563d3efa1d6abaf4c95` |
| Zig 0.16.0 Linux x86_64 | 55,478,392 | `70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00` | 20,832 members; 357,913,169 file bytes; manifest `b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90` |

The CPython source-tree projection was independently pinned as
`f7e8e480b96c4fe11bf1f0b0e5543377f9e4017c635bf7dca39175819de7e16f` over
4,837 regular files and 108,687,660 bytes. Snapshot-bound staging applied the
reviewed source patch set and returned staging digest
`5429922dac3a8c82783d9ff9c25843bd9d2a5ffbff6e19d01f5996f6cedb53ba`.
The staged result correctly retains `release_verified=false` and
`source_execution_performed=false`.

The worker's durable musl prefix is
`/home/qinzhiqing/vchive/toolchains/musl-1.2.5`. Zig 0.16.0 and the two large
archives are under `/tmp/lunar-toolchains` because the user's 35,157 MiB home
quota is already exhausted; the full installation manifest is
`/home/qinzhiqing/vchive/toolchains/INSTALL-MANIFEST-20261019.md`. Both Zig and
the local musl wrapper compiled a small `x86_64-linux-musl` static probe. The
probe was not used as a Lunar runtime image.

## Boundary and remaining gates

- Signature verification was not performed. The archive hashes establish byte
  identity against the frozen profile, not release authenticity.
- The source observation and staging run did not configure or compile CPython,
  generate frozen headers, link the target image, or execute a sealed runtime.
- A cross configure probe reached normal CPython feature checks and stopped on
  unresolved cross-compilation cache values; it did not compile or run Python.
- The temporary `/tmp` paths are ephemeral. A durable acceptance record still
  needs retained source/toolchain bytes or independently archived receipts,
  signature material, build closure, ELF inspection, startup/lifecycle logs,
  and the dedicated Linux no-skip gate described in `tasks.md`.

No WebAgent, remote evaluator, external worker, solver campaign, or production
publication was run.
