# Concrete fixed-solver build recipe and full-toolchain execution v3

This continuation implements concrete compiler/freezer/archive/link commands and
source closure generation. Generation does not invoke an upstream function,
configure, a host Python, compiler, model or evaluator. It does not claim that an
installation or solver campaign has passed. The original source emitters keep
their exit-78 behavior and the controlled mock driver remains unchanged.

## Concrete command generation

`tools.static_python_rsi_fixture.concrete_recipe.prepare_cpython_build_recipe`
consumes the original fixed `RSIProfilePreparation`, an independently pinned
canonical complete staged source inventory, the independently pinned complete
Zig archive manifest, explicit reviewed `pyconfig.h` bytes with their independent
pin, and an optional new `FixedRuntimeClosure`. It returns immutable recipe
bytes, the finite additional/overlaid source bytes that the caller must stage in
a **new** source root, and a source-only build manifest. It writes nothing.

The source inventory uses sorted `path,size,sha256,executable` records with
canonical ASCII JSON plus LF. The configuration header is never inferred from a
host interpreter, previous failed stock build, ambient headers or an environment
variable. The original source/custody APIs remain responsible for the full
reviewed patched CPython tree and installation-owned inputs. Their independent
pins are not replaced by a freshly observed output digest.

The concrete four-stage graph is:

1. `configure`: Zig compiles a fixed C probe against the independently supplied
   configured header. Static assertions require Linux/x86-64, 64-bit pointers,
   CPython 3.13.12, no shared Python and no dynamic loader. The Shinka probe also
   checks SQLite's serialization version/API and refuses extension-loading
   enablement. This is **not** an Autoconf execution or proof of all configuration
   answers. Obtaining/auditing a complete matching configured header remains an
   explicit real-build input obligation.
2. `freeze`: compile all original 162 shared translation units and two original
   freezer units, plus declared native closure units; statically link
   `Programs/_freeze_module.c` from that same source with the empty frozen-table
   implementation; invoke that generated executable with each exact generator
   ID, independently pinned source and create-only header destination. The
   original nine logical jobs remain present. A fixed solver version adds its
   finite transitive modules; it never calls `_freeze_module.py`, stock make or
   an ambient Python. No placeholder marshalled bytecode/header is generated.
3. `compile`: compile the four original target-role sources, using the original
   launcher/profile/getpath and the selected finite frozen table. Quoted
   `Python/stdlib_module_names.h` is overlaid at its actual CPython source path,
   so the build does not depend on ineffective include-path precedence.
4. `link`: deterministic `zig ar rcsD` creates the exact shared/native archive,
   then Zig statically links the original target objects and that archive with
   musl/libm/pthread. All Zig libc, CRT, compiler-support and header inputs remain
   present in the full toolchain snapshot. Objects, headers, archive and target
   all use the existing per-command observation and retained failure mechanism.

Role compiler flags, deterministic getbuildinfo constants, target
`x86_64-linux-musl` and archive/link command vectors are emitted explicitly. The
compiler, archiver and linker all select the pinned `zig` executable; there is
no shell, make, configure helper or host compiler/interpreter fallback.

`runtime_closure=None` produces the explicitly labeled `marker-fixture` image.
It is never represented as a working OpenEvolve/Shinka producer. Passing a fixed
solver closure produces an actual fixed-solver dispatch entrypoint described
below. Neither mode automatically accepts a resulting image.

## Fixed-solver source/native closure

`prepare_fixed_runtime_closure` consumes caller-provided complete CPython source
bytes plus an independent canonical inventory pin, exactly the prepared files
and fixed manifest from the OpenEvolve or Shinka source preparer, and for Shinka
an explicitly pinned SQLite amalgamation (`sqlite3.c`, `sqlite3.h`). No project
source is imported. Actual prepared source manifests remain pinned to
OpenEvolve `03266224…` and Shinka `5a6e7161…`; licenses and every module are checked.

