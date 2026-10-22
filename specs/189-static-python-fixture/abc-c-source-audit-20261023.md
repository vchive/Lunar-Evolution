# Feature 189 — bounded `_abc` C-source fixture audit (2026-10-23)

The fixture
`tests/fixtures/static_python_source/Modules/_abc.c.source` contains the exact
`Modules/_abc.c` member bytes read from the previously pinned CPython 3.13.12
archive. The archive SHA-256 is
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`; the
member is 27,112 bytes with SHA-256
`a4abd74e245af77f5a8c40ac8d443153ff8636e4e10a8578e9dddecaa3d0b9e8`.
These bytes are retained as inert test data with the member pin in
`tests/fixtures/static_python_source/provenance.json`.

The source declares module name `_abc` and initializer `PyInit__abc`, which
returns `PyModuleDef_Init(&_abcmodule)`. The pinned `Setup.bootstrap.in`
template contains `_abc _abc.c`. Lunar's candidate emitted metadata also has
an `_abc` / `PyInit__abc` table row and lists `Modules/_abc.c` and
`Modules/_abc.o` in its explicit source/object plan. The synthetic descriptor
uses the same module and initializer names, while its source/object records
are separate metadata values.

This cross-check establishes source-member observations and consistency among
the template and candidate metadata only. The archive member's presence and
the inert copy do not establish configured Setup consumption, compilation,
linking, ELF contents, or runtime module origin. The descriptor's placeholder
source/object digests are not hashes of this fixture or a compiled object.
Build, runtime, and production-admission claims remain false.
