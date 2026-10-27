# Fixed Zig cc resource-root correction

The first real support-seed software validation failed before its first object
was generated. The pinned Zig 0.16 executable returned exit 1 with the original
45-byte diagnostic `error: Unknown Clang option: '--zig-lib-dir'`. The concrete
CPython compiler/linker recipes and the new support seed had passed that Zig
compiler-driver option after `cc`; inert test compilers had accepted it and
therefore concealed the incompatibility. This was a software invocation defect,
not a deadline or machine-isolation failure.

## Corrected executable boundary

New recipes emit the Clang-compatible `zig cc` target vector without that option.
The original v3 runner constructs `ZIG_LIB_DIR` itself as the complete pinned
`workspace/toolchain/lib` snapshot. The Podman path and original-observation
validator construct exactly `/toolchain/lib`. Neither inherits the ambient value
nor permits a caller to choose this environment key. Original v1/v2 environment
behavior stays unchanged; no caller environment allowlist or budget is enlarged.

The finite original dependency-consumer graph still requires actual declared
non-executable toolchain inventory descendants below `lib/` before a compiler
or linker command can dispatch. It rejects the previously emitted illegal
option. Link/compiler capture plans describe the corrected exact command bytes;
old recipes are never silently rewritten while retaining their original pins.
The explicit-support successor locates target/object positions from the reviewed
`-o` option, so removal of the invalid pair cannot shift support CRT placement.

The pinned `lib/std/zig.zig` source identifies `ZIG_LIB_DIR` in its list of all
environment variables Zig can inspect (lines 742–747). Its 44,987 bytes have
SHA-256 `5445596331ad810fc60057fce5555477e9317441fb36f69c632f37f0d1da0824`,
matching the independent full extraction manifest. Separate `zig --help` and
`zig cc --help` calls exited zero and performed no compilation. Help/source
reading motivates this fix; it does not replace the required real corrected
compile/link validation.

## Preserved failed case

The failed single-attempt case had a 180-second absolute product budget and
zero retry. It exited in 13.710559043 seconds (outer wrapper 13.969029120), before
any completed stage, seed ELF, linker depfile or support cache output. The seed
was never executed. All 34 retained regular evidence files matched size/SHA-256;
2,576 copied source files matched before/after and 240 loaded Lunar/tools module
origins matched both times. The source copy is a working-tree byte snapshot,
not a Git-index tree or clean commit. It deliberately omitted `.env.example`
and preceded four later runtime-observation additions; it validates none of
that runtime work. No `.env` or credential was read.

Originals and verification are retained in the ignored validation directory
`parallel-batch-20261027/real-zig-support-once-6nigajy1/`. The help output and
source-file verification are under its separate `help-originals/`. The old
failed product source is not re-dispatched. Corrected software must be frozen
and reviewed before a new single-attempt case; the fixed support-name set and
original budget remain unchanged.

Native inert fixtures now read the executor-supplied `ZIG_LIB_DIR` instead of
accepting an invented argv option. Focused checks cover the actual dispatch
value, ambient/caller override refusal, pinned-resource absence and forbidden
option rejection. Podman environment construction and its observation validator
use the same fixed function. These tests remain provider-free software checks.

No immutable-generation, configured-header, complete CPython build, full driver
closure, runtime, production-admission or publication gate is closed by this
correction. In particular, the exact real generated support-name set remains
unobserved until the corrected seed actually reaches its original link stage.
