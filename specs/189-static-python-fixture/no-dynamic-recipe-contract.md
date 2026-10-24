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
- dynamic-loading, shared, PIE, `-rdynamic`, `-ldl`, `-Bdynamic`, rpath and
  dynamic-linker flag forms are refused, including GNU/Solaris aliases such as
  `-I` (dynamic linker), `-dy`, `-Bshareable`, `-call_shared`, `-G`, and `-E`;
  GNU/ELF driver/linker upper-case `-R` runtime-search/rpath forms, compiler-
  emitted runtime rpaths and shared sanitizer/runtime libraries are refused as
  well, including when they occur in compile flags a driver may reuse at link
  time. The meaning of `-R` is driver-dependent;
- opaque `-Wl`, `-Xlinker`, compiler `-specs`/wrapper/config/toolchain-override,
  frontend/backend/plugin/offload-linker pass-through, linker script `-T` /
  `--script`, and `@response-file` forms are refused in every recipe flag
  vector. They can inject unbound linker arguments or change the selected
  linker. GCC/Clang offload routing and target, sysroot, resource-directory,
  CUDA, ROCm, and HIP overrides are refused until their inputs are separately
  pinned. Linker `-z` controls, LTO linker output-mode overrides, OpenMP, and
  sanitizer runtime flags are refused by this recipe contract as well;
- these rules are a bounded refusal gate, not a complete compiler-option parser
  or positive allowlist. Other syntactically valid flags may remain in a
  detached descriptor, but parsing them never authorizes configure, compile,
  link, freezer, or runtime execution. G1 must positively pin/admit the exact
  recipe, driver, defaults, target/sysroot/resource inputs and resulting
  artifact before any build or runtime acceptance;
- `CFLAGS`, `CPPFLAGS`, and `LDFLAGS` environment values are checked as
  individual bounded flags too, so they cannot reintroduce a refused option
  through the environment;
- This syntax gate does not bind tool or configuration bytes referenced by
  `CC`, `PATH`, `AR`, `RANLIB`, `CONFIG_SITE`, Zig cache settings, or configure
  probe overrides; nor does it prove the defaults selected by a future driver.
  Feature189 G1 must pin and observe the exact toolchain, cache, configuration
  and recipe inputs before any build can be accepted. This descriptor alone
  never authorizes build or runtime execution;
- link inputs cannot be shared libraries (`.so`, `.dylib`, `.dll`, `.la`) or a
  dynamic loader path; search-based `-l`/`--library` and
  `-L`/`--library-path` flags are refused in every recipe flag vector so
  libraries must appear as exact pinned link-input records;
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