The implementation resolves literal absolute/relative imports recursively,
package initializers and the original bootstrap set, with a 256-module bound.
The finite CPython runtime aliases `collections.abc -> _collections_abc` and
Linux `os.path -> posixpath` select the actual source module while retaining the
parent initializer that registers `sys.modules`. No alias shim/source is
fabricated, and a source file masquerading at either alias path is refused.
`os.py`'s single `_names = sys.builtin_module_names` binding selects its POSIX
branch from the declared builtin roster; an unknown/rebound `_names` does not
grant branch pruning. Its later top-level `if name == 'nt'` diagnostic branch
is excluded only when the original POSIX/NT branches contain the only two
module-level `name` assignments and establish `name = 'posix'` for this profile.
Rebound globals or function-local conditions do not inherit that exclusion.
Observed aliases appear explicitly in the closure wire.
The finite interpreter-provided set separately records `__main__`: original
`Python/pylifecycle.c` calls `add_main_module` during `Py_InitializeFromConfig`
main initialization and creates it with `PyImport_AddModuleObject`. The original
fixed profile requires `_init_main = 1`. Its source identity and creation phase
are retained; no `__main__.py` shim, frozen record or nonexistent `PyInit` entry
is fabricated. Missing/changed lifecycle evidence or a fake module source refuses.
One narrowly reviewed call guard is specific to the official 3.13.12
`Lib/platform.py` SHA-256
`75fe9b94662e55b91e19602bb75e6ca6132f7a53fb22844fc44a507a639127e1`.
Its private `_java_getprop` imports `java.lang`, but its sole caller `java_ver`
first attempts the same import and immediately returns on `ImportError`.
The full source pin binds that exact guard and absence of aliases, rebinding,
other callers or top-level calls. Any byte change refuses this exception, and
literal external helper references in selected modules also refuse. The wire
records this finite guard, source identity and call count. This is not a general
callgraph solver; dynamic reflection remains explicitly unverified.
It resolves explicit Linux/posix platform branches and permits listed absent
accelerators only in ImportError-guarded imports. An unresolved required import,
unguarded absent native module or missing source refuses before any build.
Dynamic imports and platform-dependent runtime behavior remain explicitly
unverified; AST reachability alone is not runtime closure acceptance.

The generator emits a new finite builtin table, frozen table, stdlib metadata,
real pending freezer jobs and complete native C-unit records. SHA-256 uses the
CPython `_sha2` implementation and its reviewed HACL source, with no ambient
OpenSSL dependency. Other explicit units cover the selected standard-library
needs (regular expressions, JSON, collections, selectors, math, typing, datetime
and related helpers). Function-local inspection/diagnostic imports also require
explicit `_opcode`, `_suggestions` and `_tracemalloc` C units and initializer
entries. These are native modules, not guarded-absence exceptions; the original
core already includes `Python/tracemalloc.c`. External socket/SSL SDK routes are
not introduced.

Shinka adds the nine CPython `_sqlite3` translation units and the separately
pinned SQLite amalgamation, forces serialization support and omits SQLite
extension loading. `sqlite3` and its Python helpers are frozen. A system
`libsqlite3.so`, host interpreter extension or unreviewed wheel cannot fill this
source role. SQLite source provenance/license review is still required before
real build acceptance; this code does not invent a new trusted archive pin.

The new frozen `_lunar_static_main._rsi_launch` validates the original marker
syntax and calls **the selected** `openevolve.lunar_fixed.main` or
`shinka.lunar_fixed.main` with the existing marker/digest vector. It does not call
the old baseline encoder. The original native host still owns marker-to-grant
binding, destination, credentials, requests, deadline, publication and recovery.
The solver profile adds no selectable entrypoint or new input grant.

The new `lunar-fixed-python-runtime-source-closure-v1` and concrete recipe
manifest are separate source-profile contracts. They are not implicitly
accepted by legacy F01/F02 nine-header/builtin descriptors. Later versioned
installation/ELF/startup observation and production composition must bind the
actual expanded inventory and original owner/lifecycle evidence.

## Explicit v3 mechanism and independent bounds

