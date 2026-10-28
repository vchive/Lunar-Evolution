# Explicit standalone static linker capture profile

## Scope and current boundary

The Zig 0.16 dependency-capture failure is recorded separately in
`zig016-link-capture-observation.md`. This opt-in successor replaces only the
two final linker commands with an independently pinned standalone `ld.lld`.
It preserves the original Zig compilation, archive, freezer and compiler-depfile
commands. The existing Zig link recipes and exact five-file support default
remain unchanged. There is no automatic fallback or retry.

The standalone executable must pass the existing static ELF64/x86_64 gate:
neither `PT_INTERP` nor `PT_DYNAMIC` is permitted. A distribution's dynamically
linked `ld.lld` is not a supported input. The original runner cannot express an
external loader and shared-library closure for this profile; this change does
not learn such a closure from the host. Static format inspection and pinned
bytes do not prove every read performed by a trusted linker.

## Finite independently supplied profile

The canonical `lunar-standalone-musl-link-profile-v1` document has exactly:

- `schema`, `target` (`x86_64-linux-musl`), and `linker_execution`
  (`static-x86_64-elf`);
- `crt_mode`: `crt1` or `crt1-crti-crtn`;
- `archives`: the explicitly selected ordered subset of `libc.a`, `libzigc.a`,
  `libubsan_rt.a`, `libcompiler_rt.a`, including libc and compiler runtime;
- `inputs`: sorted nonempty regular-file pins (`path`, `size`, `sha256`,
  `executable`) for exactly the selected support files and the sole executable
  `standalone-linker/bin/ld.lld`. Support files use the fixed
  `standalone-linker/support/` namespace and are not executable.

The allowed extra archive names are declarations, not evidence that an observed
Zig invocation consumed them or that any combination can build CPython. The
chosen profile must be supplied separately with its expected SHA-256 to recipe
generation, pre-dispatch validation and the original dependency consumer. A
recipe's self-consistent manifest or caller DTO cannot supply that independent
pin. The files must already be staged beside the original complete Zig tree;
the consumer verifies their original pins through no-follow FDs. No package,
download URL, discovered binary or currently observed digest becomes authority.

## Commands and actual-output integration

Both links have the sole reviewed shape:

```text
@toolchain/standalone-linker/bin/ld.lld -m elf_x86_64 -static
  --no-dynamic-linker -o @work/bin/lunar-...
  <declared CRT head> <prior work .o/.a inputs>
  --start-group <all declared archives> --end-group <declared CRT tail>
  --dependency-file @work/link-dependencies/bin/lunar-....d
```

The dependency flag and output reference are separate argv tokens, using the
existing v3 expansion mechanism. Search paths, response files, config/plugin
flags, arbitrary linker options and unknown/missing/additional support records
refuse before dispatch. Both links must use the same profile and declare the
image and bounded depfile outputs.

`run_dependency_checked_build` retains its original execution path: one original
v3 runner call, the caller's original absolute deadline and interruption hook,
original persisted report comparison, FD readback of original/snapshot inputs
and every reported output, and original compiler/linker dependency comparisons.
The standalone executable receives a pinned read, the existing static ELF gate,
then another pinned read before this runner is called. Its linker depfile must
contain exactly the declared CRT, object and archive inputs; unknown, ambient,
future, missing and additional entries refuse. No synthetic depfile or supplied
output inventory can substitute for actual runner output readback.

## Claims and validation

This is an explicit trusted-tool byte-comparison profile. All existing build,
driver-input, custody, configured-closure, installation, production and online
publication claims remain false. It does not establish standalone linker source
authenticity, immutable custody, a CPython build, runtime startup or production
admission. A successful inert native helper test only checks dispatch and
consumer wiring; it is not real `ld.lld` or CPython capture acceptance.

Focused regression covers preserved compilation/default recipes, finite profile
and independent pin refusal, direct-link command grammar, exact depfile input
sets, pre-dispatch loader refusal, original report/output readback and the single
deadline with no retry. Actual-process positive fixtures require Linux x86_64
and a local compiler capable of creating a static inert helper; unsupported
hosts skip that fixture without relaxing the product gate. The root development
task runs the combined regression after all parallel edits are complete.
