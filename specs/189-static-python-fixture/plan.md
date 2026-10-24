# Implementation plan — first single-image fixture

## Gates and partition

G0: Feature188 final-head raw audit/main merge4f8576d and Feature190 private
original executable-owner final-source run37802795693/main merge3a7782c are
complete. Their evidence does not complete Feature189 target acceptance.
G1: Freeze the installation source, patches, exact toolchain/musl profile, complete
recipe and generator provenance. No ambient compiler/libc or placeholder hash.
Use the frozen Feature190 private original target-owner binding/recovery proof
and complete its Feature189 target integration before claiming safe descriptor
cleanup; public numeric-FD observations alone do not prove foreign-FD reuse safety.
The separate candidate source/patch evidence package and its later build-consumer
boundary are specified in [`candidate-build-provenance.md`](candidate-build-provenance.md).
That design does not provide an immutable tree or prove build consumption; those
remain open G1 evidence/implementation obligations.
G2: Resolve the finite initialization/module inventory, build and inspect the exact
final image. Build/compiler/startup failures remain evidence, not success.
G3: Run the original native sealed-target fixture and independent final Linux audit.
Do not promote a build or portable parser check to runtime acceptance.

The independent Linux three-child serial regression passed once on exact
`49b4929c` at the original 600-second control; exact-head complete CI remains
required before PR186 merges. The measured, narrowly bounded cache work in
[`serial-regression-performance.md`](serial-regression-performance.md) preserves
fresh source/SQLite reads and all identity/history checks. Do not widen the
deadline or infer complete CI acceptance from that independent passing case.

The next setup component is specified in
[`toolchain-private-custody.md`](toolchain-private-custody.md). Its private
materializer creates every member from the same checked archive snapshot,
preserves exact modes and runs the existing complete observer at the actual
new root. It supplies neither immutable custody nor compiler consumption.
The unique exact-a9b75116 real-Zig data-only replay passes in 11.70 seconds
including the remote independent walk and source-after validation under the
original 120-second budget; all source/module/transfer pins are independently
audited. The copied tree is not locally re-walked. Linux focused54 also passes.
The tested single-layer remount and nested-bwrap routes are unsupported under
5090gpu's current AppArmor policy; ordinary host copying is not a fallback for
that enforcement gate. Keep configured closure, helper/cache bindings, actual
read-only enforcement, source relocation, build and runtime acceptance open.

The bounded descriptor parser/external-pin checks already live in
`src/lunar_evolution/static_python_installation.py`. Candidate installation-owned
launcher, initialization profile, fixed getpath, pipe builtin and frozen-main
sources live under `tools/static_python_fixture/assets/`; the recipe emitter is
`tools/static_python_fixture/recipe.py`. These are source-only candidate assets:
its emitted build scripts still exit78 before actual configure/freezer/compiler/
linker work.
Bind and validate these existing assets in one reviewed build recipe, then add
the actual Linux sealed-target ownership/lifecycle harness. Neither the real
static build nor that target fixture is implemented by the candidate emission
or portable parser tests. Avoid unrelated native-v2 changes.

## Fixed build recipe

Use a separately pinned Linux x86_64 musl compiler/sysroot profile. Pin compiler,
linker/binutils, headers, libc/libm and any compiler support archives and their
sources. Build a non-PIE fully static ET_EXEC target for the first profile; final
compiler-supported flags and configure cache values are part of the recipe,
not inferred from a successful `--disable-shared` configure.

The offline source-preparation slice is specified in `source-preparation.md`.
It supplies pure fixed loader patches and generated finite C tables plus their
digests. The emitted direct-compile/link source vector is an unapplied plan;
stock optional-module discovery, real frozen headers and final linking remain
open. The recipe uses the actual configure option `--disable-shared` and still
exits78 before configure/make/freezer work, including with explicit execution
opt-in; no unresolved stock make closure is executed.

