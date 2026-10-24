# Fixed configure candidate assets

This G1 continuation turns the remaining configure proposal into retained,
deterministic plan assets. It adds no parser, execution API or success receipt.
The full recipe/provenance task remains open until the actual configured inputs
and outputs have been reviewed. Both emitted shell entry points still exit 78.

## Assets and scope

`tools/static_python_fixture/configure_plan.py` exposes the parameter-free
`emit_configure_plan_assets()` returning a fresh relative-path-to-bytes mapping:
`configure-plan.json`, `config.site`, and `Modules/Setup.local`. The existing
plan emitter writes these under `configure-plan/` and records each actual byte
size and SHA-256 in its outer manifest. The candidate JSON is planning data,
not a wire accepted by an admission parser. The old pinned reviewed-build-inputs
asset is retained unchanged; its earlier proposed configure argv is explicitly
superseded only as a proposal by this separate candidate.

The candidate distinguishes build `x86_64-linux-gnu` from host
`x86_64-linux-musl`. Configure argv uses supported `--without-ensurepip` and
`--disable-shared` spellings, fixes `--disable-ipv6` to avoid the upstream
cross-build getaddrinfo ambiguity, excludes the failed `--with-system-ffi=no`, and
records all unresolved tool/build-Python bindings as unresolved planning data.
No symbolic binding can be executed by this emitter. A clean environment plan
uses only named fixed variables and explicit tool/input bindings, without
reading the process environment. The outer `build_environment` uses the same
candidate `CONFIG_SITE` path rather than the old `/dev/null` proposal.
The relative path is based at the emitted plan root, without selecting an
execution cwd. The retained Setup.local is not installed into the staged
CPython tree by this emitter.

`config.site` fixes three candidate feature-disable policies:
`ac_cv_func_dlopen=no`, `ac_cv_file__dev_ptmx=no`, and
`ac_cv_file__dev_ptc=no`. These are desired policies, not observed platform
facts or a complete cross-cache. They do not preanswer unknown configure checks.

`Modules/Setup.local` explicitly enables the nine upstream static additions
from the pinned bootstrap template and disables the remaining 94 names in the
union of the pinned bootstrap and stdlib templates (103 total). `_lunar_fixture_pipe`
is separately fixture-owned in the existing direct compile plan. Core builtins
remain in their existing core plan. Template coverage is finite: it does not
claim all configure-discovered modules or actual makesetup output are covered.

The candidate must explicitly require the same-source direct C freezer with
empty frozen tables and initialization/importlib disabled. Stock cross-build
configure selects a build-Python `_freeze_module.py` route; that route, stock
make regeneration and an unrelated host interpreter cannot satisfy this gate.
Toolchain/CRT/libc, separately pinned build-Python/helper dependencies, remaining
cache answers, actual optional discovery, generated Makefile/pyconfig, role
compile/link flags, and complete closure remain unresolved. No configured,
compiled, frozen, linked, runtime or admission claim becomes true.

## Verification

Focused tests compare module coverage with the independently retained pinned
template bytes, require exact enabled source rows and the 94-name disabled
complement, check deterministic fresh assets and emitted digest/size records,
and verify hostile ambient build variables do not alter the output. Check plan
asset consistency before publishing the outer manifest or build entry points.
Existing default/opt-in shell tests must still prove exit 78 before any
configure/compiler/freezer effect. Run Ruff, compileall and diff checks.
