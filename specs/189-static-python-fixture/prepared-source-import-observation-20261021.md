# Feature 189 — prepared frozen-source import observation (2026-10-21)

## Scope and binding

This note records one provider-free source-only check over the nine Python
sources named by the fixed frozen profile. Eight inputs are inert CPython
3.13.12 `.source` fixtures, whose archive identity and limitations are recorded
in `authenticated-source-import-audit-20261021.md`. Five of those paths are
passed through the installation-owned `prepare_static_python_sources` policy;
the four Python postimages are the exact bytes supplied to the observer, while
the prepared C postimage is pinned separately. The remaining four Python files
(`_frozen_importlib`, `codecs`,
`encodings.utf_8`, and `io`) are unchanged fixture preimages. The ninth input is the
expanded Lunar `_lunar_static_main` emitted by the reviewed freeze task and is
pinned independently by that task.

The check is implemented in
`tests/test_static_python_prepared_source_import_profile.py`. It does not
read a host installation, infer modules from a runtime, execute source, run a
freezer, configure or compile CPython, inspect an ELF, or modify the fixed
profile. It only proves that the observer receives the byte strings whose
postimage/task digests are asserted by the test.

## Inputs and result

The preparation policy emits five postimages. Four are Python sources scanned
here; the fifth is the prepared C `Python/import.c` input and is checked for
identity but is intentionally outside this Python AST observer:

| Source module | Size | SHA-256 |
| --- | ---: | --- |
| `_frozen_importlib_external` | 64,722 | `2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab` |
| `abc` | 6,468 | `a6684b1a49cfbc9c64caeeac7e55ef8f35052b8e8ca93a091941817cdc510b1c` |
| `encodings.__init__` | 1,101 | `47a11d930321492bca552eed29dad061ed6739bf84c919485453315d911b1c60` |
| `encodings.aliases` | 802 | `43aadac378861c1bbdaaf04be8e1bb7d878529a7641ec123b5df4eccdd4c6106` |
| `Python/import.c` (not scanned as Python) | 146,559 | `58a5fac8fac5916511f890f3fdd095d817e6f32ab709ebf0ed0becf9328226b1` |

The AST observer receives nine source modules and reports 28 ordinary/from
import edges, no unresolved imports, and four bounded unsupported sites:

- dynamic `exec` in `_frozen_importlib`;
- dynamic `compile` in `_frozen_importlib_external`;
- the retained `from _codecs import *` in `codecs`;
- the fixed loader-negative computed import in `_lunar_static_main`.

The canonical observer wire digest is
`d7802d7ac60202b720c30bacfb124fe8ee155298ac88ddd8facdbbc7f07dc9f5`.
The prepared `abc` source has no `_py_abc` fallback edge, and the prepared
`encodings` source has no computed codec import edge; those observations are
limited to this source scan.

## Acceptance boundary

This is not a complete import graph or startup-closure proof. It does not
resolve platform branches, C-created modules, generated frozen headers,
configuration, compiler/link inputs, loader behavior, runtime module origins,
or the final image. Every observer capability claim remains `false`. A future
G2/G3 acceptance must independently audit and bind those inputs before any
build, runtime, installation, owner/lifecycle, or production claim is made.