The original `run_pinned_build` continues to accept only v1/v2 with their original
1 MiB recipe, 16,384 records per role, 256 commands/outputs per stage, 512 overall
commands, 256 arguments and original reference grammar. No old budget changes.

`run_pinned_build_v3` is a separate opt-in entrypoint for
`lunar-static-python-pinned-execution-recipe-v3`. V3 has independent fixed limits:
8 MiB canonical recipe; 32,768 input records per role; 512 commands per stage;
1,024 commands overall; 1,024 outputs per stage/group; 512 argv strings. The
original aggregate input byte limit (4 GiB), per-file bound, per-output 128 MiB
bound, log bound, fixed environment and original absolute deadline stay intact.
The larger finite graph accounts for compiling the real CPython/freezer plus
freezing the additional source closure; it does not extend a running budget.

The actual retained Zig archive manifest has independent size 3,926,082 and SHA
`b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90`.
Projection requires all **19,546** regular files totaling **357,913,169** bytes,
including the sole executable `zig`. It neither truncates this inventory to fit
v1/v2 nor silently selects only the compiler executable. The exact complete
manifest pin comes from the previous retained archive audit; generation does
not grant new custody or signature authority.

V3 adds explicit `@source-dir/path`, `@toolchain-dir/path`, `@work-dir/path`
references for compiler include and Zig-library arguments. A referenced input
directory must have declared snapshot descendants; a work directory must have
previously declared or current output descendants. Directories never grant
executable authority. Empty, noncanonical, forward and undeclared references
refuse. The runner resolves them inside its private snapshots/work tree.
Attempt-local Zig caches are fixed by the runner, never inherited or chosen by
the caller. These references are trusted build-tool semantics, not a new
subprocess sandbox or proof of every compiler file read.

## Final regression and acceptance boundary

New tests cover real command graph composition with synthetic manifests, exact
source/freezer pins, metadata/entrypoint overlays, complete-inventory retention,
old/new wire bounds, finite import/native closure, SQLite source/serialization,
explicit directory references and the original inert helper through v3. They
execute no actual upstream functions or builds. Root owns the one concentrated
focused/static regression after all parallel sources freeze; author checks only
parse their own Python ASTs before that final run.

The retained real-source checks on 2026-10-27 do **not** prepare either complete
solver closure yet. OpenEvolve attempt 6 and Shinka attempt 1 both refuse
`unresolved_import: readline` using the same pinned, patched 3.13.12 source tree;
Shinka also verifies the independently pinned SQLite amalgamation inventory
`0e3ac7b881a8578c1fdf1f71666b7cf3216c5ff9d9eb7d53e3cd01f0a3d17965`.
The conservative whole-function scan reaches `pdb`, `code` and `cmd`, including
the unguarded `cmd.Cmd.complete` import. This identifies an unclosed static edge;
it does not establish that actual fixed-solver execution needs interactive
completion. No readline/ncurses dependency, fabricated source or blanket absent
import exception is added to make this check pass. Refining a defensible finite
runtime profile and real sealed execution remain separate required work.
The reports are retained under
`.lunar-evolution/validation/parallel-batch-20261027/integrated-source-folzw8an/`
as `real-source-closure-attempt6.json` and `real-shinka-source-closure-attempt1.json`.

Actual configured-header review, complete static build and input/output closure,
ELF/image custody, sealed startup and loader-negative acceptance, actual upstream
diff semantics and broker compatibility, original execution/cleanup observations,
unknown/reconcile/export/handoff, and the production CLI remain separately
required. KVM/isolated-host availability can block those executions, but it does
not substitute for the concrete command/source generation implemented here.
All source and process reports keep production admission and online publication
false until their own real acceptance succeeds.


## Finite imported-selftest and inspect CLI refinement

