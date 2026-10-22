# Feature 189 — partial source review, not accepted closure

Date: 2026-10-21

## Scope and evidence limits

This is a read-only, source-level review of a temporary CPython 3.13.12
prepared snapshot on `5090gpu` at
`/tmp/lunar189-g2probe-20261021.Fqpy3B/source`. The snapshot reports
CPython 3.13.12 in `Include/patchlevel.h`, but is not a pristine release tree:
`Python/import.c` contains a fixture-specific external-init branch, and
`Lib/importlib/_bootstrap_external.py` has an empty
`_get_supported_file_loaders()` implementation. The snapshot directory is not
a Git checkout, so its source-tree commit and complete patch identity were not
independently established in this review. Findings about those patched paths
must not be generalized to the pristine CPython archive or another build.

The descriptor's nine frozen names do not correspond to nine source files in
this snapshot. Eight CPython `.py` inputs are present and were inspected. The
custom `_lunar_static_main` source is absent: a read-only search under the
snapshot found no `_lunar_static_main.py`. Therefore its imports, source digest,
and contribution to the closure could not be reviewed or hashed here. The two
`_frozen_importlib` names refer to CPython's importlib bootstrap sources below;
they are not separate source files in the archive.

## Inspected source inputs and SHA-256

These hashes identify the files as found in the temporary prepared snapshot;
they are not release pins and do not authenticate the snapshot.

| Frozen name | Snapshot source path | SHA-256 |
| --- | --- | --- |
| `_frozen_importlib` | `Lib/importlib/_bootstrap.py` | `b84488f731914f6da30607e10f6f8d4c5c2ff7f4b0e913060aa66999c04f6252` |
| `_frozen_importlib_external` | `Lib/importlib/_bootstrap_external.py` | `2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab` |
| `abc` | `Lib/abc.py` | `e558702a95cdce3febd289da021715d2b92bc43995b8a1bc58dfa1c3d8010287` |
| `codecs` | `Lib/codecs.py` | `2f278497548b8313580b247a1097a0a304e5087a355ebb11a92ec685fa9e63ff` |
| `encodings` | `Lib/encodings/__init__.py` | `78c4744d407690f321565488710b5aaf6486b5afa8d185637aa1e7633ab59cd8` |
| `encodings.aliases` | `Lib/encodings/aliases.py` | `43aadac378861c1bbdaaf04be8e1bb7d878529a7641ec123b5df4eccdd4c6106` |
| `encodings.utf_8` | `Lib/encodings/utf_8.py` | `ba0cac060269583523ca9506473a755203037c57d466a11aa89a30a5f6756f3d` |
| `io` | `Lib/io.py` | `7cec3cb8ac004058dd0a5af246e6d950fb59c7ddd0058fda48bcb3fcb98d8822` |

## Imports and relevant startup edges

The following records direct imports and important deferred or conditional
edges found in the inspected sources. It is not a mechanically complete import
graph and does not establish that a declared profile is sufficient.

| Source | Imports or edges observed | Profile relation |
| --- | --- | --- |
| `_frozen_importlib` | No module-level `import`/`from` statement in the inspected source. Its `_install_external_importers()` function imports `_frozen_importlib_external` later. `_setup()` obtains `_thread`, `_warnings`, and `_weakref` through builtin import machinery and injects them into the bootstrap module. | The external bootstrap is a frozen profile entry; `_thread`, `_warnings`, and `_weakref` are builtin profile entries. |
| `_frozen_importlib_external` | Imports `_imp`, `_io`, `sys`, `_warnings`, `marshal`, and `posix` on the Linux branch. Windows-only branches import `nt` and `winreg`. Deferred loader paths import `tokenize`, `importlib.readers.FileReader`, `importlib.readers.NamespaceReader`, and `importlib.metadata.MetadataPathFinder`. | Linux imports listed in the first sentence are in the fixed builtin inventory. Windows modules and the deferred stdlib modules are outside this profile. In this prepared snapshot, `_get_supported_file_loaders()` returns an empty list; that patch suppresses loader enumeration but is not evidence that every dormant path is safe or unreachable. |
| `abc` | Tries `from _abc import ...`; on `ImportError`, falls back to `from _py_abc import ABCMeta, get_cache_token`. | `_abc` is a profile builtin. `_py_abc` is not a profile frozen or builtin module; the fallback route is outside the profile and requires an explicit disposition. |
| `codecs` | Imports `builtins` and `sys`, then `from _codecs import *`. Its `open()` helper imports `encodings` when called. | `builtins`, `sys`, and `_codecs` are profile builtins; `encodings` is a profile frozen module. |
| `encodings` | Imports `codecs` and `sys`, and uses the relative import `from . import aliases`. `search_function()` dynamically constructs `encodings.<modname>` and calls `__import__` with that computed name. On Windows it can also import `_winapi` and `encodings.mbcs`. | `codecs`, `sys`, `encodings`, and `encodings.aliases` are in the profile. The computed codec target is runtime-selected and is not bounded to `encodings.utf_8` by this source alone. `_winapi` and `encodings.mbcs` are outside the Linux profile. |
| `encodings.aliases` | No imports found. | No additional dependency identified in this source. |
| `encodings.utf_8` | Imports `codecs`. | `codecs` is a profile frozen module. |
| `io` | Imports `_io` and `abc`, and imports named objects from `_io`. A Windows-only branch imports `_WindowsConsoleIO` from `_io`. | `_io` is a profile builtin and `abc` is a profile frozen module. The Windows-only branch is outside the Linux target. |

