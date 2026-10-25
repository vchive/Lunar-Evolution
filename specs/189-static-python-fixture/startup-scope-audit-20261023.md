# Feature 189 — baseline startup-scope import graph review (2026-10-23)

## Decision and scope

This review records the baseline, non-Windows startup graph for the existing
candidate `cpython-3.13.12-linux-x86_64-musl-gil-static-startup-v1-candidate`.
Its machine-readable edge list and source pins are in
[`startup-scope-graph-cpython-3.13.12-v1.json`](startup-scope-graph-cpython-3.13.12-v1.json).
The decision is to keep the current 22-name expected-startup inventory and the
separate eight-name root vector unchanged. The evidence does not justify adding
`warnings`, `site`, `zipimport`, `tokenize`, `importlib.readers`, or
`importlib.metadata` to the baseline inventory. It also does not justify
accepting a complete source graph or the configured candidate. There is no
automatic profile expansion when a source edge falls outside the current
inventory.

The reviewed Python set is the eight exact CPython release-archive members plus
the expanded Lunar `_lunar_static_main` source. Five fixed sources are observed
after the existing pure source-preparation policy. Supporting C sources are
the pinned `Python/import.c`, `Python/pylifecycle.c`, `Python/_warnings.c`, and
`Objects/genobject.c` fixtures. The module AST observation remains the existing
9-source, 28-edge wire with four unsupported syntax sites and digest
`d7802d7ac60202b720c30bacfb124fe8ee155298ac88ddd8facdbbc7f07dc9f5`. The
focused audit test replays those exact inputs, maps the package initializer to
the observer's required `encodings.__init__` key, and asserts exact equality of
all 28 normalized Python edges and all four unsupported-site tuples with the
retained JSON. The
root-vector digest remains
`d1743e729bac34c5110a1d1373cc48c74a52b585034825227ed37d0178e39313`.

## Baseline startup reachability

The eight root names come from the independent source-root audit. CPython's
`pylifecycle.c` creates `sys`, `builtins`, and `__main__`; `Python/import.c`
initializes `_frozen_importlib` and `_imp`; `codecs.c`/`unicodeobject.c` request
`encodings`; `pylifecycle.c:init_sys_streams()` requests `io`; and the Lunar
launcher imports `_lunar_static_main`. These are source-derived roots, not
runtime observations.

The transitive edge map accounts for every name in the current 22-name startup
inventory:

| Source path | Target(s) | Evidence and disposition |
| --- | --- | --- |
| `_frozen_importlib` | `_frozen_importlib_external` | `_install_external_importers()` imports the external bootstrap; pinned `Python/import.c` invokes it during normal interpreter initialization. |
| `_frozen_importlib` | `_thread`, `_warnings`, `_weakref` | `_setup()` iterates this exact fixed string tuple and calls `_builtin_from_name()`. This is a literal C-builtin lookup the generic AST observer does not infer. |
| `_frozen_importlib_external` | `_imp`, `_io`, `_warnings`, `marshal`, `sys` | Fixed module-level imports in the pinned source. |
| `_frozen_importlib_external` | `posix` | Selected by the source's non-Windows branch for the declared Linux candidate; the target OS is not yet observed from a built image. |
| `_lunar_static_main` | `_imp`, `_lunar_fixture_pipe`, `sys` | Top-level imports in the reviewed expanded Lunar main source. |
| `encodings` | `codecs`, `sys`, `encodings.aliases`, `encodings.utf_8` | The prepared source binds UTF-8 to one fixed module and keeps the aliases source finite. The relative package base self-edge is retained in the machine graph but introduces no new module. |
| `codecs` | `_codecs`, `builtins`, `sys`, `encodings` | `_codecs` is the pinned wildcard-import base; `encodings` is a deferred `lookup()` import and is already a C startup root. Wildcard names are not expanded into module edges. |
| `encodings.utf_8` | `codecs` | Fixed module-level import. |
| `io` | `_io`, `abc` | Fixed module-level imports; the `_io` initializer source has a separate bounded audit. |
| `abc` | `_abc` | The prepared source requires `_abc`; the `_py_abc` fallback is removed. |
| Frozen aliases | `importlib._bootstrap` → `_frozen_importlib`; `importlib._bootstrap_external` → `_frozen_importlib_external` | Fixed alias inventory. The graph records alias routes separately from source imports. |

The machine-readable graph is a source-review candidate graph, not a
`startup-closure-v2` receipt. Its reachability is tested against the existing
candidate inventory, while all acceptance claims remain false. The current v2
parser's `synthetic-dto-comparison-only` wire can test graph consistency but
cannot upgrade this source review to proof that the configured build consumed
the audited sources.

## Explicit non-baseline and conditional routes

Several routes are accounted for without adding their modules to the baseline
inventory:

- `pylifecycle.c` imports `warnings` for a nonempty `warnoptions` list. The
  candidate declares an empty list. `_warnings.c` separately tries to import
  Python `warnings` only for selected display hooks before finalization; on
  `ImportError` it clears that error and uses its C display fallback. The fixed
  source proves this fallback branch exists, but no target startup or fixed
  workload observation proves how warning paths behave. The graph DTO has no
  explicit optional-import/refused-import route, so the warning path remains a
  closure limitation beyond the baseline graph.
- `site` is guarded by `config->site_import`; the candidate declares zero. The
  actual initialized value has not been observed.
- Upstream C startup calls `init_zipimport()`, but the fixed candidate
  `Python/import.c` postimage removes that call. The postimage is pinned; its
  use by a configured build is not established.
- `nt` and `winreg` are imports in Windows-only source branches, excluded from
  the Linux candidate scope. The target platform itself remains unobserved.
- `tokenize` is imported by deferred `decode_source()`. `importlib.readers` is
  imported by resource-reader methods, and `importlib.metadata` by deferred
  `PathFinder` methods. They are not called on the audited bootstrap path, but
  the source review does not prove direct calls or post-startup use unreachable
  or refused.
- `_lunar_static_main` contains a computed `__import__` in the explicit
  `loader-negative` case. The baseline case does not call that helper; the
  negative case expects `ImportError` for each fixed non-inventory name. That
  refusal has not been observed on the target runtime.
- The Python AST observer flags frozen-importlib `exec`, external-bootstrap
  `compile`, and `codecs`' `from _codecs import *`. Source review accounts for
  the first as execution of frozen code returned by the C frozen table, the
  second as a deferred namespace-loader method, and the third as a known
  `_codecs` base module edge. The generated frozen bytes, configured builtin
  table, and runtime behavior are still unbound; these classifications do not
  clear the observer's unsupported records.

## What remains open

The source-level baseline reachability map is now retained, and the candidate
inventory decision is versioned. The broader unchecked task remains open:

1. Bind launcher assignments to the actual initialized `PyPreConfig` and
   `PyConfig`, including platform, warning, site, frozen-module, and path fields.
2. Bind the patched source tree and fixed patch set to the actual configured
   `Setup`, builtin/frozen tables, same-source freezer outputs, generated
   headers, objects, link map, and ELF.
3. Resolve optional warning hooks and direct deferred resource-reader/metadata
   calls for any scope broader than baseline startup.
4. Observe the sealed target's startup module origins and the fixed
   loader-negative refusal case.

This record does not claim complete source graph verification, configured
closure, build, startup, runtime loader protection, installation acceptance,
production admission, or online publication. No configure, build, freezer,
solver, evaluator, or network operation was run for this audit.
