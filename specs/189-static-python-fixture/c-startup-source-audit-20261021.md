# Feature 189 — bounded CPython C-startup source audit (2026-10-21)

## Scope and evidence boundary

This report records a bounded source review of selected CPython 3.13.12 C
startup, import, configuration, frozen-table, and path-configuration inputs. The
review read named regular-file members directly from the pinned release archive
on `5090gpu` with `tarfile.extractfile()`; it did not extract the archive, run
CPython, configure, compile, freeze modules, link an image, or run an evaluator.
The archive is 22,926,488 bytes with SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`, matching
the identity recorded in
[`release-input-audit-20261021.md`](release-input-audit-20261021.md). That
separate audit retained a valid detached-signature transcript; this report did
not rerun GnuPG or independently establish signer trust.

The observations below are source callsites and table semantics, not proof that
every branch executes in the candidate. The archive's `Python/frozen.c`,
`Modules/config.c.in`, and `Modules/getpath.c` are upstream release members. The
Lunar candidate's finite `Python/frozen.c`, static `Modules/config.c`, and
strict path implementation are separate generated or fixture-owned inputs.
Do not treat their planned hashes as build outputs. The existing prepared
staging tree is also distinct from the archive: its `Python/import.c`,
`Lib/importlib/_bootstrap_external.py`, and `Lib/encodings/aliases.py` differ
from the authenticated archive members, and the complete staging patch identity
is not established.

## Pinned archive members reviewed

These SHA-256 values and sizes were computed over the exact named member bytes
from the archive identified above. Paths are relative to its
`Python-3.13.12/` root. They are source identities, not claims that each member
was used by a configured build.

| Archive member | Bytes | SHA-256 |
| --- | ---: | --- |
| `Python/import.c` | 146,770 | `4e18922dc31001c24fd9875746881ab407252bddc6bca544f22403d50e493a61` |
| `Python/pylifecycle.c` | 106,247 | `21296f86275077e4f19234a2c32691ee087fea961c28745770373a6c4ef70789` |
| `Python/preconfig.c` | 25,604 | `cf75e44a6d6e55730ecb3dbe18aeedd0ca6140354d1b64d40e50aa2e61ceee1d` |
| `Python/initconfig.c` | 93,973 | `cd994293e560e14e2ceae100c36e7aa7435665dddb08e2038f33ee4e594143ee` |
| `Python/frozen.c` | 6,296 | `ac246e0144ddfae629315a605049ad1ffb191db4b35df419bd039e7f2f6ed829` |
| `Python/bltinmodule.c` | 95,929 | `707c3c3e599941828b79d5cfb4d355ad6a97ea72835bdf4510d2a627913b53f5` |
| `Python/sysmodule.c` | 118,571 | `9767ec9be310810126ae10eb4441ca9f0b40f9f7ab64cd26a036da4867790ca1` |
| `Python/codecs.c` | 46,160 | `910a58613c8332b1afa6c006595c536ca5ffa56845e65b3cf78b9e32219d511b` |
| `Objects/unicodeobject.c` | 474,671 | `77ffa6c7c7407207a531890f95e474c812fa1066bb0f22cd92887cf5717e83c7` |
| `Include/cpython/initconfig.h` | 8,197 | `ecccd0c893d606516d8c8cbdc5a20bb7aa0c3d97fd0ccbcdedbd4a1183c58e2b` |
| `Include/internal/pycore_initconfig.h` | 6,375 | `1e4437226a5b08c72a960f24fae497e43f0ef35b0e0140b0a58df6e2dbeba681` |
| `Include/internal/pycore_import.h` | 7,731 | `3a625cef967da0b404e25c4380973cc18fb56eff063829528438719f3f9b47c1` |
| `Include/import.h` | 3,235 | `00b7cb4d6e7f0055e25beabcea7bee576ff991bd83b4ffbb36912201cc0d9342` |
| `Modules/config.c.in` | 1,751 | `3b762c1ca93511eca2deb923f4632d708ec8f11f5d75e71bf2ec3cad84e69c03` |
| `Modules/Setup.bootstrap.in` | 971 | `bb401f9494c2f896aa40af6a8077ff9f22b99a9d4126ce38daef759427c8df88` |
| `Modules/Setup.stdlib.in` | 8,606 | `700424110da7f19053e02642da6853035490726b1cec9c9ed99b1261e447caa7` |
| `Modules/getpath.c` | 27,291 | `7483bff1382baa27ff1db8dd4b237bc3aa58e64e28996ddab5d83a5e8b642576` |
| `Modules/getpath_noop.c` | 267 | `8573d6611493b22ad038c1d208ef82755e430afa9a0b0ba9bd146160278a9f74` |
| `Programs/_freeze_module.c` | 6,590 | `50b61a5efbfb6c294e7ff0ffe6a01c0964b8c954285bcbac5d99c7a5483ca9be` |
| `Programs/_bootstrap_python.c` | 3,031 | `6dfda921d2128b66fa9b814c7e3feb0c6238b306e45c51e67255ebaebddd632a` |
| `Makefile.pre.in` | 121,814 | `eece065935a88ca410641df020a4f144d39e1b9154e87fbf2ba7c329a01ca712` |
| `configure.ac` | 255,967 | `8e47d53509f130d4a300d85ee51d899a21631ba40b83c5c8b32b2b8b33e525b8` |
| `configure` | 893,475 | `0495fd50c8441437de8df5bd681b94bda00492ad3cf0d0db07f52f928dc12f20` |

`Modules/config.c` is not a release-archive member. CPython supplies the
`Modules/config.c.in` template; its generated result depends on the selected
`Modules/Setup` and `makesetup` inputs. The Lunar candidate instead emits a
finite source from `tools/static_python_fixture/tables.py`. The reviewed
candidate records `generated-sources/Modules/config.c` as 1,576 bytes with
SHA-256 `f88d5155d330bafa52dba00030fb4c8dfcd4f3844e996b34980f81a30089fb0c`.
That is a pinned planned source asset, not an observed configure output or
compiled table. Likewise, the candidate finite table at
`generated-sources/Python/frozen.c` is recorded as 2,417 bytes with SHA-256
`70a872d666061c85a17a555aba090689b39c6a4c5786aae82c9d3e41432bcecf`; the
archive's stock `Python/frozen.c` has the different digest shown above.

## C-created modules and static builtin table

The release `Modules/config.c.in` marks the builtin table as being edited by
`makesetup` and declares `_PyImport_Inittab[]` (lines 13–16 and 35 onward). Its
stock core entries include `marshal`, `_imp`, `_ast`, `_tokenize`, `builtins`
and `sys`, `gc`, `_warnings`, and `_string` (lines 39–63). `builtins` and `sys`
have `NULL` initializers (lines 51–53): these are not ordinary `PyInit_*`
entries. In `Python/import.c`, `PyImport_Inittab` initially points at
`_PyImport_Inittab` (lines 53–61); a `NULL` initializer is treated as a
core-module special case by `is_builtin()` and `create_builtin()` (lines
2260–2275 and 2310–2327).

The lifecycle creates those two modules directly. `Python/sysmodule.c`
creates the `sys` module with `_PyModule_CreateInitialized()` and registers it
through `_PyImport_FixupBuiltin()` (lines 3890–3939). `Python/bltinmodule.c`
defines `_PyBuiltin_Init()` (line 3166 onward); `Python/pylifecycle.c` calls it
and fixes the result up as `builtins` (lines 803–823). `sys` is created before
`builtins`, and both precede `_PyImport_InitCore()` in the same lifecycle
sequence (`Python/pylifecycle.c` lines 916–934). The profile's explicit
`"NULL"` initializer spelling for those entries is therefore meaningful; it
must not be confused with an omitted table record.

`_imp` follows another distinct route. `Python/import.c:bootstrap_imp()` makes
a minimal spec, looks up `_imp` through the builtin table, and calls its
initializer before the import system is installed (lines 3114–3154). Then
`init_importlib()` imports the frozen `_frozen_importlib`, creates `_imp`,
places it in `sys.modules`, and calls the frozen bootstrap module's `_install`
method (lines 3173–3217). This describes the upstream route; the actual target
must still bind its generated initializer table and frozen source bytes.

The candidate's `tables.py` defines nine core table entries and ten static
additions, for the descriptor's fixed 19 builtin names. Its `Modules/config.c`
source is generated from that profile, not taken verbatim from the archive. The
candidate list also contains the fixture-owned `_lunar_fixture_pipe` module.
No configured `Modules/Setup` output, actual generated `_PyImport_Inittab`,
compiled initializer object set, or final linked symbol table was reviewed
here. `Modules/Setup.stdlib.in` contains conditional optional-module entries;
the archive template alone does not prove which conditions a configured build
would enable.

## Frozen tables, aliases, and startup code arrays

The upstream `Python/frozen.c` is broader than the fixed Lunar profile. It
contains `_frozen_importlib`, `_frozen_importlib_external`, and `zipimport` in
the bootstrap table (lines 69–74); `abc`, `codecs`, and `io` plus modules for
`site` and `runpy` in the stdlib table (lines 75–97); and a nonempty test table
(lines 98–110). It also contains more aliases than the two importlib bootstrap
aliases (lines 116–128). These are the stock source defaults, not the final
candidate inventory.

The import implementation always searches the bootstrap table. It searches
stdlib and test frozen tables when `use_frozen()` is true, and custom modules
are searched separately (pinned `Python/import.c`, lines 2746–2759, 2783–2810,
and 2887–2933). `use_frozen()` reads `PyConfig.use_frozen_modules` unless an
internal override is set. A frozen module's name, alias, code bytes, and package
bit are resolved in separate code paths; the callable API
`PyImport_ImportFrozenModule()` is declared in `Include/import.h` (lines 81–85)
and implemented in `Python/import.c` (lines 3015–3107). The descriptor's table
claims cannot prove generated headers match these inputs or that every runtime
lookup comes from the intended table.

There is also a separate embedded startup-code path in upstream
`Modules/getpath.c`: it includes generated `Python/frozen_modules/getpath.h`
(lines 24–25), and `_Py_Get_Getpath_CodeObject()` unmarshals the embedded
`_Py_M__getpath` array (lines 840–845). This is not an entry in the regular
`Python/frozen.c` module tables. It is why an empty candidate
`embedded_startup_arrays` disposition needs source/object evidence. The planned
target replaces stock `Modules/getpath.o` with the Lunar strict path asset
(`tools/static_python_fixture/assets/getpath.c`, hash
`a067fe6dc9a2bd63d5847e29b14c9b7c30d42432dcf1f505bb461feae6b2d722`) and
excludes stock `Python/frozen.o`. The strict asset checks fixed path strings,
an empty explicit `module_search_paths`, and `module_search_paths_set=1`; it
does not calculate paths from the filesystem or environment. Its inclusion is
only a candidate-source statement until a configured object/link audit confirms
that the stock `getpath.o` and generated `getpath.h` are absent.

`Modules/getpath_noop.c` is not that target implementation: it returns an
error for `_PyConfig_InitPathConfig()` (lines 6–10). The build-input plan uses
it only for the same-source freezer stage, and uses the installation-owned
strict getpath for the target stage. Do not treat freezer-stage substitution
as target path support.

The upstream `Programs/_bootstrap_python.c` has its own bootstrap frozen table
including `zipimport` and its own aliases (lines 2–46). It is the restricted
build-time interpreter source, not the intended installed target. The build
plan excludes it from the target and excludes stock `Python/frozen.o`; the
planned finite target table is separately emitted by `tables.py` with two
bootstrap entries, fixed stdlib/custom entries, an empty test table, and two
aliases. The table emitter produces source references to nine generated module
headers, but no same-source freezer output or target headers have been
verified.

## C startup import edges and controlling fields

The reviewed upstream C sequence establishes these source-level edges:

| C site | Source fact | Candidate disposition / remaining check |
| --- | --- | --- |
| `Python/import.c:init_importlib()` (3173–3217) | Imports frozen `_frozen_importlib`; initializes `_imp` from the builtin table; invokes bootstrap `_install`. | Both modules are in the fixed profile. Must bind actual table/header bytes and the exact prepared `Python/import.c` postimage. |
| `Python/import.c:init_importlib_external()` / `_PyImport_InitExternal()` (3222–3231, 4161–4178) | Calls `_install_external_importers()` and then `init_zipimport()`. The latter tries to obtain `zipimport.zipimporter`; a missing module clears the error and is tolerated (4125–4158). | `zipimport` is not admitted to the finite candidate profile. Review the final patched bootstrap source and demonstrate that missing `zipimport` and external loader routes fail closed. |
| `Python/codecs.c:_PyCodec_InitRegistry()` (1501–1511) | After registry setup, imports `encodings` so it can register codec search functions. | `encodings` is in the frozen list. The source-preparation policy now constrains names to UTF-8 and six aliases; target registration and runtime lookup remain unverified. |
| `Objects/unicodeobject.c:_PyUnicode_InitEncodings()` (15865–15878) | Initializes the codec registry, filesystem codec, and stdio encoding in that order. | The candidate pins filesystem and stdio encoding/error fields; actual startup must show the intended UTF-8 routes and reject unsupported codecs. |
| `Python/pylifecycle.c:init_interp_main()` (1184–1232) | Unless `_install_importlib` is false, initializes import config, external importers, optional faulthandler, then Unicode encodings. | Candidate sets `_install_importlib=1`, `faulthandler=0`; actual configured field writes and call sequence are not built/runtime-verified. |
| `Python/pylifecycle.c:init_sys_streams()` (2802–2828) | Imports `io` before creating standard streams. | `io` and its `_io`/`abc` dependencies are in the profile; startup origins remain unobserved. |
| `Python/pylifecycle.c:init_set_builtins_open()` (2769–2799) | Imports `builtins` and obtains `io.open`, then assigns `builtins.open`. | `builtins` and `io` are listed; actual origin is unverified. |
| `Python/pylifecycle.c` warning and site branches (1294–1319) | Imports `warnings` only if `warnoptions` is nonempty; imports `site` only if `site_import` is enabled. The exact 3.13.12 source member is now retained and tested as an inert supporting fixture in `pylifecycle-warning-source-audit-20261023.md`. | Candidate pins `warnoptions=[]` and `site_import=0`. A future launcher/config mutation or altered argv must not activate these routes; source pins do not establish effective runtime settings. |

The Python startup inventory's direct C edges do not enumerate the Python
bootstrap's conditional, fallback, deferred, or computed imports. In
particular, the prior archive AST audit found dynamic `encodings.<modname>`
selection and `abc`'s `_py_abc` fallback; neither is closed by this C review.
The attempted `zipimport` lookup is another explicit C startup edge even
though missing `zipimport` is tolerated.

`Include/cpython/initconfig.h` contains the public `PyPreConfig` and `PyConfig`
fields; `Python/initconfig.c` keeps a `PYCONFIG_SPEC` list of fields and parses
`PYTHON_FROZEN_MODULES` and `-X frozen_modules` at lines 2155–2199. The selected
profile sets `use_environment=0`, `parse_argv=0`, and
`use_frozen_modules=1`; these values should suppress those environment and
argument gates in the intended isolated launcher. However, the source audit
does not establish the exact compiled header/configuration or caller behavior.
`Python/import.c:use_frozen()` also has an internal frozen-module override
before consulting `PyConfig` (2746–2759); the final built-in surface and
reachable override behavior need a separate disposition.

The candidate pins path outputs (`executable`, prefixes, home, `stdlib_dir`,
`platlibdir`, `module_search_paths_set`, and `module_search_paths`) in
`static_python_installation.py`. Its `profile.c` and strict getpath asset are
Lunar-owned candidate sources, not upstream headers or runtime proof. The
required header/API check must bind these names and types to the selected
CPython 3.13.12 headers, then bind actual initialized output fields after the
target starts.

## Configure and header boundary

`Include/cpython/initconfig.h` declares the public configuration structures;
its fields include the encoding, stdio, frozen-module, safe-path, executable,
prefix, search-path, and run-mode values named above. It conditionally includes
`legacy_windows_stdio` for Windows and `enable_gil` for free-threaded builds.
The current profile is Linux, GIL-enabled CPython 3.13.12. The header/source
review provides declarations and upstream default logic, not the selected
generated `pyconfig.h` or proof all candidate C assignments compile against
the exact configured layout.

`Modules/Setup.bootstrap.in`, `Modules/Setup.stdlib.in`, `Modules/config.c.in`,
`configure.ac`, `configure`, and `Makefile.pre.in` are inputs/templates. No
configured `Makefile`, `pyconfig.h`, resolved `Modules/Setup`, or generated
`Modules/config.c` from the intended candidate was reviewed. The existing
build-input contract explicitly retains `LIBOBJS`, `MACHDEP_OBJS`,
`DTRACE_OBJS`, `PLATFORM_OBJS`, `PERF_TRAMPOLINE_OBJ`, `MODOBJS`/`MODLIBS`,
`LIBS`/`SYSLIBS`, CRT, libc/libm, compiler-support objects, and actual compiler
flags as unresolved. The configure and build templates therefore cannot
establish a complete object/link closure or prove that optional discovery and
stock setup entries were excluded.

The candidate input plan is useful evidence for proposed exclusions and
dispositions: the freezer has empty tables and uses `Modules/getpath_noop.c`;
the target uses generated finite tables and the strict Lunar getpath source;
stock target `Python/frozen.o`, `Modules/getpath.o`, `Programs/python.o`, and
`Programs/_bootstrap_python.o` are planned exclusions. These are planning
facts only. A later configured-build audit must compare real Makefile
substitutions, generated headers, object/archive/link maps, and ELF bytes to
the same pinned source/profile before any runtime gate can advance.

## Explicit unresolved gates and focused next checks

The following remain open and must not be converted into empty inventories or
false-success fields:

1. Reconcile the exact configured `PyPreConfig`/`PyConfig` layout and
   initialization call order with the pinned header and the actual launcher
   source. Confirm all path outputs are set before path initialization and that
   environment, argv, site, warning, debug, free-threaded, and frozen-module
   override gates have the intended disposition.
2. Audit the exact C sources and patch postimages consumed by the configured
   target, including the `Python/import.c` patch, loader changes, `getpath`
   replacement, `Modules/Setup` result, generated inittab, and all optional
   module discovery. The prepared staging tree is not a substitute for this
   source-to-build binding.
3. Resolve `encodings` dynamic codec selection, the `_py_abc` fallback,
   `_frozen_importlib_external` deferred imports, and the optional `zipimport`
   lookup with a finite source or explicit refusal disposition. No profile
   inventory is enlarged by discovery alone.
4. Establish that the target has exactly the intended frozen/bootstrap/test/
   custom tables, aliases, generated header bytes, and no stock `getpath`
   embedded code or startup table. The current candidate table emitter and
   descriptor do not prove the contents of a freezer output or final ELF.
5. Close the real configure/static-link inputs and inspect the target link map,
   symbols, and ELF. Retain the first compiler/configure/link/startup failures.
6. Only after those gates, execute the sealed fixed fixture to observe actual
   CPython version, configuration fields, startup module origins, loader
   refusal behavior, frozen-main result, and pipe lifecycle. No such acceptance
   run is recorded by this report.

Focused provider-free checks for a future implementation should pin the source
member digests above; detect drift in direct C literal-import, `_inittab`,
frozen-table, alias, and getpath-array sites; distinguish upstream members from
generated candidate assets; verify the selected Linux/GIL header field set and
its explicit conditional omissions; and refuse added or unresolved table rows.
Those checks would test the bounded observer, not prove that all C or Python
startup edges are enumerated. Existing relevant synthetic suites are
`tests/test_static_python_import_audit.py`,
`tests/test_static_python_installation.py`,
`tests/test_static_python_startup_closure.py`, and
`tests/test_static_python_build_inputs.py`.

## Claims

This report makes no build, runtime, loader, ownership, or production claim:

```text
source_graph_verified=false
configured_closure_verified=false
build_performed=false
runtime_startup_performed=false
loader_policy_verified=false
owner_verified=false
installation_accepted=false
runtime_load_protection=false
general_code_origin_protection=false
production_admission=false
```

No WebAgent, remote evaluator, company evaluation platform, or solver campaign
was used.
