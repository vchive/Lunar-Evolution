# Explicit pinned-Zig ELF LLD capture profile

## Status and scope

This is a separately selected successor for the two final links in the v4
source-data recipe. It uses the existing pinned `zig` executable's explicit
`ld.lld` subcommand. It does not change the original Zig `cc`, archive, freezer,
compiler-depfile or support-preparation commands. It does not retry a failed
profile, discover a linker or silently fall back to another capture route.

The original failed and unknown attempts remain recorded in
[zig016-link-capture-observation.md](zig016-link-capture-observation.md). Neither
the original five-name support contract nor the standalone-linker profile is
changed. The separate freestanding diagnostic below establishes the direct
entry point for that graph only; an accepted support bundle, configured CPython
build or runtime startup is not established.

## Fixed upstream source research

The official Zig `0.16.0` annotated tag
`44d9672fed001115e674fd5ddb32747ef43a7af4` points to commit
`24fdd5b7a4c1c8b5deb5b56756b9dbc8e08c86a8`. The following small official source
files were read without executing Zig or LLVM:

| Source at that commit | SHA256 |
| --- | --- |
| [`src/main.zig`](https://codeberg.org/ziglang/zig/src/commit/24fdd5b7a4c1c8b5deb5b56756b9dbc8e08c86a8/src/main.zig) | `dd931f83eb6c4747b185185dc8c76e0bc07f7b14361b435c1f1bec212539551b` |
| [`src/zig_llvm.cpp`](https://codeberg.org/ziglang/zig/src/commit/24fdd5b7a4c1c8b5deb5b56756b9dbc8e08c86a8/src/zig_llvm.cpp) | `bcc22a767bc3fd5ebdde792af2e0ab2b946c37327e165f9bc7cff18d6c42da1a` |
| [`src/zig_llvm.h`](https://codeberg.org/ziglang/zig/src/commit/24fdd5b7a4c1c8b5deb5b56756b9dbc8e08c86a8/src/zig_llvm.h) | `6d62a3d01064a0573fcbe17f8423c18735216b1a2acddcb5bb68778ae348ba3a` |

In `main.zig`, lines 218-223 only retain `args[0]` as crash metadata and require
a command argument; line 279 chooses `cmd = args[1]`. Lines 314-319 explicitly
dispatch `ld.lld`, `lld-link` and `wasm-ld`. Lines 6021-6069 identify `ld.lld` as
ELF, require LLVM extensions, remove the Zig executable from the forwarded argv
and call `llvm.LinkELF` directly. `zig_llvm.cpp` lines 515-517 forward that vector
to `lld::elf::link`. This path does not enter Zig's `cc` driver.

Copying or renaming `zig` to basename `ld.lld` does not select that command. With
the existing standalone vector, `-m` would become `args[1]`; basename dispatch
is not present in this fixed source. The successor must retain the explicit
two-token prefix `@toolchain/zig ld.lld`. No wrapper or executable alias is part
of this design.

The fixed binary remains the previously observed 172,641,672-byte file with
SHA256 `2317bbb91798556d9d0f38aabdac23db83f0979b25f767259ae474546724087c`
inside the complete 19,546-file inventory. Source research does not authenticate
that binary's build provenance or prove its actual runtime behavior.

### LLVM 21 capability reference

Official LLVM tag `llvmorg-21.1.0`, annotated tag
`827731c0bf12b0ce8d70e15ebf9f731e7961fe51`, points to commit
`3623fe661ae35c6c80ac221f14d85be76aa870f1`. This is an upstream LLVM 21 capability
reference, not a claim that the pinned Zig binary embeds this exact patch
version. Zig's release notes contain both LLVM 21.1.0 toolchain and Clang 21.1.8
references; those references do not establish the binary's precise LLD build.

| Official file at the LLVM commit | SHA256 |
| --- | --- |
| [`lld/ELF/Options.td`](https://github.com/llvm/llvm-project/blob/3623fe661ae35c6c80ac221f14d85be76aa870f1/lld/ELF/Options.td) | `43f37eb5cf3a609bef5629ed89d536fa4ea5c84aa759f24b608667fcdae17b11` |
| [`lld/ELF/Driver.cpp`](https://github.com/llvm/llvm-project/blob/3623fe661ae35c6c80ac221f14d85be76aa870f1/lld/ELF/Driver.cpp) | `b3fdc6c561d8bbbdee7b85d9425b945d3529dc51b6606f865b8e0ec4739a3d65` |
| [`lld/ELF/InputFiles.cpp`](https://github.com/llvm/llvm-project/blob/3623fe661ae35c6c80ac221f14d85be76aa870f1/lld/ELF/InputFiles.cpp) | `9ffff4796a65217489ddbee86c4ad8740a0d6fa135d685d5db8c50d3b2328614` |
| [`lld/test/ELF/dependency-file.s`](https://github.com/llvm/llvm-project/blob/3623fe661ae35c6c80ac221f14d85be76aa870f1/lld/test/ELF/dependency-file.s) | `18fa29c5b7b22256e9d2a75734532821227048750bcc1b78a687b6dad5d8e9f6` |

`Options.td` lines 10-13 and 185 declare separate and joined dependency-file
forms. Lines 322, 340, 361 and 604 declare `-m`, `--no-dynamic-linker`, `-o` and
the `-static` alias. `Driver.cpp` line 175 explicitly recognizes `elf_x86_64`.
No additional general linker flags are needed for the proposed fixed prefix.

`InputFiles.cpp` lines 219-265 add resolved/remapped file paths to the dependency
set before opening them. `Driver.cpp` lines 2453-2509 write this set in Make
syntax; lines 3387-3390 write the depfile before final ELF emission completes.
Consequently a depfile alone does not prove successful linking. Ordinary archive
paths are included through `addFile` at lines 245-266; member objects are not
separate depfile entries. Thin archive members use `Archive::Child` reads at
lines 195-225, so this capture is not a universal record of all file I/O. Existing
finite input checks must remain in force; this profile cannot expand accepted
archive formats, ambient paths or arbitrary tool behavior. The upstream test
was read as source only and was not executed.

### Separate bounded real entry-point observation

The root development agent separately performed one newly authorized
freestanding diagnostic on 2026-10-30. This was separate from the source-reading
work above and from the new support-bearing profile. The complete original
19,546-file / 357,913,169-byte toolchain inventory matched before and after.
Compilation returned 0 in 0.032176744 seconds, and the explicit `zig ld.lld`
command returned 0 in 0.007747389 seconds. The whole diagnostic took 1.742771950
seconds within its original 120-second absolute budget, with retry 0.

Its actual 164-byte depfile has SHA256
`963176f44c4e994787aeccf53618380cfd3a039a02e9f8daa226655e3c5b0d8a` and reports
exactly the intended ELF target and sole original object, using LLD continuation,
blank-line and complete phony-rule syntax. Its 1,880-byte ELF has SHA256
`198b7c565dad5cbcd50409f4a685ac35d825401291ba84b78aa9a77ef72e8a77` and is
ELF64/x86_64 without `PT_INTERP` or `PT_DYNAMIC`. The generated ELF was not
executed. Original `probe.d` and `actual-summary.json` are retained in the ignored
local evidence directory
`.lunar-evolution/validation/zig-lld-direct-20261030/remote-originals/`;
the summary SHA256 is
`2644651779a303ccc4e6340febf04cede76dc4640586dadced9cfa1daffa16dd`.

This demonstrates that the explicit entry point can emit genuine capture for
the observed freestanding graph. It does not verify the proposed profile's
support bytes, original full support seed, static-musl closure, configured
CPython graph, runtime startup or immutable custody. Those remain unaccepted;
the earlier failures and unknown outcomes are not replaced by this observation.

## Independent finite profile

The canonical profile uses the new schema
`lunar-zig-lld-musl-link-profile-v1`. It has exactly the existing finite profile
fields: `schema`, `target`, `linker_execution`, `crt_mode`, `archives`, `inputs`.
The target is `x86_64-linux-musl`; `linker_execution` is
`static-x86_64-elf`. Canonical encoding, independent expected SHA256, file-count,
per-file and total-byte bounds follow the standalone profile's existing limits.

The sole executable record is `zig`. Its complete pin (`path`, `size`, `sha256`,
`executable`) must equal the `zig` row already present in the independently
pinned complete Zig manifest and base recipe. It is not appended as a duplicate
row, replaced by the profile or accepted by its currently observed digest.
Unknown fields, a missing/mismatched original Zig row and namespace overlap
refuse before dispatch. The original static ELF64/x86_64 check still rejects
`PT_INTERP` and `PT_DYNAMIC`; this does not introduce a host loader or shared
library closure.

Non-executable support records use only `zig-lld/support/`. CRT modes remain
`crt1` or `crt1-crti-crtn`. The explicitly selected ordered archive subset
remains `libc.a`, `libzigc.a`, `libubsan_rt.a`, `libcompiler_rt.a`, with libc and
compiler runtime mandatory. Inputs contain exactly `zig` and the support records
selected by those fields. The selected support files must already be staged
beside the original complete Zig tree and must have independently supplied pins.
They are declarations, not evidence of successful Zig support generation.

The profile's bytes and independent expected SHA256 must be passed separately
to recipe generation, pre-dispatch validation and the original actual-dependency
consumer. Recipe self-consistency, manifest claims, callback DTOs, verbose
dispatch text and current cache digests cannot supply this independent authority.
The existing `lunar-standalone-musl-link-profile-v1` remains a distinct schema;
neither profile is interpreted as the other.

## Commands and original consumer path

Only the v4 source-data entry accepts the new profile. Legacy recipes/consumers
continue to refuse this new schema and command. Both final links must use the
same independently pinned profile and the sole reviewed shape:

```text
@toolchain/zig ld.lld -m elf_x86_64 -static --no-dynamic-linker -o
  @work/bin/lunar-...
  <declared CRT head> <prior work .o/.a inputs>
  --start-group <all declared archives> --end-group <declared CRT tail>
  --dependency-file @work/link-dependencies/bin/lunar-....d
```

The executable and subcommand are separate fixed argv tokens. The two depfiles
are actual bounded outputs of their original link commands. Search paths,
response/config/plugin flags, arbitrary subcommands/options, mixed linker modes,
extra/missing support records and extra output declarations refuse. Compilation,
archive, freezer and the prospective prior-output graph stay unchanged.

The new selection joins the existing runner and dependency consumer path. It
does not create another execution backend, deadline, report or retry loop. The
consumer validates the independent profile against the original Zig row in the
separately pinned recipe. Generation obtains that row through the unchanged
complete-manifest validator; the consumer does not receive or independently
revalidate the original toolchain manifest. It reads the original executable
through no-follow FDs, applies the existing
static ELF gate, rechecks the pin, and calls the selected original v4 runner
once with the caller's original absolute deadline and interruption hook.

Original report persistence/comparison, original and snapshot input FD readback,
every reported output FD readback, compiler dependency comparison, and linker
dependency comparison remain mandatory. Each genuine linker depfile must report
exactly the declared CRT, prior object/archive and selected support inputs for
that link. Missing, unknown, additional, future or ambient entries refuse. No
supplied output inventory or synthetic depfile substitutes for actual readback.

## Non-goals, claims and validation boundary

This slice does not acquire support bytes, change support preparation, repair
the observed `zig cc` seed crash, infer a new generated-cache acceptance set or
complete CPython configuration/build/runtime acceptance. The old required set
of `crt1.o`, `crti.o`, `crtn.o`, `libc.a`, `libcompiler_rt.a` remains exactly
unchanged. No toolchain download, real diagnostics or business case execution
is authorized by this specification itself.

All existing claims remain false: `build_performed`,
`immutable_custody_verified`, `implicit_link_inputs_verified`,
`driver_inputs_verified`, `configured_closure_verified`,
`installation_accepted`, `production_admission`, `online_publication`, and all
existing image/runtime/source-origin protection claims. Pinned source research,
static format inspection, ordinary private files and an inert helper cannot
establish source authenticity, immutable custody or production admission.

Necessary focused coverage includes independent-profile and original-Zig drift
refusal; fixed subcommand/profile grammar; namespace/support sets; v3 refusal;
unchanged default and standalone schemas; both real depfiles' exact sets;
original report/output readback and shared deadline/interruption behavior. An
inert native helper may verify software dispatch/readback wiring when separately
run in the combined regression, but cannot count as real Zig/LLD or CPython
capture acceptance. Real acceptance remains a later explicitly selected,
single-attempt validation with original failures retained and zero fallback.

## Consolidated software verification

Software tree7c4bb0a ran16 complete files on Linux/Python3.12:629unique,
626passed/3new-test fixture failures/0error/0skip,18.565264seconds. Two CRT
vectors omitted the compiler's required existing `lib/` input; one drift
fixture tried writing its0500 original executable before returning the report.
Keep the product refusals and error assertions: add the resource record and
explicitly make only the caller-owned drift fixture writable before replacing
its bytes, then restore0500. Original unsuccessful results stay retained.

Treeb6665f52 changes only that new test file; every product byte and mode matches
the original batch. Its complete53case file passed53/53 with zero failure,
error, skip or retry in2.801458seconds. Current applicable unique passing
coverage is629, not682 or a complete execution on one final tree. The53include
five complete generator-graph cases through the original emitter, both solvers
and both explicit lifecycle source versions; those use synthetic inventories,
not a real CPython/toolchain build.

Both runs verified all2745source files before/after and exact collection/JUnit
keys. Original remote/local22artifact hashes match;287module origins/395exposed
references and268/347 in the supplement match their frozen manifests. Ruff,
compileall and diff checks pass. A preceding `/tmp` inode-exhaustion preparation
failure executed no test bodies; actual tests used a new explicit `/dev/shm`
profile with the same source. Full new-source CI remains required before merge.
Evidence is retained in primary ignored `validation/zig-lld-direct-20261030/`.