The literal closure scan excludes the imported-only demonstration/CLI main block
in exactly the official 3.13.12 `pickle`, `difflib`, `pickletools`, `heapq` and
`inspect` sources. Full independent source SHA-256 pins bind this finite exception. The
first three contain a private `_test` helper; `inspect` contains `_main`.
This finite module-to-helper mapping permits only the sole local Name reference
which is the helper's direct call inside that false main block, with no alias,
rebinding, other caller, decorator or arguments. Literal external `_test`/`_main`
helper attribute/string references or `from` helper/star imports in any selected
module refuse. `heapq` has only the main block and no private helper. Canonical imported module names
come from the existing frozen records; these sources are not selectable main
entrypoints. Their original source bytes are retained, with the specific excluded
source/call/guard evidence recorded under `excluded_imported_selftests`.

This is not arbitrary dead-code elimination or a complete callgraph proof.
Other module main blocks and all functional function bodies remain scanned;
dynamic reflection and runtime import closure remain unverified. No `readline`
absence exception, fabricated source or readline/ncurses dependency is added.

A retained source-only trial preceding the inspect CLI refinement removes the diagnostic
`pickle._test`/`difflib._test -> doctest -> pdb/cmd -> readline` route but does
**not** close either real solver source graph. OpenEvolve next refuses an
unguarded absent import while scanning `subprocess` reached from `os.popen`;
Shinka next refuses `_bz2` required by `bz2`. The trial executes no supplied
upstream Python, build, model or evaluator; runtime execution and production
admission remain false. The extra source pins do not supply the still-missing
reviewed target `pyconfig.h`, isolated build, sealed runtime or production CLI.


The `inspect` extension binds complete official `Lib/inspect.py` (128803 bytes,
SHA-256 `ea27c96e5b29fe29de8e3ee8840a50d6ff4b05f47cf911f4ee17cb0d4f953ca8`).
Its undecorated no-argument `_main` at line3412 has one Name Load, the sole call
at3471 inside the canonical main guard at3470. It imports `argparse`/`importlib`
for CLI object inspection. The original complete source is retained; only its
exact imported-only helper/main dependency scan is excluded. This can remove
the inspected `inspect._main -> argparse -> shutil -> bz2` diagnostic route
without adding `_bz2`, moving import failure or modeling transitive optional
initialization. A functional or otherwise required compression import still
refuses if its real native dependency is absent. Other possible routes remain
conservatively scanned, and no real-source closure success is claimed for this
extension before independent source-only verification. Build/runtime/production
acceptance and dynamic reflection remain unverified.


## Exact imported calendar CLI refinement

The finite imported-only mapping also includes official CPython 3.13.12
`calendar.main`, complete `Lib/calendar.py` (26077 bytes), SHA-256
`519c59b7a52e45f9c8056ed8cc8cede5be4bfa16d2179c1db1b01688ac1935b3`.
Its sole helper definition at line 699 is exactly `main(args=None)`, with no
other arguments, annotations or decorators. Its sole Name reference is the
zero-argument direct call at line 813 inside the canonical false imported-main
guard at line 812. Only this exact helper/source may use that optional argv
signature. Original source bytes and functional bodies remain retained/scanned;
its CLI-only `argparse` import at line 700 is excluded with `args=None` evidence.

The common name `main` is never added to the global private-helper literal gate.
A separate finite calendar reference rule permits only the actually selected
full-source-pinned `_strptime` caller (34734 bytes, SHA-256
`42ace512e928d00bf6642f322d6ecae9112412f9b4d2d73ab89f8db3a79d0598`).
Its one unaliased `import calendar` at line 16 has exactly five module Name
loads, solely the public `day_abbr`, `day_name`, `month_abbr`, `month_name` and
`isleap` attributes. Its caller source/import/public-member proof is retained
under `guarded_call_imports`. Other literal calendar imports, aliases, module
exports or module-name reflection refuse as unreviewed; there is no generic
alias analysis or automatic approval of other official callers. Unrelated
`main` functions/attributes/strings remain scanned normally.

This refines only the observed `_strptime -> calendar.main -> argparse` source
route. It adds no native/absent module, transitive optional exception or runtime
capability. Other required import edges continue to refuse; source-graph success
needs a fresh independent source-only check. Dynamic reflection, build/runtime,
production admission and CLI acceptance remain unverified.
