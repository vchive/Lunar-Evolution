# Validation contract — preparation is not runtime evidence

## Exact 3222c9d original-budget replay and row parsing follow-up

The unprofiled local case passed in 456.82 seconds on exact
`3222c9d78f96ce484ca31d88969ee759c675a798`. The independent Linux case still
failed under the unchanged 600-second control: case 600.945 seconds, suite
602.633 seconds, wrapper 602.921350 seconds. The error is
`SolveExecutionBudgetExceeded` at `rsi_brs_before_evidence`, observed elapsed
600.311864 seconds, through `_before_control_live` / `_mailbox_observe` /
`retain_mailbox_observation`; the worker additionally reports an unknown attempt.
All 2,310 regular source files and executable bits matched the exact Git archive
`f387086caa909a0e66b226172853a4e3986774770d95db67449103a714ca99e0`.
Complete raw evidence is retained in ignored `linux-mixed-3222c9d-nzbqln_7/`,
with all transferred result hashes independently checked.

The admission-row follow-up removes a second serialization already performed by
the complete fresh parser. An exact-str guard retains canonical-BLOB rejection
in SQLite's non-STRICT TEXT column. The 17 new cases and independent review
pass, including same-length drift, noncanonical/duplicate JSON, digest drift
and independent column bindings. The row/admission/BRS publication recovery,
prepared-pin and evidence-composition selection passes 260 cases; the local
run reports the existing 27,483 cleanup warnings and exits zero. A two-row
microbenchmark invokes `to_json` six times before and four after; this is no
end-to-end acceptance. Neither the Linux 600-second gate nor final-source CI
is closed by these local checks.

## Complete extracted toolchain tree observer

The API in [`toolchain-tree-observation.md`](toolchain-tree-observation.md)
reuses the original complete manifest wire and checks actual files, directories,
modes, sizes and hashes through no-follow directory descriptors. Internal stat
pins remain private to the sequential walk. It rechecks names, inventories and
held ancestry and closes its descriptors before returning; immutable custody
and future build-consumption claims remain false.

The 58 implementation cases and 14 independent review fault cases pass. The
related archive, manifest, staged-source and toolchain selection passes 353
cases with zero failures/errors/skips. Independent review covers ancestor/root
replacement, late same-length content changes with restored mtime, each partial
acquisition boundary, primary-error retention and redacted clock failures.
Whole-repository Ruff, src/tools/tests compileall and diff check pass. The
204-case deterministic regression-runner suite passes as well, reporting the
existing 27,483 macOS cleanup warnings from older read-only temporary trees.
The dedicated CI gate requires all 72 new cases without skips. These selections
overlap and are not additive. Exact-source three-version Linux CI remains an
open gate. No configure, build, freezer or runtime was executed.

A single real Linux replay of exact `c00632fb7270da7acea087a75f54b7d2feae233d`
(the same Git tree as cherry-pick `5af81663`) passed in 1.515601 seconds under
one original 120-second deadline, exit 0 and empty stderr. The historical
independent manifest pin `b988925a…93b90` matches all 20,832 members, including
19,546 files, 1,286 directories and 357,913,169 file bytes. The 1,012-byte
canonical observation SHA-256 is
`85d77ae0768e0e7afd6f749a315b4b768f41c863afb53fed794bfe5e770e1571`.
Two independent reviews after transfer verified every retained artifact hash,
tar commit, source module hashes, canonical manifest/record, counts, root stat
and ten false claims. Complete raw evidence is retained under ignored
`toolchain-tree-c00632fb-20261022T224051Z-1f3a33ca/`. The source archive SHA is
`7255afff764321cd2d3b6652b7af3f4ca838302f43effbc8b26b5c7a8857e01b`.
The original tree was not modified and no Zig/configure/build tool was run.
This proves a sequential directory comparison only; immutable custody and
future configured-build consumption remain open.

## Original-budget BRS mixed serial performance follow-up

The exact `cfd76f8` three-child mixed case passed locally in 468.41 seconds
under the original 600-second control and failed on Linux in 602.75 seconds
with `rejection_control_expired`. Raw first-failure evidence is retained under
the ignored `linux-mixed-cfd76f8-k2sex269/` directory; a stack-only sampler was
then run once against that exact source to identify repeat validation costs.

The bounded fixes preserve each SQLite read, JSON parse, row/revision/parent
chain and reference validation, while keying the pure checkpoint digest cache
by exact persisted text (128 entries / 16 MiB conservative budget). They also
allow the source extraction LRU to hold 1,024 entries within the prior 24 MiB
source-text ceiling; all fresh byte reads, source ownership checks, hooks and
live configurations remain. Separate tests cover content/history drift, exact
keys, concurrent cache misses and bounded eviction. The combined cache,
store, identity, drift and checkpoint selection passed 129 cases. The new
checkpoint cache file separately passed 20 cases; the source-cache/identity/
fingerprint/durable-flow selection passed 94 cases. These suites overlap and
are not additive. Independent cross-review of both cache changes passed.
Ruff, compileall and diff checks passed. The original-budget Linux case must
still pass on the final implementation; no timeout, policy or admission check
was weakened.

## Complete toolchain archive observation — 2026-10-23

The bounded API in [`toolchain-observation.md`](toolchain-observation.md)
retains the existing complete extraction manifest with a separate canonical
record. Its 52 inert cases pass, including exact pin and profile boundaries,
clock errors and deadlines through final return, detached output and an exact
archive-field type check before comparison. Independent review reproduced the
hostile comparison failure before that check was added and confirmed the
regression passes afterward. The combined existing archive and new toolchain
selection passes 118 cases with zero failures/errors/skips. Whole-repository
Ruff, src/tools/tests compileall and diff check pass. CI has a separate 52-case
no-skip gate. No source-readiness or admission wire changes.

The earlier real archive replay using the existing public archive APIs retained
3,926,082 canonical manifest bytes, independently matching the previously
committed pin and all 20,832 member records. It is described in
[`toolchain-layout-audit-20261023.md`](toolchain-layout-audit-20261023.md).
That earlier replay does not validate the new deadline-bound record API. A
separate real-input replay of exact b93787c did validate the new API: both
snapshot acquisition and observation used one original 120-second deadline,
finishing in 3.838545438 seconds, exit 0 and empty stderr. The complete manifest
still matched the independent historical pin. Its canonical observation record
is 1,011 bytes, SHA-256
`a55c4bf8a3253a5f9cc318e207c94b6029d03f7f50f1b5c2a783f476f844a718`.
All member counts, byte totals, source identity, validated metadata, unperformed
signature and seven false claims were independently checked after transfer.
Full raw artifacts are under ignored
`.lunar-evolution/validation/feature189-20261023/toolchain-deadline/`.
Neither operation establishes extracted
toolchain custody, compiler consumption, configured build or runtime acceptance.

