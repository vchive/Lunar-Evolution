# Validation contract — preparation is not runtime evidence

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
