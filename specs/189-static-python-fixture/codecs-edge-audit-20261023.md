# Feature 189 — bounded `codecs` → `_codecs` source-edge audit (2026-10-23)

## Scope and pinned input

This note reviews one import edge in the fixed CPython 3.13.12 Python source
fixture `tests/fixtures/static_python_source/Lib/codecs.py.source`. The exact
input is 36,978 bytes with SHA-256
`2f278497548b8313580b247a1097a0a304e5087a355ebb11a92ec685fa9e63ff`, matching
the existing pin in
[`test_static_python_prepared_source_import_profile.py`](../../tests/test_static_python_prepared_source_import_profile.py).
It does not authenticate or reacquire the upstream archive, execute the source,
inspect a C extension implementation, or establish what any configured build
consumed.

## Observed edge and profile comparison

At `Lib/codecs.py:16`, the pinned source uses `from _codecs import *`. The AST
observer records the base `codecs → _codecs` `from-import` edge. A separate
comparison against `specs/189-static-python-fixture/wire-v1-example.json`
finds an `_codecs` entry in the descriptor's `builtin_modules`, with init
symbol `PyInit__codecs`. The descriptor labels itself
`synthetic-parser-and-ELF-format-only-never-executed`; this comparison checks
that the candidate profile declares the expected module, not that the target
inittab or linked object contains it.

The observer also retains the exact unsupported site
`{source: "codecs", line: 16, column: 4, reason: "star-import"}`. The generic
observer does not expand wildcard exports, and this audit does not weaken that
rule or treat the base edge as a complete enumeration of imported names.

## Remaining limits

The `_codecsmodule.c` initializer, its exported names, its transitive C/runtime
dependencies, generated builtin table, compiled object and runtime module
origin have not been audited or bound here. The descriptor's `_codecs` source
and object records are synthetic metadata, not those inputs. The audit closes
only the bounded source-to-candidate-inventory comparison for this one edge;
it does not close the Python/C startup graph, configured closure, build, ELF,
runtime startup or production acceptance. All production and online-publication
claims remain false.