The original final-source `cfd76f8` three-child mixed serial regression passed
locally in 468.41 seconds with the unchanged 600-second execution control.
The Linux replay failed in 602.75 seconds with `rejection_control_expired`.
The diagnosis and narrow remediation contract are in
[`serial-regression-performance.md`](serial-regression-performance.md);
Linux regression and final-head three-version full CI remain open gates.

## Fixed configure candidate and RSI pin-chain integration — 2026-10-23

The candidate assets in [`configure-candidate.md`](configure-candidate.md)
now emit explicit GNU-build/musl-host argv, feature-disable cache policies,
clean-environment planning data and the complete 103-name pinned-template
disposition (9 static enabled, 94 disabled). The build plan records and reads
back all three assets before publishing its manifest or either entry point.
Both entry points still exit 78 even with execution opt-in.

All 10 new focused cases passed; the combined existing build-input/recipe/
source-plan and candidate gate passed 100 cases. The wider 13-file RSI
source/profile/contract/mock-driver/backend/readiness chain passed 784 cases
with no failures/errors/skips. The independently fixed source-plan, overlay
and preparation hashes were refreshed after reviewing the two changed original
source-file records. Reconstructing those two records with their old values
reproduced the old canonical source-plan digest; restoring the corresponding
two preparation pins reproduced its old digest. The 11 source inputs, 6 output
assets, launch policy and initialization fields are unchanged. No wire or
runtime authority was expanded. These suites overlap and are not additive.

The first combined run retained 113 fixture errors caused by the old
source-plan pin. It is not a passing result; the later complete 784-case run
is the final passing evidence. Local logs, XML and the reconstruction receipt
are retained under ignored `.lunar-evolution/validation/feature189-20261023/`.
Ruff for the whole repository, `compileall` for src/tools/tests and
`git diff --check` passed after the final changes.

A collection audit checked all 50 fixed CI inventories. Two existing ceilings
were stale: selected service/wait 39→43 and Python preparation 243→463. Both
corrected selections passed locally (43 and 463 cases); their macOS runners
reported the existing 27,483 read-only-temporary-tree cleanup warnings and
exited 0. The build-input gate now includes the 10 candidate cases and requires
100 with zero failures/errors/skips. Final-head Linux CI is still required.

The separate [`toolchain-layout-audit-20261023.md`](toolchain-layout-audit-20261023.md)
records actual Zig/musl/CRT/source layout and upstream cross defaults. It is
not complete retained toolchain custody or observed compiler consumption.
No configure, compiler, freezer, target, evaluator or solver was executed for
this slice. G1 complete custody/recipe/closure and G2/G3 acceptance remain open.

## G0 descriptor contract review — 2026-10-23

[`descriptor-contract-review-20261023.md`](descriptor-contract-review-20261023.md)
freezes the existing v1 field/bound contract after comparison with the parser.
The external descriptor/version/artifact pins remain three distinct caller
inputs; no fourth target-profile argument or new runtime API is introduced.
Nested provenance, toolchain, recipe, generated-module and ELF fields remain
declarations until separately observed. The profile accepts exactly 9 frozen
modules, 19 builtins, 2 aliases and an empty embedded-startup array.

The installation, artifact, build-closure and startup-closure suites passed all
568 collected cases on local CPython 3.13.12 (process exit 0). Ruff on the four
corresponding production modules, `compileall` for `src/lunar_evolution`, and
`git diff --check` passed. This is G0 shape/consistency validation; G1 source/
toolchain custody, the fixed configure recipe, full closure, G2 build/ELF and
G3 runtime/lifecycle acceptance remain open.

