# Feature189 — Installation-owned static CPython fixture

Status: bounded implementation in progress, 2026-10-08. Priority P1. No static
artifact, compilation, startup or Feature189 acceptance is established yet.
Feature188 final source `c5973a7b4ad026182b11e6d65af946ae6d15bd30`, run
`37747759152`, independently passed three-version raw audit and merged as
`4f8576d02f2b3be191f71d8c869e48f704dc7a4a`. Its main push `37754528167`
also independently passed 22 phases per version (current11984/92 platform skips,
material274/0 skips). Existing 184 trusted-host startup and 188 sealed-data evidence cannot
satisfy this feature's static-runtime acceptance.

## First profile and outcome

The sole first profile is Linux x86_64, ELF64 little-endian ET_EXEC, exact
CPython 3.13.12 standard GIL-enabled release ABI (no debug/free-threaded/JIT profile),
one installation-owned fully static executable, a finite frozen
and static-builtin module table, and one fixed inert frozen main. The image
contains CPython, the startup module closure, a tiny static `_lunar_fixture_pipe`
builtin and `_lunar_static_main`. Launch the actual image through the existing
sealed target FD and original native guardian/control-v2 lifecycle. No new FD,
bundle handoff, selector or production Python worker admission is introduced.
The Feature188 frame is not loaded by this first image.

The fixed frozen main performs a real Python computation, records actual
`sys.version_info`, `sys.implementation.cache_tag`, flags and startup module
origins, and exchanges bounded inert request/response bytes through the existing
two parent-owned broker pipe endpoints. Use a predefined fixture-case enum only;
no caller-selected module/path, `-c`, code string or interpreter argv is accepted.
The C launcher must obtain the computation and observations from the running
CPython; a fabricated C reply cannot satisfy acceptance.

## Installation and original pins

The installation supplies the source/patch/toolchain/libc/recipe/generator/module
inventory and final artifact described in data-model.md. The caller independently
pins the installation descriptor and executable digest. Runtime entry must not
build, download, pip-install, scan imports, use `sys.executable` as a replacement,
or regenerate pins from current installation bytes.

The research observed CPython tag `v3.13.12` at source commit
`1cbe481834751b0125e006042ffbd8cd5eaec8a8`, annotated tag object
`c3024299e68ff061b197b711368c3e1d74beb4c7`. Its tag signature was not verified.
These are observed source identifiers, not an executable digest or completed
supply-chain attestation. Verify source acquisition/identity before future builds.
The selected build candidate is Zig0.16.0 Linux x86_64, LLVM21.1.0 and its bundled
musl1.2.5 plus backports and Zig-libc replacements, ordinary GIL CPython3.13.12.
The toolchain archive and upstream source archive have explicit advertised pins;
retrieved bytes, patches, generator and artifact hashes still require observation.
Admission of null/placeholder/default-host
pins is forbidden; resolve the installation gate before any build is called accepted.

Require no PT_INTERP and no DT_NEEDED in the final ELF. Static libpython or
`--disable-shared` alone is insufficient. Enumerate every static link input and
remove/refuse dynamic extension loading and unsupported loader routes at the
installation build boundary. Prefer one separately pinned musl toolchain profile;
static glibc without a closed NSS/gconv/dlopen disposition does not qualify.
The final image must be no larger than **128 MiB (134217728 bytes)**, matching
the existing `producer_launcher.MAX_OUTPUT_BYTES` and `linux_executable_binding`
admission ceiling. Do not raise that ceiling or add a temporary exception to fit
an image; an oversized build is a failed candidate.

## Original target ownership gate

Feature190 final source `fc4cda6a64bd27cc5c6946b9e5bdaa5bdb431b07` implements
private original-source/anchor/borrowed ownership and exact live binding checks.
Its own final three-version Linux acceptance and merge remain prerequisites for
launching the Feature189 image; source review or Darwin skips cannot meet them.
The fixed image must use a privately held target owner whose
original binding/lifetime is independently validated by dedicated fixtures, or a
separately reviewed owned-target recovery implementation must be completed first.
Do not invent an existing private-owner API or reconstruct ownership from parsed
JSON, a same-byte object or a public numeric FD. Keep the native v2 inherited-FD
schema unchanged; ownership proof is an implementation/acceptance gate, not a new
FD grant or a claim that the old helper has already been repaired.

## Complete initialization closure

The final descriptor records every builtin, frozen module, package bit, alias,
source/generated-byte digest and generated table. Audit all stock frozen tables
and bootstrap/static inittab entries, including separate embedded startup code/data
arrays such as getpath when retained; a sys.modules trace alone is incomplete.
Adding `PyImport_FrozenModules` does not
remove the stock tables. Remove unadmitted site/runpy/test/zip entries and fail
if an extra entry remains. Static optional modules are not silently admitted by
configure autodetection.

The closure must cover CPython's exact initialization, filesystem/stdio UTF-8,
codec registry, importlib bootstrap and the fixed main. The seed includes
`_frozen_importlib`, required `_frozen_importlib_external` bootstrap machinery,
`sys`, `builtins`, `_imp`, `marshal`, `_io`, `_codecs`, and frozen `encodings`,
`encodings.aliases`, `encodings.utf_8`, `codecs`, `io`, `abc`, plus the fixed main
and pipe builtin. **This is a seed, not the accepted complete inventory.** The
exact required additional builtins/codecs and their source disposition must be
closed by build review and actual startup. No runtime discovery widens this list.

Use fixed isolated PyPreConfig/PyConfig as specified in plan.md. Freeze all path
configuration outputs, not only sys.path or isolated mode. Installed builtin /
frozen import handling must refuse non-inventory names and file/zip/dynamic
extension fallback for this fixed fixture. Test readable decoys independently;
Landlock denying the files must not be the only explanation for non-loading.

## Claims and boundary

Successful live execution may establish `execution_performed=true` for the
known frozen main and `initial_image_binding=sealed-static-installation-image`.
It establishes that the tested initial executable/runtime/frozen bytes were the
pinned sealed image, and that its fixed startup, pipe exchange and original
lifecycle succeeded under the trusted installation/controller/kernel model.

Keep `runtime_load_protection=false`, `production_admission=false` and
`general_code_origin_protection=false`. The contract does not prohibit
compile/exec, marshal/code-object construction, mutable import hooks or process
memory changes. No arbitrary malicious Python program is admitted. The fixture
does not narrow existing work/output grants or add a post-start exec/memory gate.
An importer policy, empty sys.path or immutable initial image cannot establish
that all later code objects originate in the image.

A generic project runtime consuming188 material, a new native bundle FD and
importer, full producer SDK freezing, real OpenEvolve/Shinka adapters, production
RSI composition and P2 services/multi-host scheduling remain separate features.
No model, WebAgent, remote/company evaluator, real campaign, .env or credentials
are read or run. Installation preparation and pure admission implementation are
within this feature. Actual image execution remains gated on Feature190 acceptance.
