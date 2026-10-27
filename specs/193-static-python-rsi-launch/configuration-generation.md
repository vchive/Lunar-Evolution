# Native CPython configuration generation

This explicit continuation implements the missing operation that actually invokes
CPython configure and retains its generated header. It is an ordinary trusted
native build preparation. It does not replace the inert configure-plan emitter,
its exit-78 entry points, the mock build driver, independent configuration review,
or accepted isolated build/runtime gates.

## Fixed execution and inputs

`run_cpython_configuration` accepts original CPython, complete Zig and helper
roots, independently pinned canonical source/helper inventories, the independently
fixed complete Zig manifest, a fresh workspace and one absolute deadline. It
copies only pinned ordinary files through the existing no-follow FD observer,
then compares original and copied inputs before and after the sole configure
process. Source trees with prior `pyconfig.h`, `Makefile`, `config.log` or
`config.status` are refused. Configure itself must match the original 893,475-byte
CPython 3.13.12 member with SHA256
`0495fd50c8441437de8df5bd681b94bda00492ad3cf0d0db07f52f928dc12f20`.

The helper prefix explicitly requires regular executable copies named `bin/sh`,
`bin/python3.13`, `bin/sed`, `bin/grep`, `bin/expr`, `bin/basename`, `bin/dirname`,
`bin/mkdir`, `bin/cat`, `bin/rm`, `bin/ln`, `bin/tr`, `bin/cut`, `bin/awk`, `bin/sort`,
`bin/uniq`, `bin/wc`, `bin/uname`, `bin/chmod`, `bin/mv`, `bin/cp`, `bin/touch`,
`bin/readlink`, `bin/head`, `bin/tail`, `bin/install`, `bin/true`, `bin/false`,
`bin/printf`, `bin/ls`, `bin/find`, `bin/readelf` and `bin/diff`. The pinned configure
uses diff to validate non-GNU grep/sed implementations. Additional runtime data,
Python standard-library and shared-library files can be independently pinned
under that prefix. Other bin executables and any make/gmake file are refused.
The helper inventory is bounded to 16,384 records / 1 GiB. These are explicitly
supplied tools, not automatic host discovery or a host Python fallback.

Only the pinned shell is invoked directly, with the pinned configure script.
Fixed argv selects GNU build / musl host x86_64, disabled shared/test modules,
ensurepip and IPv6, computed gotos and pymalloc. CC/AR/RANLIB are fixed shell
wrappers around pinned Zig cc/ar/ar-s. The resource root is fixed through
`ZIG_LIB_DIR`, with local caches; the invalid `zig cc --zig-lib-dir` spelling is
never emitted. No ambient environment is inherited. PATH names only the helper
prefix, CXX and pkg-config are explicitly false, and Python uses only the supplied
prefix with user-site disabled. The fixed config.site has exactly the existing
three feature-disable policies; no unknown feature answer is invented.

The runner stages the retained `Modules/Setup.local` policy, invokes configure
once through the original bounded process/log/deadline mechanism, then snapshots
`pyconfig.h`, `Makefile`, `Makefile.pre`, `config.log`, `config.status`,
`Modules/Setup.bootstrap`, `Modules/Setup.stdlib`, and `Modules/config.c` through
original FD readback. It returns actual header/Makefile bytes and records their
sizes/digests. Failed attempts retain their first process logs and observation;
the original workspace cannot be reused. No retry is implemented.

## What remains unaccepted

The runner never invokes make, stock regeneration or any freezer. The independently
pinned configure source itself checks build Python's matching major/minor version
(lines 3690–3723). Its stock cross-freezer substitutions at 3740–3747 are retained
in Makefile and must not become the later Lunar freezer route. Configuration
probes are upstream behavior: the runner does not claim to have observed every
subprocess or all target execution.

Native helper binaries may use the host loader and libraries. Hashing ordinary
copies does not establish complete helper/driver implicit inputs, immutable
custody, kernel isolation or independent source authenticity. Those capabilities
remain false. A copied Python prefix must actually contain all required runtime
files; no missing library is supplied from another interpreter by this runner.
The explicit helper list is an execution contract; it is not a claim that a real
configure has already completed with those tools.

Generated `pyconfig.h` is an observation, not a reviewed configuration. Before the
existing concrete recipe consumes it, the caller must independently review/pin
the bytes and audit Makefile's source/header/role flags, replacement objects,
optional module discovery, library and static-link closure. The original recipe
continues to require `configuration_header` plus a separate expected digest.
The runner does not self-adopt its observation digest as that external pin.
Production admission and online publication remain false.

## Validation boundary

Focused tests use an actual inert shell process and explicitly synthetic configure,
Zig and helper pins. They cover returned original bytes, existing concrete-recipe
consumption using a separate fixed test pin, clean environment and fixed dispatch,
first-failure retention, fresh-workspace/control gates, helper/source/pin refusal.
Controls are also exercised while an original inert shell is actually running,
including its termination/reap and preservation of the original refusal reason.
They do not execute CPython configure, a compiler, a host Python or a solver.
No focused tests or real configure case were executed by this development slice;
it is delivered as an independent patch for the root's later regression batch.
