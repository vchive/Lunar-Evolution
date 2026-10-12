# Feature 193 F02 — static Python build-closure comparison contract

Status: pure bounded DTO/comparator implemented, 2026-10-12. This contract does
not perform or accept a CPython build. It records the evidence shape required
for a later controlled build and rejects a description that cannot be compared
to the F01 installation descriptor.

## Scope

`parse_static_python_build_closure` consumes canonical caller-owned JSON bytes,
independent SHA256 pins, and canonical F01 descriptor bytes. It has no path,
filesystem, process, network, environment, compiler, freezer, linker, ELF
loader, or clock access. It returns an immutable DTO only. Synthetic source,
toolchain, header, object, and ELF records in tests are wire vectors and must
never be reported as a completed build.

The wire schema is `lunar-static-python-build-closure-v1`. Its closed top-level
projection contains `schema`, `installation_version`, `source_identity`,
`toolchain_identity`, `frozen_headers`, `link_closure`, `elf`, and `claims`.
Unknown fields, duplicate keys, non-canonical JSON, non-finite values, deep or
oversized structures, invalid paths, duplicate records, and all non-false claims
are refused with fixed errors that contain no caller data.

## Required evidence projection

`source_identity` contains the upstream tag/commit/tree/archive/patch digests
and an ordered list of source file records. The tree digest is independently
pinned by the caller. `toolchain_identity` contains the target triple and
separately described compiler, linker, archiver, sysroot, libc, and compiler
support records. Its manifest digest is independently pinned and must equal the
canonical projection digest.

`frozen_headers` contains exactly the nine reviewed modules from F01. Every
entry carries a generator id, symbol, package bit, source record, generated
header record, and freezer recipe record. Generated paths are fixed to
`generated-sources/Python/frozen_modules/<generator_id>.h`; the inventory digest
is independently pinned. The contract does not infer header bytes or permit
the old `_lunar_static_main` header to be silently reused.

`link_closure` carries ordered unique object, archive, CRT, libc, and libm
records; compile/link flags; generated `pyconfig.h`, module-config, and link-map
records; the four forbidden stock objects; and a separately pinned manifest
digest. Stock `Modules/getpath.o`, `Programs/_bootstrap_python.o`,
`Programs/python.o`, and `Python/frozen.o` may only occur in the explicit
exclusion list. This is a description of the expected closure, not compiler or
linker output.

`elf` repeats every field of `StaticPythonELFProfile` and adds artifact digest
and size. It requires the no-`PT_INTERP`, no-`DT_NEEDED` projection and a size
at most 128 MiB. The comparator checks those fields but does not parse or open
an ELF image. All capability, build, runtime, installation, input, protection,
and production claims are required to remain false.

## Pins and F01 cross-check

The caller supplies independent pins for the canonical contract, source tree,
toolchain manifest, frozen inventory, link manifest, artifact, and installation
version. Validation checks exact built-in types and bounds before parsing or any
delegation. It then compares source/archive/artifact/ELF fields, frozen source
and generated records, and link paths against the embedded F01 descriptor.
Matching metadata does not establish source-to-object correspondence, configured
Makefile/`pyconfig.h`, complete `LIBOBJS`/`MODOBJS`/`MODLIBS`/`LIBS`/`SYSLIBS`/CRT
closure, frozen header generation, or an ELF's actual bytes.

## Acceptance boundary

Focused tests cover valid immutable DTOs, pin and cross-field drift, missing or
duplicated frozen records, forbidden stock objects, ELF loader fields, claims,
canonical/duplicate JSON, strict bounds, and monkeypatched filesystem/process
APIs. Ruff, compileall, focused tests, and `git diff --check` are required.
F02 production acceptance still requires a separately controlled CPython source
and toolchain acquisition, configured build, freezer output, object/archive
inventory, link map, final ELF byte digest, and independent source/tree audit.
