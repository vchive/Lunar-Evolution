# Opt-in retained link-object format checks

Status: implemented; focused regression and retained real-byte observation
complete, final-source full CI pending. No
compiler, linker, generated image, solver or model execution is part of this slice.

The existing direct-LLD profile pins support bytes but does not interpret archive
or CRT contents. Add an explicit stricter consumption path for those same bytes
and the original recipe's `libraries/liblunarpython.a`. Keep all old APIs,
defaults, profile bytes, report versions and candidate bytes unchanged.

## Finite format

Accept ordinary GNU ar only, at most 128 MiB and 4096 inline object members.
Validate every 60-byte header, payload extent and newline padding. Accept short
names, an optional GNU long-name table and one optional 32- or 64-bit GNU symbol
table. Long-name references must name entry starts; symbol-table offsets must
name real inline object headers. Names are bounded canonical relative paths:
retained Zig archives use `.zig-global-cache/o/<hash>/...o` names, which are
embedded names rather than external files. Refuse thin archives, BSD extensions,
absolute/parent paths, scripts, unknown special entries and incomplete/trailing
data. No archive member is extracted, resolved or opened by its name.

Every inline member and CRT must have a bounded little-endian ELF64 x86_64
ET_REL header, no entry point/program headers/dynamic tables, supported ordinary
section numbering, bounded section extents and valid section/string/relocation
table relationships. Symbol string/section/value ranges, relocation symbol/target
offsets and group indices are checked. At most 4096 sections, 262144 cumulative
symbol/relocation/group entries and 128 MiB per object are accepted.
This is a structural format profile, not symbol-resolution, relocation execution,
machine-code correctness or provenance verification.

Explicitly refuse `SHT_LLVM_LINKER_OPTIONS` (0x6fff4c01) and
`SHT_LLVM_DEPENDENT_LIBRARIES` (0x6fff4c04), regardless of section name: these
can name additional link inputs/search paths. Also refuse `SHT_LLVM_LTO`
(0x6fff4c0c), whose embedded LTO/ThinLTO bitcode route is outside this native-
object profile. The latter is not described as a direct file-path directive;
LLD's fat-LTO option is disabled in the fixed link grammar. Retain the observed
`SHT_LLVM_ADDRSIG` (0x6fff4c03) and x86_64 unwind (0x70000001) metadata.

The fixed upstream references are LLVM `llvmorg-20.1.8`:
[ELF extensions](https://github.com/llvm/llvm-project/blob/llvmorg-20.1.8/llvm/docs/Extensions.rst)
lines 248–306 and 550–555;
[ELF types](https://github.com/llvm/llvm-project/blob/llvmorg-20.1.8/llvm/include/llvm/BinaryFormat/ELF.h)
lines 1136–1150;
[LLD input parsing](https://github.com/llvm/llvm-project/blob/llvmorg-20.1.8/lld/ELF/InputFiles.cpp)
lines 380–395 and 592–609; and
[LLD driver](https://github.com/llvm/llvm-project/blob/llvmorg-20.1.8/lld/ELF/Driver.cpp)
lines 233–243, 1264–1265 and 1295–1296. These explain known input routes;
they do not authenticate the selected Zig binary or prove all driver routes.

Loops and incremental hashes use the original deadline/cancellation checkpoint.
No subprocess, file discovery, environment lookup or external-member read occurs.

## Original consumption paths

`stage_zig_lld_support_selection_object_format` verifies the existing independent
selection/profile pins and every selected byte before creating the fresh support
namespace. It then uses the existing stage/readback path; it does not generate or
select replacement support. The old staging API retains its behavior.

`prepare_worker_input_view_object_format_fixed_installation_description` retains
the original worker-view execution-v8/dependency-v7 validators and both original
FD readback rounds. It additionally requires the independently pinned direct-LLD
profile to match the original recipe and both links, checks the pinned original
support/CRT bytes and the original recipe's `zig ar rcsD` library output, and only
then returns the existing unaccepted candidate. It writes and executes nothing.
Missing/mixed history, profile, graph, files or format refuses. Present readback
does not establish original execution-time consumption or immutable protection.

All custody, complete driver/configured closure, installation, admission and
publication claims remain false. Real support headers were inspected read-only
before selecting this grammar; passing fixtures is not real-build acceptance.

## Batch validation

Cover GNU short/long and 32/64-bit symbol tables, inline relative paths, malformed
offsets/counts/padding, thin/script/external members, wrong ELF type/architecture,
section overflows, checkpoints, and actual staging/retained consumption. Preserve
old API behavior and candidate bytes. Run focused tests, Ruff, compileall and diff
checks once after this code/test batch; no CPython rebuild is needed for parser
regression. Any later real full-build acceptance remains a separate exact plan.

The first frozen nine-file run at `ec4de6b6` retained 513 passes and three
fixture `PermissionError` failures among 516 exact nodes, with no skips. The
three failures occurred when repinning an already read-only simulated tool.
Successor `481a7430` only made that fixture writable before rewriting it and
restored the original final mode. Its complete 102-node new file passed;
product bytes and test-body/parameter AST were unchanged. These are two
executions, not one all-passing 516-node invocation. Both source inventories,
JUnit identities and failure preservation were independently audited.

A separately reviewed once-only read-only observation of seven retained real
materials passed at `481a7430`: five ordinary archives containing 1281 inline
objects and two CRT objects. It took 2.361669 seconds of its original 120-second
budget, with zero retries and a reaped direct child. Both original archives
were streamed without extraction; all 2784 source files were compared before
and after. Only the two exact parser modules were loaded through an explicit
empty namespace, without package initialization. This checks present formats;
it does not exercise the stricter retained-candidate API on the complete
original build history or prove original execution-time consumption.

Evidence is under the main workspace ignored validation root
`support-object-format-20261031/`. Focused originals audit SHA256:
`8594905e1b394eec314540bf55df82e96a83b4e03bb496c32b73e8819795777a`;
real-byte observation audit SHA256:
`aaaf514ff21862159cdc43568ecba9032ef49ed501c2db0cf6c8fc2fd346eedd`.
The subsequent test-only import sort does not change assertions or product
bytes. Ruff, compileall and diff checks pass. Complete driver/configured
closure, immutable custody and runtime/installation authority remain false.