The next pure preparation contract is `build-inputs.md`. Its reviewed shared162
candidate has146 core-role inputs and16 builtin additions, with separate freezer
and target extras and source/postimage origins. The freezer retains its own
empty frozen tables and excludes stock/target frozen objects. All nine intended
headers stage adjacent to the finite table under
`generated-sources/Python/frozen_modules/`. Configured object substitutions,
compiler flags, optional discovery and static-library/CRT inputs remain open;
the fixed candidate is not an observed configure or complete link closure.

The later [`configure-candidate.md`](configure-candidate.md) slice retains
concrete candidate cache/module/environment assets and corrects the proposed
cross-build argv without changing the old reviewed input asset. It still
enables no configuration or compiler entry point. The actual Zig bundled
source layout and upstream cross defaults are recorded separately in
[`toolchain-layout-audit-20261023.md`](toolchain-layout-audit-20261023.md).

The next bounded observation slice in
[`toolchain-observation.md`](toolchain-observation.md) reuses the full existing
Zig extraction manifest and its independent pin, retaining a separate canonical
record of snapshot identity, complete counts and honest observation limits.
It neither traverses an extracted tree nor changes source-readiness/admission.
Concrete extracted-tree custody and build tools still require separate evidence.

The following [`toolchain-tree-observation.md`](toolchain-tree-observation.md)
slice compares a concrete directory with the complete independently pinned
manifest through held no-follow directory descriptors. It reuses the existing
manifest wire and applicable FD helpers, checks full content/modes/inventories
and late changes, and retains a separate small observation record. The walk is
sequential; it closes its descriptors before returning and cannot prove immutable
custody or future compiler consumption. Concrete wrapper/helper/build-Python and
cache/environment bindings remain prerequisites to configure-only execution.

Disable optional extension autodiscovery and supply an explicit static/disabled
module manifest. Review generated pyconfig.h, Modules/Setup output, inittab,
core sources, separate embedded startup arrays, object/archive link map and
symbol/loader dispositions. Freeze Py_DEBUG=0, Py_GIL_DISABLED=0 and disable
experimental JIT/profile variants for this first release ABI. Exclude
unsupported ctypes/FFI, dynamic extension loaders and optional package libraries.
Reject unexpected static dependencies as well as PT_INTERP / DT_NEEDED. A link
map/ELF check alone is not a CPython identity or code-origin proof.
Require a final image size <=134217728 bytes (128 MiB), using the existing
`producer_launcher.MAX_OUTPUT_BYTES` / `linux_executable_binding` ceiling. An
oversized image refuses; do not widen the ceiling or insert a temporary bypass.

Generate frozen code with installation build tools from the same pinned CPython
3.13.12 source/patch profile. Record the `_freeze_module`/generator executable,
compiler recipe, host architecture, Python version/opcode/marshal provenance,
each module's source and generated bytes, and complete frozen/inittab/alias tables.
A host CI Python of another version is not an implicit freezing substitute.
Do not invent a reproducible artifact digest before bytes exist; publish the
actual final descriptor only after all inputs/tables/image fields are known.

## C initialization profile

Preinitialize explicitly with `PyPreConfig_InitIsolatedConfig`: isolated=1,
use_environment=0, parse_argv=0, utf8_mode=1, configure_locale=0,
coerce_c_locale=0, coerce_c_locale_warn=0. Check every PyStatus result.
Register the one static pipe builtin and installation frozen tables in the
CPython-documented preinitialization/initialization order.

Initialize with `PyConfig_InitIsolatedConfig` and explicit isolated=1,
use_environment=0, parse_argv=0, safe_path=1, site_import=0,
user_site_directory=0, write_bytecode=0, inspect=0, interactive=0,
install_signal_handlers=0, dev_mode=0, optimization_level=0. Freeze argv and
orig_argv to one installation program name; no task-provided Python argv.
Use explicit filesystem_encoding='utf-8', filesystem_errors='surrogateescape',
stdio_encoding='utf-8', stdio_errors='strict'. Freeze all remaining actual
3.13.12 configuration fields in the descriptor and verify header/API support
rather than inventing undocumented fields. Resolve the frozen-use configuration
and any entropy/hash/locale/startup dependency during the build audit.