The separate failed configure diagnostic and original logs are retained in
[`real-build-probe.md`](real-build-probe.md#failed-configure-diagnostic-2026-10-23).
Its unrecognized `--with-system-ffi=no`, host build-Python version mismatch,
missing cross-compilation device cache answer and absent Makefile do not
establish a usable recipe, clean staging, build or runtime result. No cache
answer or configure rerun was used for this contract review. Production and
online-publication claims remain false.

## Snapshot-bound create-only source staging

The `source-staging.md` continuation uses inert USTAR/XZ bytes containing the
three licensed source fixtures plus unchanged/empty files and explicit/implicit
directories. Its externally retained inventory pin is computed by the fixture
harness independently from observer output. The101-case dedicated gate verifies
the actual complete byte-to-postimage-to-filesystem chain and result stat/digest
pins, one strict decode, scalar/manifest/preimage/profile refusals before I/O,
create-only destinations, ancestor/inode/link/mode drift, short/partial writes,
fsync/readback and extra-entry failures, original deadline throughout final
callback/verification/FD cleanup and detached results. Final callback drift
tests require actual file/directory drift codes, not a generic clock failure.
Cleanup uncertainty must preserve a write refusal or refuse a successful path,
including invocation from within a caller's already-handled exception block.

Final local Python3.11.15 archive64+projection50+staging101 passes215 cases with
zero failures/errors/skips. Python3.13.12 complete static-fixture suites pass660
with zero failures/errors/skips. Ruff, compileall and diff checks pass; independent
review is clear. Failed interim fixture output and first review reproductions
remain separate ignored records; only final-source CI can approve merging.
This slice stages local source bytes, not a release signature, compiler/image,
frozen-header or real runtime. `production_admission` remains false. The legacy
pathname-reopening `recipe.extract_source` is not used by this gate.

## Pure build-input preparation

The continuation in `build-inputs.md` checks one fixed reviewed162-object
candidate, source/postimage/table/asset origins,146 core versus16 builtin roles,
separate freezer/target extras and nine adjacent header-output/include paths.
Inert tests must reject inventory/origin/digest/flag drift, duplicate core builtin
sources, target or stock frozen objects in the freezer and unresolved fields
being promoted to observed empty values. The pinned C freezer owns empty frozen
tables; checking its source/plan is not execution of that freezer.

The driver must exit78 before configure/make/freezer activity under both default
and explicit execution requests. Retain earlier shell-stub argument evidence as
historical preparation checks; it does not authorize the newly blocked path.
No source/toolchain archive is acquired, no configuration is observed and no
real header/image is generated by this slice. Focused counts and passing results
are recorded only after tests exist and run; actual G1/G2/G3 gates remain open.

## Pure archive receipt and extraction manifest

The continuation in `verified-inputs.md` validates bounded caller-supplied
archive receipts and extraction member manifests against the two fixed
advertised archive profiles. Portable inert fixtures may exercise exact shape,
digest/size/profile binding, signature-result honesty, normalized rooted paths,
duplicates, unsupported member kinds, external receipt/manifest digest drift
and aggregate bounds. Refuse malformed
metadata before hashing, serialization or caller callbacks where shape checks
can decide the result. Keep the original fixture and first focused-test failures
separate from later passing evidence.

These tests do not download/read the real archives, verify upstream signatures,
decompress tar members, traverse/extract a filesystem tree, execute the compiler
or build/start CPython. A parsed receipt or consistent manifest is not independent
evidence that the advertised bytes were acquired, signatures were checked or
extraction was safe and complete. No supplied `verified` value can replace
actual machine receipts. Actual archive bytes, signature/acquisition results,
extracted source/toolchain provenance and G2/G3 acceptance remain unchecked.
The implemented dedicated inventory contains143 portable cases. Author and
independent reviewer runs pass143/0failure/0error/0skip; root's combined
metadata/preparation/source/observation run passes508/0failure/0error/0skip.
Full Ruff, compileall and diff checks pass. The first RUF022 lint result was
retained as a verbatim tool-result copy, explicitly distinct from an original
process stdout file. Root's broader run also reports existing Darwin pytest
cleanup warnings for older read-only temporary trees; they are not test failures
or new metadata-fixture cleanup claims. Evidence is retained in ignored
`reports/feature189-verified-inputs-20261009/`.
The new `python-verified-inputs.xml` gate requires all143 without skips and is
retained separately. Final-source run37871696368 passes all three Linux
versions and28 exact
raw XML phases with current12632/92 platform skips, zero failures/errors/retry.
Raw and root independent audits pass; PR28 merge1e492dc preserves the tested
source4ec32b2/treeeb9f9e8e. This completes the pure metadata slice only; actual
G1/G2/G3 gates remain open. The new main push CI is separately pending.

## Existing offline source preparation

The offline source-preparation slice has 96 portable cases: 49 exact-source
transformation checks, 46 finite-table checks and one plan/asset-digest check.
Root's combined preparation/observation/source run passes365/0failure/0error/0skip;
full Ruff, compileall and diff checks pass. A separate CI
`python-source-preparation.xml` gate requires all96 cases without skips and
retains the XML separately from preparation226 and observation43. Overlapping
suites are not summed as independent coverage.

Three inert `.source` fixtures retain original reviewed Git bytes and the full
upstream LICENSE. The patch policy has SHA256
`f3f740c644165d8c4d2e89840a1e75427806c12c13debf843d3b6fb2cc90f479`.
It verifies all preimages/unique snippets before returning any patched outputs,
and rechecks full postimages. Seven extracted fixed loader/finder methods refuse
before fake callbacks; the full upstream module is never executed. Stock
zipimport helper code remains, with only its external-init call removed. This
is not configured loader enforcement, source-archive/signature verification,
real frozen-header generation, compilation or startup acceptance. Four finite
table sources and their digests are emitted into the plan, with patch application,
headers, final linking and runtime acceptance explicitly pending.
Independent read-only review matched all three fixture preimages and LICENSE to
the real pinned Git checkout, reproduced all11 unique replacements/full output
hashes and checked the refusal bodies, C initialization, aliases and recipe
claims. No actionable finding remains in this preparation slice.

2026-10-09 preparation validation: the offline recipe now preserves literal
recipe directory names and expands quoted source/output variables for the
same-source freeze commands. Five portable recipe tests pass, including a
disposable configure/make/freezer shell-stub exercise with spaces, quotes and a
literal dollar in the recipe path. The stubs create no image or generated frozen
headers. Without explicit opt-in the driver returns plan-only before any build
work. This verifies emitted shell argument handling, not a CPython build,
compiler/toolchain identity, startup, loader closure or production admission.

The current implementation has local pure parser/recipe/source checks, with
Feature188 and190 prerequisites separately audited and merged. None supplies
Feature189 CPython startup or static-runtime identity.
Use the actual first installation artifact after G0/G1; old184 host Python,
Darwin behavior, fake ELF metadata, synthetic C replies and a source tag alone
are not substitutes for the required Linux evidence.

## Portable admission tests after G0

Check canonical descriptor roundtrips, exact fields/UTF-8/duplicate keys and all
aggregate bounds; exact types and hostile subclasses/collections; bool versus
integer; malformed/invented digest spelling; incomplete toolchain/libc/recipe/
generator/source/module/ELF pins; null/placeholder inputs; unsupported platform,
architecture, CPython patch version/cache tag; unlisted aliases/modules/link inputs;
external descriptor/version/artifact pin mismatch. Refuse before filesystem,
serialization/hash callbacks or runtime work when cheap shape is invalid.
A parser verifies spelling/consistency, not unseen bytes, static linking or seals.

The bounded no-dynamic recipe refusal gate now covers known direct/forwarded
loader options and linker aliases, response files, linker scripts, unpinned
library search, compiler/toolchain/offload overrides, target/sysroot/resource
overrides, linker `-z` controls, LTO output-mode overrides, OpenMP and sanitizer
runtime flags, including their build-flag environment forms. Provider-free
parser tests recompute both recipe and descriptor pins for these mutations.
This remains a refusal denylist rather than a complete compiler-option parser
or positive allowlist; no compiler, linker, build, or runtime is invoked. G1
must pin/admit the exact driver, recipe, defaults and inputs and inspect the
resulting ELF before build/runtime acceptance.
On 2026-10-23, the eight focused installation/build-input/acceptance files
reported **624 passed**; Ruff, `compileall`, and `git diff --check` passed.
Pytest emitted 27,483 existing macOS temporary-fixture cleanup warnings while
removing deliberately read-only directories; the test process exited 0.

The bounded `codecs → _codecs` source-edge continuation was checked by the
prepared-source profile, import-audit, and startup-closure suites: **102 passed**
with zero failures/errors/skips. Ruff, `compileall`, and `git diff --check`
passed. The macOS runner emitted existing warnings while removing read-only
temporary fixture trees; the test process exited 0. This check preserves the
`star-import` unsupported site and compares against a synthetic descriptor; it
does not audit the complete `_codecsmodule.c` implementation, prove target
builtin-table membership, or complete configured import closure. See
[`codecs-edge-audit-20261023.md`](codecs-edge-audit-20261023.md).

The retained `_codecsmodule.c` source slice is checked by
`tests/test_static_python_codecs_source_fixture.py`. It pins the archive
member bytes, observes the `_codecs` initializer declaration, and keeps the
synthetic descriptor's source/object metadata separate. It does not perform a
compile, link, ELF, or runtime check; see
[`codecs-c-source-audit-20261023.md`](codecs-c-source-audit-20261023.md).
The same prepared-source profile test also classifies all 21 distinct AST
targets against the synthetic frozen/builtin name sets; its five exact-name
absences are recorded in
[`prepared-import-inventory-membership-20261023.md`](prepared-import-inventory-membership-20261023.md).
This classification does not establish branch execution, target refusal, or
closure.

The combined codec-source, prepared-source, import-audit, startup-closure,
release-source, and static-table focused regression, including the `_io`
source tests, reported **159 passed**.
Ruff, `compileall`, and `git diff --check` passed. Pytest emitted 27,483
existing macOS temporary-fixture cleanup warnings for deliberately read-only
fixture trees; the test process exited 0.

The `_io` source slice is covered by
`tests/test_static_python_io_source_fixture.py`, which checks the retained
archive bytes, module/initializer spelling, Setup template's seven-source row,
and consistency with the synthetic candidate tables and descriptor. Its
evidence boundary is recorded in
[`io-builtin-source-audit-20261023.md`](io-builtin-source-audit-20261023.md).

The `_abc` source-only continuation is covered by
`tests/test_static_python_abc_source_fixture.py`. It pins the exact archive
member bytes and checks the `_abc`/`PyInit__abc` declaration, the Setup template
row, Lunar's candidate table and source/object plan, and the separate synthetic
descriptor metadata. The evidence boundary is recorded in
[`abc-c-source-audit-20261023.md`](abc-c-source-audit-20261023.md); it provides
no build, link, ELF, or runtime evidence. The combined focused regression over
the new `_abc` fixture, existing `_codecs`/`_io` fixtures, candidate tables,
build-input plan and relevant import profiles reported **142 passed**. Ruff,
`compileall`, and `git diff --check` also passed.

## Build and static evidence

Retain verified source acquisition, exact source/patch/toolchain/musl/compiler/
linker/generator/recipe hashes and outputs, static link map, generated configuration,
frozen byte arrays/inittab/alias/embedded-startup inventories and final
installation/image digests. Check release-GIL ABI flags and reject other build
profiles.
Independently inspect the actual ELF and loader/module route disposition. Require
ELF64 little-endian EM_X86_64 ET_EXEC, absent PT_INTERP/DT_NEEDED and no unexpected
static input/module. Record signature verification honestly. Preserve original
build/link/freeze errors and actual receipts; absence of a build is an open gate.
Reproducible comparison, if performed, is supporting evidence only.
The actual image must be <=134217728 bytes (128 MiB), including all frozen/static
contents, under the existing producer-launch/executable-binding ceiling. Exercise
the boundary and reject oversized candidates without changing the limit or adding
a temporary exception.

## Actual fixed startup and closure

Launch the original sealed static image through original native targetFD/v2.
The real CPython must emit version_info=(3,13,12,'final',0),
implementation='cpython', cache_tag='cpython-313', actual expected flags/config/path
outputs and the fixed frozen main's Python computation/pipe results. Independently
compare output with the pinned profile and retained object/process evidence.
Check the complete startup module table and origins against the final finite
inventory; the seed list in spec.md alone is insufficient. No Python/stdlib host
roots may be necessary for startup or the fixed computation. Verify initialization
encodings/aliases/UTF-8 and required error handlers; test an unadmitted codec.

Provide inert, explicitly readable cwd/PYTHONPATH/PYTHONHOME/site/venv/pyvenv/._pth/
build-tree/customization/zip/extension decoys. Verify their readability separately
from their non-loading so the existing filesystem sandbox is not the sole cause.
Require no decoy execution or pyc, and fixed refusal of unlisted module names,
unsupported codecs and dynamic-extension route. All such tests run the same
installation-owned fixed main/predefined case set; no arbitrary project/code
payload is passed. These negatives prove the bounded startup/fixture, not a
compile/exec/marshal or malicious-producer containment guarantee.

## Seals, provenance, original lifecycle and cleanup

Prove exact original installation/image source pins before sealing and the actual
four seals on the target object. Original same-byte/different-identity or changed
source/image pins refuse as required by existing executable admission. Replace or
delete installation source after sealing and demonstrate that original sealed
bytes still execute the admitted fixture; do not rebuild pins to hide drift.

Verify original ready/release/start/terminal ordering, guardian ownership, exact
stdio/pipe/target FD closure, pipe transcript, bounded case output and process
reaping. Exercise deadline/cancellation, pauses/death, malformed/truncated pipe
response, startup failure, interrupted acquisition and uncertain cleanup. Attempt
all still-owned releases and preserve primary errors with fixed cleanup_unknown
notes; known foreign FD reuse is not closed. No renewed budget/deadline.
This foreign-reuse condition requires independent dedicated proof of the selected
privately held original target owner, or a separately reviewed owned-target
recovery implementation. The old public `sealed_linux_executable` closes its
numeric FD without that original-object check and is not safe-recovery evidence.
Feature190's private original owner is on main3a7782c; Feature189's actual target
integration remains unaccepted. Test closed/reused
numbers and same-byte foreign objects, forced public observation mutation and
interrupted acquisition/release; parsed JSON or public numeric FDs cannot establish
the owner's cleanup authority. Keep v2's FD schema and keep-list unchanged.

## Final-head acceptance

Run focused tests, ruff, compileall and diff check after modifications. Linux CI
must include a dedicated actual-artifact fixture gate requiring exact collected
case identities/counts and zero skips; freeze the count only after implementation
exists. Collect raw ZIPs/logs/XML, actual checkout/source tree, original module/
toolchain/image pins and machine receipts. Independently check API/run/head/base/
tree binding, artifact digests and bytes, expected inventories/skips, actual Python
observations and first failures. Current full-suite retries are not silently used
to replace a failed first attempt. Preserve any specifically authorized historical
retry's original XML and reason separately.

Passing189 records only installation-owned-static-frozen-fixture scope and actual
known-main execution. Keep runtime_load_protection, production_admission and
general_code_origin_protection false. Merge requires this feature's own exact
final-artifact/Linux evidence;188 or184 evidence cannot be relabeled as189.
## Snapshot-bound original source-tree observation

The source-tree observer consumes one immutable `StaticPythonArchiveSnapshot` and
reuses the strict archive walker exactly once. It records the complete sorted
regular-file inventory, original archive modes, sizes and pre-patch byte hashes in
the separate `lunar-static-python-source-tree-v1` domain. Expected manifest and
source-tree digests are independently supplied pins. Explicit inert fixtures keep
`profile_pin_verified=false`; they do not establish acquisition, signature,
extraction, build or runtime evidence.

The focused gate is `tests/test_static_python_source_tree_observation.py` with 22
cases and zero failures, errors or skips. It covers canonical/detached records,
single decode, independent pin drift, fixed-profile refusal, deadline expiry and
the absence of filesystem, subprocess, network, staging and runtime routes.

## Archive receipt/source-tree consistency comparator

The comparator stays in `tools/static_python_fixture/source_provenance.py` and
reuses the existing archive-receipt-v1 validator. Focused cases cover complete
DTO/canonical/hash and tree wire/hash consistency, independent original pins,
coherent and stale inert refusal, deep file/container immutability, retained
signature declarations and absence of external effects. Handmade coherent
metadata checks the successful agreement return only; it is not an observed
release, successful archive acquisition or G1 acceptance. Original inert archive
observations deterministically refuse. Execution, signature-verification work,
load/origin protection and production admission remain false.

PR37 run38042870910 passed independent raw audit and merged mainc8238ef with
treefde29b44. Its focused source-tree gate is22 cases. PR38's artifact slice and
this comparator each need their own final-source CI/audit; neither inherits
PR37 acceptance or completes the remaining actual G1/G2/G3 gates.

Local final check:34 comparator cases and234 receipt/source-tree/artifact cases
passed with zero failures/errors/skips; full Ruff, compileall and diff checks
passed. Final-source CI is pending and cannot be claimed from these fixtures.

## Source-tree / staged-tree consistency check

The provider-free `validate_source_staging_consistency` continuation compares
the independently pinned source-tree observation with a canonical staging
record. Its positive fixture may use the existing inert CPython source fixture;
this verifies only that the records agree and must preserve the inert-profile
state. Also cover coherent validated-profile metadata without treating it as
real acquisition. Refuse wrong/missing staging, manifest or source-tree pins;
stale/noncanonical/self-digest-mismatched wires; archive/root/version/snapshot
drift; mismatched profile/inert states; changed source paths/modes/sizes/digests;
missing, duplicate or extra regular files; implicit directories that are not
required ancestors; valid explicit directories including empty-directory entries;
wrong patch-set and fixed-patch pre/postimage pins; changed unchanged-file bytes;
bad claim flags; and malformed entry/stat fields. Monkeypatch and prove the check
does not call `open`, `os.open`, filesystem/network APIs or subprocess.

The focused check must preserve the distinction between the original archive
tree digest and staging digest. It does not restat the staging directory and
cannot close candidate-build-source provenance, G1 acquisition/signature,
configured toolchain/build closure or G2/G3 runtime acceptance.

Local continuation result (2026-10-21): 83 provenance tests passed, including
positive inert and validated-metadata fixtures, independent-pin and canonical
wire refusal, archive/version/profile drift, patch pre/postimage agreement,
directory inventory, malformed stat/entry bounds and no-external-effect checks.
An explicit `tests/__init__.py` package marker keeps a separately installed
top-level `tests` distribution from shadowing repository helper imports. The
five-file focused run then passed through the normal `python -m pytest` entry
point. Repository-wide Ruff, `compileall` and `git diff --check` passed. This
result establishes only detached DTO consistency and leaves real source
acquisition, candidate-build provenance, configured static build and runtime
acceptance open.

The same validator was then exercised on Linux against the pinned CPython
3.13.12 archive using the previously retained manifest and source-tree pins.
All 4,837 original regular files (108,687,660 bytes), 5,245 staged entries and
the fixed patch pre/postimage set agreed. The staging digest was computed by
that probe itself, so this is a real-input implementation regression rather
than an independent retained staging pin or candidate-build provenance.
Details and the exact claim limits are in
[`source-staging-consistency-probe-20261021.md`](source-staging-consistency-probe-20261021.md).

## Bounded startup/import graph DTO

`startup-closure-contract.md` freezes a separate canonical graph wire that binds
the current installation descriptor, source/patch/initialization/frozen/builtin/
alias pins, the exact expected startup-module inventory, a separately hashed
startup-root vector, route records, alias mappings and directed import edges.
The parser validates only caller-supplied DTO consistency, canonical bytes,
reachability and independent pins. Its synthetic roots are not the audited
CPython roots. It does not extract imports, prove the graph is complete, inspect
a configured build, or start CPython. Existing module inventories remain
unchanged; `operator` is not admitted from a separate diagnostic image.

The synthetic focused regression is `tests/test_static_python_startup_closure.py`
(64 passed, zero failures/errors/skips). It covers separated inventory/roots,
alias edges, reachable and missing-edge graphs, unknown/missing inventory,
external pins, strict
canonical/type/budget failures, detached results, false-only claims and the lack
of filesystem/process/network/environment/build/runtime effects. Ruff passed for
the changed Python files, `compileall` passed on those files, and
`git diff --check` passed. Independent source-edge review, actual static build,
sealed startup and owner/lifecycle acceptance remain open; no real build or
runtime was run for this DTO slice.

The staging budget regression tests exercise a 65,000-entry canonical staging
wire larger than 32 MiB, enforce independent staging wire/string ceilings, and
retain the existing source-observation wire ceiling. A complete consistency
fixture with 2,500 synthetic regular files expands implicit ancestors until the
staging-entry path total exceeds 16 MiB while the original source paths remain
within their 16 MiB budget. The validator accepts this bounded matching pair.
The combined provenance/source-tree/staging/projection/patch run passes all320
collected cases with zero failures, errors or skips. Full Ruff and
`git diff --check` pass; `compileall` passes on the three changed Python files.
Do not run `compileall .` across ignored `.lunar` evidence trees: those retain
inert payload files ending in `.py` and can contain read-only directories. No
build, runtime or evaluator was run by this regression.

## Source-byte-bound Python AST import observations

`python-import-audit-contract.md` defines a separate in-memory observer over an
exact caller-supplied module-to-source-bytes map and matching external per-source
SHA-256 pins. Synthetic tests cover absolute/from imports, package-relative
resolution using explicit `pkg.__init__` source keys, optional submodule edges
only when those bytes are supplied, literal imports, and fixed unresolved or
unsupported records for relative gaps, dynamic calls, star imports and dynamic
code execution. They also cover malformed pins/types, encoding/syntax failures,
size/node/depth/site/output budgets, canonical detached results and refusal
codes. No source file is read or executed.

The suite also covers namespace-package parent resolution, literal `name=` and
`package=` arguments, nonliteral relative package refusal, and the distinction
between an `importlib` root alias and an `importlib` submodule alias.

The result is an AST observation wire only. A static target may be named even
when its source bytes were not supplied; there is no profile comparison or
closure claim. The scanner does not establish source provenance and does not
cover C-created imports, arbitrary import aliases, loader hooks, runtime-built
code or every other dynamic mechanism. Therefore, an empty unsupported-site list
does not complete the independent CPython 3.13.12 source audit in `tasks.md`.
The synthetic gate is **35 cases**, with zero failures, errors or skips on
Python 3.11 and 3.12; focused
Ruff, compileall and diff checks are run for these new files only. No build,
startup, solver, remote evaluator or company platform was run for this slice.

## Partial CPython release-source import review

`authenticated-source-import-audit-20261021.md` records read-only AST
observations for eight frozen-module Python files read directly from the pinned
CPython 3.13.12 release archive on 5090gpu. It distinguishes those archive
members from a separately patched staging tree, records the tree byte drift,
and identifies dynamic codec-name selection under `encodings` and the `_py_abc`
fallback under `abc` as source-level policy issues. The finite source-preparation
contract now defines dispositions for both, but target use remains unverified.
It also pins the
Lunar-owned frozen-main template separately from the final expanded source.

This partial audit is an input for the independent source review, not its
completion. It does not cover all Python/C startup edges, establish runtime
reachability or module origin, bind the emitted frozen main, or close the
configured startup graph. No build, install, evaluator or campaign was run.

The same report now retains a direct Lunar-observer replay over the eight exact
CPython archive members: 28 import edges, zero unresolved observations and four
fixed unsupported sites, with a canonical result digest. Call-time member pins
were derived from the supplied bytes, so the replay validates observer behavior
on those bytes but is not independent per-file provenance or closure evidence.
The separate three-case `test_static_python_source_import_profile.py` checks the
6,794-byte expanded `_lunar_static_main` bytes against the reviewed freeze-task
pin and audits those exact bytes; its fixed `__import__(name)` loader-negative
site remains unsupported. Both source observations keep all capability claims
false. They do not replace the still-open complete CPython/C startup audit,
target-startup codec registration, generated-header checks, configured build or
sealed runtime acceptance. The finite source patch now re-raises the original
`_abc` `ImportError`; its focused test checks message and exception context.
The codec test registers the synthetic patched lookup callback with host
`codecs.lookup` and confirms an unsupported name raises `LookupError`. These
checks remain source-level and host-API observations; they do not execute or
start the patched target.

## Bounded C-startup source review

[`c-startup-source-audit-20261021.md`](c-startup-source-audit-20261021.md)
records exact sizes and SHA-256 digests for 23 CPython 3.13.12 archive members,
plus fixed Lunar generated-table source pins. The review distinguishes
C-created `sys`/`builtins`, `_inittab` entries, `_imp` bootstrap initialization,
frozen tables and aliases, and the separate embedded getpath array. It also
records which path/table inputs are archive-owned, generated from the Lunar
profile, or fixture-owned.

This is a bounded source report, not a complete mechanized C import/configuration
gate. It does not show that the planned tables were built, that a configured
`Modules/Setup` or `pyconfig.h` matches the profile, or that the final image
contains only those entries. The actual configure/link closure, same-source
freezer outputs, C/header conditionals, startup behavior, module origins and
runtime refusal paths remain open. All capability and production claims remain
false; no build or evaluator was run.

## Source-derived CPython startup roots

`startup-root-audit-20261022.md` records the eight source-level primary roots
for the fixed CPython 3.13.12/Linux profile and their pinned C/launcher entry
sites. The compact canonical root array is retained separately with SHA-256
`d1743e729bac34c5110a1d1373cc48c74a52b585034825227ed37d0178e39313`.
The bounded bootstrap and loader route review is documented in
`importlib-edge-audit-20261022.md`; it classifies selected source edges and
candidate dispositions, while deferred direct resource-reader/metadata routes
and configured/runtime binding remain open.
The focused startup-closure suite now has **65 passing cases**, including a
check that this root pin is a proper subset of the descriptor's 22 expected
startup modules and composes with the comparator. The associated graph edges in
that test remain deliberately synthetic. This closes root derivation only;
complete import-edge audit, configured closure, build, runtime, and admission
remain open. Ruff, `compileall`, and `git diff --check` passed for this slice.

## Core `_warnings` source-only observation — 2026-10-23

`tests/fixtures/static_python_source/Python/_warnings.c.source` is pinned to the
43,088-byte `Python-3.13.12/Python/_warnings.c` member from the archive identified
by SHA-256 `2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`.
The companion inert `Setup.stdlib.in` fixture is also member-pinned. Focused
checks record `MODULE_NAME`, the module definition, `_PyWarnings_Init` and its
`PyModuleDef_Init` return; they compare the initializer with Lunar's emitted
`Modules/config.c`, core source recipe, exclusion from
`LUNAR_STATIC_MODULE_SOURCES`, and the synthetic descriptor. Neither Setup
template declares `_warnings`; this is the core builtin path.

`get_warnings_attr()` conditionally imports the Python-level `warnings` module.
That module is absent from the currently reviewed finite profile, leaving an
unclosed source edge. This observation does not decide whether the path is
reachable under target execution.

The continuation test pins the two `try_import=1` call sites and their
source-level guards/fallbacks: warning display is conditional on the warning
action, an absent Python display hook uses the C display path, and unawaited
coroutine finalization has a Python hook plus `_PyErr_WarnFormat` fallback.
That fallback can re-enter the display path. The candidate's empty
`warnoptions` and disabled `site_import` therefore do not establish that
`warnings` is unnecessary for every fixed workload path. The current fixture
set separately pins `Lib/warnings.py` and `Objects/genobject.c`: the Python hook
is called for a coroutine with `FRAME_CREATED`, and it imports `linecache` and
`traceback` only when `cr_origin` is present. The `warnings` module itself also
has conditional `linecache` and `tracemalloc` paths. These sources are support
evidence, not module-profile inputs; complete workload reachability and runtime
disposition remain open.

The supporting `Lib/warnings.py` bytes also pass through the bounded AST import
observer, which records ten supported static edges and one unsupported dynamic
import at line 267; no imports are unresolved. All closure, runtime,
installation, and admission claims remain false. Separate source assertions pin
selected `linecache`, `tracemalloc`, and `traceback` conditions and confirm that
`warn_explicit()` returns for `action == "ignore"` before its local `linecache`
import. These observations do not track branch reachability or change the
expected startup inventory.
The focused warning/source/profile/table set passed 57 cases; Ruff,
`compileall`, and `git diff --check` passed.

## `pylifecycle.c` conditional warning/site source observation — 2026-10-23

The supporting 106,247-byte `Python/pylifecycle.c` archive member is pinned by
size and SHA-256. A focused test checks that the source imports `warnings` only
for a nonempty `warnoptions` list and imports `site` only behind
`config->site_import`; candidate metadata still pins `warnoptions=[]` and
`site_import=0`. This records a source/config relationship, not effective
runtime configuration or reachability. Focused results for this addition are
covered by the combined warning/lifecycle/source/profile/table run below: 59
cases passed. Ruff, `compileall`, and `git diff --check` passed.

These checks establish only retained bytes and source/metadata consistency.
They do not prove header closure, configured `Setup`/`pyconfig.h`, source
consumption, compilation, linking, ELF contents, runtime startup or module
origin. No build, remote evaluation or solver campaign was run.

## Versioned baseline startup-scope review — 2026-10-23

`startup-scope-audit-20261023.md` and its versioned JSON retain the fixed
CPython 3.13.12 Linux candidate's baseline source graph. The observer replay
uses `encodings.__init__` as its package key, reproduces the retained canonical
AST digest, and now compares all 28 normalized source edges and all four
unsupported source sites directly against the JSON. The review keeps the
source-derived eight-root vector separate and documents the C bootstrap
literal-import edges plus conditional, deferred, platform-excluded, and
loader-negative routes. The expected 22-module candidate inventory is
unchanged.

The focused source-scope and startup-closure suites passed 69 cases with no
failures, errors, or skips. Comparator regressions confirm that the exact four
unsupported sites and the deferred out-of-profile `tokenize` edge are refused;
the comparator remains a synthetic comparison DTO. Ruff, `compileall` for
`src`, `tools`, and `tests`, and `git diff --check` passed. Effective
configuration, complete configured closure, generated freezer/header
consumption, build, target runtime origins, and loader-negative behavior remain
open. No configure, build, solver, evaluator, network, or remote assessment was
run for this source-only slice.

## Serial RSI regression follow-up — 2026-10-23

`serial-regression-performance.md` records the retained failed unprofiled
`31b8c2cd` Linux case, its separate live-receipt naming defect, and the new
exact-type and globals-namespace changes. The 178 admission/type cases and
64 policy cases passed. The independent new-boundaries selection passed all
45 cases (33 admission types plus 12 builtin namespaces), which CI enforces
without skips. All 204 runner cases passed with an external unique `/tmp`
basetemp; the earlier combined run's two environment-induced nested-collection
failures remain preserved separately. Ruff, src/tools/tests compileall and
`git diff --check` passed.

The pure `project()` benchmark is not end-to-end evidence. A separately retained
main-thread CPU profile has invalid clock accounting and cannot support timing
or hotspot conclusions. Exact final-source Linux original-600-second acceptance
and all 33 final-head CI jobs remain required before main merge. Build/runtime,
production admission and online publication are not enabled by these changes.

The subsequent unprofiled `88005a30` Linux replay still failed at the original
control, with primary `rejection_control_expired` and teardown `worker_unknown`.
Its live module/source checks and eleven transferred file hashes passed.
Post-run ledger preservation was impossible because fixture teardown removed
its private directory; the limitation is retained, and no replay was started
to fill that evidence gap.

The follow-up exact-dispatch/domain split passes 288 related focused cases.
CI's exact-type/domain/freeze gate is now 91 cases (33 + 19 + 39), requiring
zero failures, errors or skips. The independent freeze-only pure builder
benchmark preserves projection/pins; local timing is not E2E evidence. The
normalization memo experiment was rejected after a mutable-regex-cache
counterexample. These changes enable no build, runtime or production claim.

## Source/startup audit CI and candidate-plan alignment — 2026-10-24

The dedicated source-import audit gate now selects the existing import audit,
source import profile, baseline startup-scope audit and startup-closure suites.
Local collection confirms 107 cases (35 + 3 + 2 + 67). Execution with CPython
3.13.12 passes all 107 with zero failures, errors or skips; the exact workflow
XML guard also passes against
`/tmp/lunar189-p1-source-audits-ci-gate-20261023.xml`. Full-tree Ruff,
`compileall` for `src`, `tools` and `tests`, and `git diff --check` pass.

The plan and unchecked G2 tasks now name the existing candidate assets and
their remaining configured/static-target and runtime bindings, including the
fixed `_main` computation of 285 and existing baseline/loader-negative cases.
Feature190's completed private original-owner implementation is distinguished
from Feature189's still-open target integration. No acceptance checkbox is
changed. These are local source observations and synthetic comparator checks;
exact-source three-version Linux CI, immutable build custody, configured
closure, freezing/compilation/linking and G3 runtime acceptance remain open.
No build, E2E, solver or evaluator was run for this change.

## Complete toolchain copy validation — 2026-10-24

The private materializer and independent fault-injection selection pass all
54 cases; the broader 433-case combined selection passes with zero failures,
errors or skips. Those selections overlap and are not additive. Ruff for the
whole repository, compileall for src/tools/tests and diff checks pass. Linux
CPython 3.11.15 independently passes the same focused54, with the command,
log, XML and summary transfer hashes verified.

The unique real-Zig data-only replay on exact a9b75116 creates all 20,832
members (19,546 files, 1,286 directories, 357,913,169 bytes), then performs a
separate complete remote walk. Its original 120-second budget includes that
walk and source-after checks; total budgeted time is 11.696064 seconds.
Independent local audit checks exact source commit, loaded modules, runner,
inputs and transferred receipts. The copied tree itself is not transferred
for a second local walk. See `toolchain-private-custody.md` for evidence pins
and receipt limitations. No archive member, compiler, build, runtime or solver
runs; all ten claims remain false and G1/G2/G3 remain open. The rejected
remount/nested-userns custody probes remain failures, not copy acceptance.

## Independent retention of source records — 2026-10-24

Eighteen existing release/source records and five actual patched files are
retained locally with checked transfer type/mode/size/hash and original patch
file identities. An independent offline standard-library review reads all
5,245 archive members and reconstructs the complete 4,837-file source and
staged-projection pins. The five actual postimages equal the in-memory fixed
patch results byte-for-byte. Saved signature metadata/transcripts are retained
and compared; no new cryptographic verification or old runner replay occurs.
See `candidate-source-retention-20261024.md` for pins and the historical record's
LF/live-provenance limitation. This closes raw-record retention, not current
full staged-filesystem observation, immutable custody or configured consumption.

## Candidate codec workload and identity transition — 2026-10-24

The existing candidate negative case now checks the finite UTF-8 name/aliases,
fixed unknown-codec rejection and surrounding module/path profile. All candidate
and RSI input/overlay/profile pins are refreshed as one source-only change.
The historical expanded main and source graph remain unchanged; a separate
current nine-source AST observation binds the new main to the same 28 import
edges and four unsupported sites, with the dynamic-import site's new line.

The final combined selection passes 1,032 distinct cases with zero failures,
errors or skips, including the 54 copy and 204 runner cases. The dedicated
22-case codec selection and exact workflow XML guard pass separately;
independent review's 69 cases overlap and are not additive. Whole-repository
Ruff, src/tools/tests compileall and diff checks pass. See
`candidate-codec-negative.md` for precise candidate pins and earlier grouped
focused results. The existing launcher suite builds an inert argv probe against
a fake C header/runtime; it does not build CPython. No archive member, CPython
build/freezer, candidate static image or solver runs; configured closure,
immutable custody and G2/G3 target acceptance stay open.

## Linux focused source-invariance refusal and candidate C API review (2026-10-24)

The first and only Linux focused run of exact83c1d88d has 774 passing tests,
zero failures/errors/skips, 236 verified module origins and unchanged bytes/full
modes/exec bits for all 2,332 original tracked files. Full source invariance
fails on three added pyc files and one cache directory. The overall result is
FAIL, with the original source and additions retained. The old collector exits1
without recording its child Popen returncode before the failing assertion;
the plugin's session exitstatus0 and passing XML are distinct receipts, not a
reconstruction of that missing raw process status. See
`candidate-codec-negative.md` for the retained artifact pins and location.

Three source-only CLI argv lists now explicitly include `-B`; all original
assertions, the minimal environment and full source-invariance gate remain.
The local launch51+codec22 set passes73 with no skips. New-source Linux focused
verification must persist child returncode and complete before/after inventories
before any overall assertion, including on refusal. It is not a retry of83c.

That single run of exactde9bd387 subsequently passes:774/0/0/0, rawrc0 durably
recorded before post-run gates, 2333 complete source files and directory
inventories identical with no additions, and236 final-session module origins
verified. XML22.331s and subprocess22.664091s are separate measurements. All17
transferred artifacts, the exact Git archive/index, source inventories and raw
receipts pass the independent root review. See `candidate-codec-negative.md`
for each pin. The previous83c overallFAIL is retained, not reclassified.

The separate independent `profile-getpath-source-review-20261024.md` checks ten
actual pinned CPython C/header members, ten PreConfig fields, 66 PyConfig fields
and28 source anchors. No source/API mismatch was found. Generated configuration,
role flags, actual compilation/consumption, link and effective runtime settings
remain unverified; the original G2/G3 tasks stay open.

## Five fixed deferred-import source refusals (2026-10-24)

`deferred-import-refusal.md` records the five whole-function replacements and
their independently projected 63,208-byte external source identity. The fixed
reader name decorator is removed and actual PathFinder staticmethods retained.
The current source audit has25 edges/4unsupported/0unresolved; no modules are
added, old codec/v1 graph records stay byte-identical, and old prepared bytes
are separately retained for historical replay.

The final shape-preserving base/RSI pin group passes502 tests, and its31-case
new dedicated subset passes with zero failures/errors/skips. The independent
review's22 cases are included in31, not additive. Eight in-memory AST negative
variants are rejected. The earlier736-case source/history group ran before the
final JSON projection correction; its unchanged source/history tests passed,
but it is not a736-case final-revision acceptance. Whole-repository Ruff,
compileall and diff-check pass. Final-chain, literal-consumer, historical-byte
and JSON-shape independent review reports no blocker. The unique exact966
Linux focused/source-invariance run below now passes; full branch CI is still
required. Neither the earlier736 group nor later documentation heads inherit
that exact source's acceptance identity.

No archived source module, real configure/freezer/compiler/linker, target,
solver or evaluator executes. SourceLoader.get_source still reads before
decode_source; general callback/file refusal, full closure, immutable custody
and G2/G3 runtime/admission remain open. PR186's separate49b CI now has a
Python3.13 current-3 failure under investigation; main merge remains blocked.

## Exact966 Linux provider-free source acceptance and retention (2026-10-24)

The tested source is exactly
`966c5cf91ec63265b9d6d0cadaf91945d38aaa9a`. Its 26,961,920-byte Git archive has
SHA-256 `2f6c909fbbaaf36a51f9c618b4305deb335111035deaadb61f19cca103bb7cac`.
The fixed selector contains 27 distinct test files: the earlier 736 selection
plus RSI launch, source staging/tree/provenance, candidate-build source and
observation, projection, verified-input and source-readiness suites. Local and
remote collect-only results agree on all 1231 nodeids. Only the remote host
starts actual tests, once, under Python 3.11.15 with one unique repository-external
`/var/tmp` basetemp, unchanged budget, no rerun and no source cleanup.

The XML records 1231 tests, zero failures/errors/skips and 25.853 seconds. The
raw Popen returncode 0 is flushed and fsynced before evaluating any post-run
inventory, XML, module or success gate; subprocess monotonic time is 26.159305
seconds. Complete before/after inventories match all 2338 files and 292 directories
against the new archive index, including bytes, complete modes and executable
bits. Added, removed and changed files/directories are all zero; caches are
included, not ignored. All 238 final-session Lunar/tools modules have matching
exported source origins and bytes. The original seven required modules and ten
additional actually used source modules are all loaded. No receipt is missing
and the collector records no error.

All 17 raw artifact hashes match after transfer. The source worktree retains its
original ignored package at
`.lunar-evolution/feature189-deferred-linux-evidence/966c5cf91ec6-v78xqg7u/`;
the remote run remains at
`/home/qinzhiqing/vchive/lunar-feature189-deferred-966c5cf9-BPZ0UT`.
A create-only copy is retained in the main workspace under
`.lunar-evolution/validation/feature189-20261024/deferred-966c5cf9-retention-bn4qrqdb/966c5cf91ec6-v78xqg7u/`.
All 30 files, two directories and 29,727,449 file bytes match the original package's
modes, sizes and hashes; read-only before/after comparison confirms the original
package did not change. Previous 49b/83c/de9 packages are untouched.
Root independently audits the complete archive against exact Git966, all index/
source/receipt hashes and modes, 1231 unique passing cases and both collections,
rawrc0, all 237 file origins plus one tools namespace, and all 17 required modules.
The read-only review passes without executing tests or artifact code. Its receipt
is `root-independent-review.json` in the retained package's parent directory.

| Retained receipt | Bytes | SHA-256 |
| --- | ---: | --- |
| Raw artifact manifest | 2563 | `b705ff6c714e4eac65afb2c430fe459ae2f1bd1072229636804a6dbda98a2172` |
| Test XML | 219868 | `be5465b4a9b34af8b2985fc428e372fe8c30373aee553a8fac8a7467dac35751` |
| Raw process result | 133 | `3c474747d39c5ba520e0db0056fea96b4d4b78ba52b8fb0f69bf7203c84af5d0` |
| Source-before and source-after (each) | 554908 | `58288e8b354893c7ba4ba1d8911ee0ca538f2eef67bbc3c8fcff90970bd95f0e` |
| Retention manifest (parent of package) | 6033 | `ad85fb54a1f5508202507ea00031c2a7f76014ad2b8ac37d7cec3cfcab31af19` |
| Root independent review (parent of package) | 595 | `45f8902aa3a2855aff1afbaffefd2c086569c630ce97a58140ebf8d8d9878392` |

The selector includes existing inert host-C launcher probes against fake
Python.h/runtime stubs and source-only CLIs. No mixed replay, archived CPython
source execution, actual configure/freezer/static build/target, solver or remote
evaluator runs. This acceptance belongs only to 966, not the later documentation
commit. Full branch CI, configured closure, immutable custody, ELF and G2/G3
runtime/admission remain open.

PR186's distinct exact49b original CI has a Python3.13 current-3 mixed failure
at 601.169 seconds with primary
`rsi_brs_rejection_provenance_allowance_exhausted` and attached `worker_unknown`.
The observed stack is not hotspot proof; the other two original CI versions
remain pending. Preserve that raw failure and the original budget. Do not rerun
49b, infer 33 passing jobs, or merge main using the independent 966 focused result.
