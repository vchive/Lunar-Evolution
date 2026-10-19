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

## Core-only continuation (2026-10-19)

After the zlib probe, a fresh build directory at
`/tmp/lunar-toolchains/build-core-noffi` was configured with the pinned Zig
compiler, the host-local musl zlib archive (`zlib-1.3.1`, SHA-256
`9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23`) and an
explicitly untrusted/absent libffi include and library prefix. The command only
requested CPython's `python` target; it did not claim that optional extension
discovery was closed. CPython still reported `_ctypes= yes` because the stock
configure path can discover the host `pkg-config`/libffi metadata even when the
requested musl prefix is empty. A full `make` must therefore remain blocked at
the `_ctypes` extension until a separately pinned musl libffi input is either
provided or the reviewed module manifest disables it.

The core `make -j8 python CFLAGS_NODIST=-Wno-error=date-time` target completed
and produced a 26,673,400-byte ELF with SHA-256
`bfc4dbffc882d6f69540823cf32eef3994585c74d994b26677c3e61e17467a69`. Read-only
inspection observed ELF64, little-endian, `ET_EXEC`, x86-64, nine program
headers, no `PT_INTERP`, and no dynamic section. These are detached format
observations only; the image still contains stock getpath/frozen tables and has
not passed the Feature189 installation descriptor or static-link closure gate.

Running that binary in an empty environment failed before user code with:

```text
Fatal Python error: Failed to import encodings module
Python runtime state: core initialized
ModuleNotFoundError: No module named 'encodings'
```

This preserves the runtime failure as evidence. It confirms that a successful
stock static link is not a sealed runtime. The next implementation slice remains
the same-source finite frozen inventory, isolated `PyConfig`/getpath binding,
loader-negative cases and native lifecycle receipt. No build, runtime or
production-admission claim is promoted by this continuation.

The detached observation can be retained in the bounded
[`build-probe-receipt.md`](build-probe-receipt.md) wire. That parser keeps the
core-link result, optional-module closure and startup failure as separate
fields and rejects every capability claim; it is an evidence transport, not an
acceptance shortcut.

The archive PAX compatibility change is committed separately from this probe;
the strict default remains unchanged for inert and untrusted inputs.