Relevant C startup edges were also checked in the same prepared snapshot:

- `Python/import.c:init_importlib()` imports the frozen `_frozen_importlib`,
  creates/installs builtin `_imp`, and calls `_install()` on the bootstrap
  module. The bootstrap then installs builtin and frozen importers.
- The bootstrap source's `_setup()` path injects `_thread`, `_warnings`, and
  `_weakref`; its later `_install_external_importers()` imports the frozen
  `_frozen_importlib_external`.
- `Python/import.c`'s `_PyCodec_InitRegistry()` path imports `encodings` from C.
  The `encodings` package registers the Python codec search function. The
  fixed UTF-8 filesystem and stdio configuration is expected to reach
  `encodings.utf_8`, but the package's computed import mechanism permits other
  codec module names unless an independently verified gate constrains them.
- `Python/pylifecycle.c:init_sys_streams()` imports `io` from C. `io` then
  depends on builtin `_io` and frozen `abc`.
- `Python/frozen.c` contains the stock bootstrap frozen table and the two
  `importlib._bootstrap` aliases. This review did not verify generated frozen
  headers, their relation to the inspected source hashes, or the final linked
  image.

The descriptor's Linux profile includes the active dependencies identified
above: `_imp`, `_io`, `_warnings`, `marshal`, `posix`, `_thread`, `_weakref`,
`_codecs`, and `_abc` as builtins, and the listed frozen bootstrap, codec, and
I/O modules. This inventory comparison is only a comparison of names. It does
not show that all initialization paths, dynamically selected imports, loader
behavior, or actual runtime origins are closed.

## `operator` finding

No direct `import operator` or `from operator ...` statement was found in any
of the eight inspected `.py` inputs. No direct or indirect `operator` edge was
identified in the reviewed fixed Linux bootstrap edges. A comment in
`_bootstrap_external.py` mentions the word “operator” in an unrelated
historical note; it is not an import.

This does **not** prove that `operator` is unnecessary for the complete
startup closure. `_lunar_static_main.py` is missing, codec imports in
`encodings` are computed at runtime, and dormant loader paths and C/runtime
behavior were not exhaustively audited. Keep `operator` outside the current
profile; do not add it based on this partial review, and do not claim closure
without completing the missing checks.

## Required gates before accepting a startup closure

1. Obtain and independently identify the exact source tree and its complete
   preparation patch set. Re-run the review against the pinned source/profile
   inputs, distinguishing pristine CPython files from Lunar-owned patches.
2. Supply the exact `_lunar_static_main.py` used by the profile, independently
   pin its bytes, and review all of its imports and runtime-selected behavior.
3. Complete a source-level audit of all nine frozen sources and relevant C
   bootstrap/startup code. Resolve every conditional, fallback, deferred, and
   computed import, including the codec-selection policy and external-loader
   paths. Record a finite route or an explicit refusal for each reachable
   dependency.
4. Verify that actual configuration values constrain startup to the reviewed
   routes (including platform, filesystem and stdio codecs, import settings,
   and loader policy). Bind those values to the same source/profile identity.
5. Independently verify generated frozen headers, builtin tables and aliases
   against their reviewed inputs and the final image, then observe actual
   startup module origins and refusal behavior. A descriptor graph or this
   source review alone cannot establish those properties.

Until these gates pass, this document is a **partial source review, not
accepted closure**. It records no successful build, freezer, executable
startup, runtime test, or evaluator result. No provider, WebAgent, remote
evaluator, company evaluation platform, or real solver was used for this
review.
