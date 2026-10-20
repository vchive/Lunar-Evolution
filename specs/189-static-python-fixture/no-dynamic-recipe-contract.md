# Feature189 no-dynamic recipe contract

This contract is a pure descriptor gate. It runs before any source, toolchain,
filesystem, compiler, linker or freezer operation and does not establish that a
future build is static. The machine-derived ELF gate still has to observe an
actual artifact with no `PT_INTERP` and no `DT_NEEDED`.

The installation descriptor's `recipe` must contain the reviewed static and
non-PIE intent:

- configure flags include `--disable-shared` and `--without-ensurepip`;
- compile flags include `-fno-PIE`;
- link flags include `-static` and `-no-pie`;
- dynamic-loading, shared, PIE, `-rdynamic`, and `-ldl` flag forms are refused;
- link inputs cannot be shared libraries (`.so`, `.dylib`, `.dll`, `.la`) or a
  dynamic loader path;
- flags are unique, contain no whitespace, and environment values use the
  bounded deterministic character set.

The existing environment name allowlist remains in force. This gate does not
require `reproducibility=byte-identical`: `not-tested` is honest while the
source, toolchain and output bytes remain unobserved. It also does not infer a
toolchain or source identity from these flags. A matching descriptor is still a
pending recipe until independently pinned source/toolchain receipts,
configuration, generated tables, link inputs, ELF bytes and Linux lifecycle
evidence exist.

The parser returns fixed `static_python_installation_recipe` or
`static_python_installation_environment` refusals and never includes caller
paths, command text or credentials in an error.
