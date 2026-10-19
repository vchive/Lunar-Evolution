# Real-input build probe (not acceptance)

This note records the first real-input smoke probe on the isolated Linux host
`5090gpu` on 2026-10-19. It is an engineering reproduction record, not a
production acceptance receipt. The probe never ran a solver, evaluator,
producer campaign, or remote worker.

## Inputs and isolation

The pinned CPython 3.13.12 archive was acquired into
`/tmp/lunar-toolchains/sources/Python-3.13.12.tar.xz` and the pinned Zig
0.16.0 archive into
`/tmp/lunar-toolchains/sources/zig-x86_64-linux-0.16.0.tar.xz`. Their sizes and
SHA-256 values are the fixed values in `tools/static_python_fixture/profile.py`.
The host-local musl prefix is
`/home/qinzhiqing/vchive/toolchains/musl-1.2.5`; no system package was
installed. The home filesystem quota is full, so the CPython source staging and
build trees are intentionally under `/tmp` and are ephemeral.

The archive snapshot gate passed the fixed size and SHA-256. The source archive
contains twelve per-file PAX `path` records for long names. The explicit
`allow_bounded_pax=True` path accepts those records under a 64 KiB, one-key
`path` policy. The complete observation had 5,245 members and 108,687,660
regular-file bytes. The smoke run used the observed manifest digest as its
local pin; that digest is not an independently retained release pin and must
not be treated as production evidence.

## Source staging

The bounded observer and source projection produced the three reviewed
preimages and postimages. `stage_archive_sources` then created a new source
tree containing 115 MiB of CPython files. The staging result retained
`build_performed=false`, `runtime_execution_performed=false`, and
`production_admission=false`. This proves snapshot-bound local staging only.

## Configure and minimal static build

The following host-only cross configuration was sufficient to generate a
Makefile with Zig's bundled musl target:

```sh
export CONFIG_SITE=/tmp/lunar-toolchains/cross.site
export ZIG_GLOBAL_CACHE_DIR=/tmp/lunar-toolchains/zig-cache
export ZIG_LOCAL_CACHE_DIR=/tmp/lunar-toolchains/zig-cache-local
sh /tmp/lunar-toolchains/cpython-staged/Python-3.13.12/configure \
  --prefix=/tmp/lunar-toolchains/pyhome \
  --build=x86_64-linux-gnu --host=x86_64-linux-musl \
  --with-build-python=/home/qinzhiqing/software/miniforge/bin/python \
  --without-ensurepip --disable-shared --disable-ipv6 \
  CC=/tmp/lunar-toolchains/zig-cc \
  AR=/tmp/lunar-toolchains/zig-ar RANLIB=true
```

The site file supplies only cross-compilation facts (`ac_cv_file__dev_ptmx`,
`ac_cv_file__dev_ptc`, and the non-buggy `getaddrinfo` result). `make
python CFLAGS_NODIST=-Wno-error=date-time` produced a 26 MiB statically linked
x86-64 ELF. This is a stock CPython build artifact and is not the sealed
Lunar runtime: it has no reviewed frozen-header closure, launch binding,
startup receipt, loader proof, or input/result handoff.

## Blockers found

The full `make` target stops at the optional zlib extension because the isolated
musl environment has no `zlib.h`. Installing a host glibc zlib development
package would be an invalid cross-build shortcut. The real build path needs
reviewed musl-compatible dependency inputs or an explicit minimal module set.

The stock `python` binary also refuses startup before importing `encodings`
when run from the cross build tree. Its generated getpath/module search path is
not the sealed `PyConfig` path required by Feature189. A successful stock
binary therefore cannot close the runtime gate. The next implementation slice
must provide the reviewed isolated `PyConfig`, finite frozen modules, loader
closure, and startup receipt before any production admission claim.

The archive PAX compatibility change is committed separately from this probe;
the strict default remains unchanged for inert and untrusted inputs.
