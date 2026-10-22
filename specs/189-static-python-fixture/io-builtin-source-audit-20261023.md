# Feature 189 — bounded `io` → `_io` source-edge audit (2026-10-23)

## Pinned source and entry declaration

The inert fixture
`tests/fixtures/static_python_source/Modules/_iomodule.c.source` is the
`Modules/_io/_iomodule.c` member observed from the pinned CPython 3.13.12
archive. It is 24,972 bytes with SHA-256
`9d04adc6fd2b493f3a7de3b519abbfd60476b209ccd3428eff4ed1cdf06cbaf2`.
The test checks the source's `_PyIO_Module` definition, exported module name
`io`, and `PyInit__io` initializer returning `PyModuleDef_Init`.

The retained upstream `Modules/Setup.bootstrap.in` template declares `_io`
with seven source files, including `_io/_iomodule.c`. The emitted Lunar
candidate table plan declares `_io` with `PyInit__io` and includes the same
seven paths in its explicit static-source list. The synthetic descriptor
separately names its builtin `_io` with `PyInit__io`. This cross-check catches
inconsistency among the pinned C declaration, source-template entry, Lunar
plan, and candidate metadata.

The name difference is intentional: CPython's inittab key is `_io`, while the
module definition sets `m_name` to `io`; this source audit records both strings
without asserting target initialization behavior.

## Limits

The existing prepared-source AST observer records `io → _io` and
`_frozen_importlib_external → _io`; the source-derived startup-root audit also
records `io` as a primary root for sys streams and `open`. This slice does not
prove the other six source files are built, generated `Setup.bootstrap` or
`Modules/config.c` contents, object bytes, link inclusion, header resolution,
runtime origin, or startup success. The template and descriptor remain
metadata/source evidence, not build receipts. Production and online-publication
claims remain false.

