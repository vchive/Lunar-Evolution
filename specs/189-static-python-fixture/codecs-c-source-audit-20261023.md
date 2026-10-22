# Feature 189 — bounded `_codecs` C-source fixture audit (2026-10-23)

The inert fixture
`tests/fixtures/static_python_source/Modules/_codecsmodule.c.source` is the
exact `Modules/_codecsmodule.c` member observed from the pinned CPython 3.13.12
archive. It is 33,553 bytes with SHA-256
`149a20c2d7aee22281ddd8756ae7eae685ae0ef21764138d41f367443182041e`; the
member identity is recorded in `provenance.json`.

The source text identifies the `_codecs` module definition, its
`_codecs_functions` table, and `PyInit__codecs`, which returns
`PyModuleDef_Init(&codecsmodule)`. The focused test checks those byte-level
observations without compiling, loading, or executing the source.
It also pins the direct include spelling and the `MS_WINDOWS` guard surrounding
`windows.h`; the target preprocessor configuration and bytes/resolution of
`Python.h`, `pycore_*`, or the generated clinic header are not validated here.

The supporting inert `Modules/Setup.bootstrap.in` archive member is 971 bytes
with SHA-256
`bb401f9494c2f896aa40af6a8077ff9f22b99a9d4126ce38daef759427c8df88` and
contains the declaration `_codecs _codecsmodule.c`. This is an upstream
template observation only; it does not establish generated `Setup.bootstrap`
or its consumption by a configured Lunar build.

The synthetic installation descriptor independently names `_codecs` with the
same initializer symbol. Its source/object records are deliberately different
synthetic metadata and are not replaced by this fixture. This slice therefore
does not prove generated builtin tables, C headers or macros, object bytes,
link inclusion, final ELF symbols, or runtime module origin. Build, startup,
and production-admission claims remain false.