Set every path-config output explicitly before initialization:
base_exec_prefix, base_executable, base_prefix, exec_prefix, executable, prefix,
module_search_paths_set=1 and module_search_paths=[] . Use fixed installation
logical strings, e.g. `/lunar-static` and `/lunar-static/cpython-3.13.12`, rather
than discovering the memfd path or host interpreter. Pin inputs home, platlibdir,
program_name, pathconfig_warnings=0 and the absence of pythonpath_env. Exact
strings and all resulting fields must be frozen in the installation profile.
Do not call Py_Main/Py_RunMain or set run_filename/run_module/run_command.
An unset output can trigger path calculation, pyvenv/._pth/build-tree discovery.

Initialization must obtain encodings/importlib from the installation's finite
frozen/static closure with no host stdlib root. Audit/remove unadmitted stock
frozen/test/alias entries. A custom frozen-table pointer alone is insufficient.
Restrict the installation import routes to its reviewed builtin/frozen names;
remove or explicitly refuse file/zip/dynamic-extension fallback. Any required
bootstrap_external code remains pinned and has an explicit loader disposition.
Implementation details of these CPython-specific patches require source/header
review and actual startup; rearranging sys.meta_path alone is not a security proof.
A newly required module discovered during failed startup is a proposed recipe /
installation-version revision, not automatic admission into an existing pinned
image. Retain the failed candidate and freeze/review a new candidate explicitly.

## Frozen main and existing target delivery

The existing candidate `assets/launcher.c` calls
`PyImport_ImportModule("_lunar_static_main")` and its fixed `_main` callable.
`assets/frozen_main.py` computes `sum(n * n for n in range(1, 10)) == 285`,
collects CPython observations, and exchanges bounded constant pipe bytes via
`_lunar_fixture_pipe`. Its fixed case IDs are `baseline` and `loader-negative`.
These sources still require matching freezing, compilation and actual target
startup; source inspection is not a successful import or runtime observation.
The current `loader-negative` candidate also requires the fixed UTF-8 name and
six aliases to round-trip, one fixed unsupported codec to raise `LookupError`,
and the surrounding module/path profile to remain unchanged. Candidate and RSI
pins are refreshed explicitly in `candidate-codec-negative.md`; the old expanded
main and its historical graph remain retained separately. The new nine-source
AST observation is a source audit, not target registry or loader acceptance.
The existing pipe builtin only accesses the two original parent-owned broker
pipe endpoints; it is not a generic FD, filesystem, HTTP or arbitrary execution
API. Complete the required unknown module/codec and loader-negative matrix
within the reviewed finite workload. No caller data names a module, file or
code operand.

Validate independent installation/artifact pins and source bytes, seal the exact
executable with all original required seals, then use the existing target FD,
control v2, guardian, attestation, grants, absolute deadline and FD keep-list.
Feature190 already implements and independently validates the private `_Owner`
and retained context identity in `linux_executable_binding.py`. Reuse that
implementation; Feature189's actual static-target binding, cleanup and recovery
integration remains an open G3 gate. Test closed/reused original numbers,
same-byte foreign objects, forced public observation mutation and every
interrupted acquisition/release boundary against this fixture's retained owner.
Preserve primary errors with fixed cleanup-unknown evidence and never close a
known foreign reused object. No native v2 FD extension follows from this gate.
Do not re-exec the CI-installed Python or inherit any188 bundle FD. The first
fixture supplies no broad host runtime read roots. Where tests need readable
decoys, explicitly fixture-own narrowly bounded inert read roots and prove the
decoys are readable before testing the loader refusal; no grant is learned from
observed imports. Preserve ready/release/start/terminal, process reaping and FD
ownership on success, failure, interruption and cancellation.

Record machine receipts and raw observations separately from C-generated claims.
An independent reviewer verifies exact source/toolchain/artifact/ELF/module pins,
actual Python output, final CI head/tree and original lifecycle. Native source
pin drift must refuse while replacing/deleting the source image after sealing
cannot alter the original sealed image used by the successful fixture.
