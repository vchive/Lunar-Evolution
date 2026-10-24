# Feature 189 — bounded core `_warnings` C-source audit (2026-10-23)

`tests/fixtures/static_python_source/Python/_warnings.c.source` is the exact
`Python-3.13.12/Python/_warnings.c` member observed from the CPython 3.13.12
archive already identified in `provenance.json`. The archive SHA-256 is
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`; the
member is 43,088 bytes with SHA-256
`bed91ba65456a2bc1ca278a4d320be978487563a566c79a9e57b0bf46c40352d`. The
bytes are inert test data. The archive's `Modules/Setup.stdlib.in` member is
also retained and pinned as a supporting template.

The source defines `MODULE_NAME` as `_warnings`, names that module in its
`PyModuleDef`, and exposes `_PyWarnings_Init`, which returns
`PyModuleDef_Init(&warnings_module)`. Lunar's emitted `Modules/config.c` names
the same initializer. The emitted `LUNAR_CORE_BUILTIN_SOURCES` includes
`Python/_warnings.c`; the source does not appear in
`LUNAR_STATIC_MODULE_SOURCES`. Neither retained `Setup.bootstrap.in` nor
`Setup.stdlib.in` contains an `_warnings` declaration, consistent with the
core-builtin path in this candidate metadata. The synthetic installation
descriptor carries `_PyWarnings_Init` for `_warnings` separately from these
upstream source bytes.

`get_warnings_attr()` conditionally attempts to import the Python-level
`warnings` module when `try_import` is true and the interpreter is not
finalizing. The current finite profile includes `_warnings` but excludes
`warnings`, so this remains an unclosed source-level profile edge. This audit
does not establish whether that branch executes in target startup or workload
paths.

The pinned source has two `try_import=1` call sites. `call_show_warning()` is
reached only after warning processing selects an item for display. If the
Python hook is absent, or importing `warnings` fails with `ImportError`, the
source uses C `show_warning()`; other import errors remain errors. A present
hook must be callable, and its `WarningMessage` lookup does not import the
Python module. `_PyErr_WarnUnawaitedCoroutine()` tries the Python coroutine
hook during coroutine finalization, then writes hook errors as unraisable and
uses `_PyErr_WarnFormat()` unless the hook succeeded or raised
`RuntimeWarning`. That C fallback can itself reach `call_show_warning()`, so
it does not prove that the Python-level import edge is unreachable.

The candidate profile pins `warnoptions=[]` and `site_import=0`, which rules out
the corresponding configured startup imports at the metadata/source level.
It does not establish the configured runtime values or whether the fixed
workload can emit warnings or finalize an unawaited coroutine. Keep
`warnings` excluded from the expected startup inventory for now, while leaving
the complete workload/profile disposition open for actual startup and lifecycle
evidence. The `_warnings.c` fixture/test itself does not contain the Python
handler or external coroutine-finalization caller. Separate supporting source
fixtures now pin both paths: `Lib/warnings.py` prefers `_warnings` and implements
`_warn_unawaited_coroutine()`, while `Objects/genobject.c` calls the C hook only
for a coroutine whose frame is still `FRAME_CREATED`. The helper imports
`linecache` and `traceback` only when `coro.cr_origin` is present, then calls
`warn(..., RuntimeWarning, source=coro)`. These bytes establish a conditional
source path, not whether that path is reachable in the fixed target workload.

If `warnings` is admitted or imported by a future profile, its source also has
conditional `linecache` and `tracemalloc` paths; coroutine-origin formatting
adds `traceback`. The source-only fixture deliberately does not expand the
finite module inventory or assert those dependencies are safe for the target.
The supporting `Lib/warnings.py` fixture is also passed through Lunar's bounded
Python AST import observer. It records ten supported static import edges to
`_warnings`, `builtins`, `functools`, `inspect`, `linecache`, `re`, `sys`,
`traceback`, `tracemalloc`, and `types`, plus the unsupported dynamic import at
line 267 (`__import__(module, ...)`); no imports are unresolved. The result keeps
all closure/runtime claims false. Static edges do not encode their branch
conditions, while adjacent source assertions pin selected local guards and
ordering. This observation remains separate from the finite startup profile.

The checks establish source-member identity and consistency with retained
candidate metadata only. They do not verify headers, configured Setup or
`pyconfig.h`, actual source consumption, compilation, linking, ELF contents,
runtime module origin, or production admission. No build or target execution
was performed.
