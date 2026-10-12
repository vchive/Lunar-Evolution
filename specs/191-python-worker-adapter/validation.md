# Validation plan

## 2026-10-13 explicit native prepared-boundary bridge

`NativeRSISchedulerProvider.pin_python_admission_at_prepared_boundary` is the
reusable provider hook for a caller-owned `prepared_observer`. It accepts the
original handoff digest/file pin, persisted prepared journal and expected
admission-anchor digest, rereads each retained file, compares the complete
request/runtime identity, then invokes the existing DRS/BRS bridge adapter.
The native provider's `__call__` path never invokes this hook and does not read
post-execution Python evidence. A caller must pass the hook explicitly after
the transaction has durably published the prepared intent; this remains
provider-free plumbing and keeps `production_admission=false`.

## 2026-10-13 provider-free admission bridge

The provider-free bridge has focused coverage for descriptor parsing, DRS/BRS owner
selection, missing owner scope, single-controller binding, workspace identity and record
digest validation.  The native scheduler does not call this hook automatically: its
prepared journal/attempt anchor includes post-execution/runtime evidence, while the
current scheduler context has no original Python handoff/file-pin input.  The path does
not run CPython/toolchains or remote evaluators and keeps `production_admission=false`.
The complete runtime/process/journal interruption matrix and sealed-runtime acceptance
remain open P0/P1 work.

## 2026-10-12 independently pinned runtime observations

The new `python-observation-policy.xml` gate requires74 unique cases and zero
failures/errors/skips. Final five-suite local Python3.11.15 verification passes309
cases in69.708seconds:74 policy,45 admission gate,49 adapter,98 lifecycle and43
encoder/observation cases. Seven disjoint compatibility suites pass195 in6.298seconds,
yielding504 unique local cases. XML IDs are compared before aggregation; reruns are
not additional tests. Reports remain under ignored main-workspace
`python-observation-policy-20261012`, including earlier failing setup/reproduction
XML retained separately.

Independent review of the original303-case source found a Unicode encoding exception
for malformed installation-version labels. The corrected exact ASCII label gate is
covered by six added cases; each exercises helper/gate/build/verify with a fixed
`installation_pin_unverified` refusal. Independent Python3.13.12 final policy replay
passes74 in50seconds with no failure/error/skip and six reviewed source/test hashes
unchanged. Its create-only report is
`python-observation-version-pin-final-py313-1791742697581629000`. The first74 replay
passed but observed a concurrent comment-only test edit; that fact and the source
reconstruction proof remain separate from the final frozen replay. The earlier
303/498 local evidence and independent303 replay in
`python-observation-policy-independent-py313-1791742012203477000` retain their earlier
source identity. Overlapping cases are not counted twice. Ruff, compileall and diff
checks pass. Complete three-version CI/raw source/tree audit remain required before
merge.

Inert asset tests use the actual frozen-main encoder, fake sys/loader/pipe facts,
the existing observation adapter and both detached gate/build/verify APIs. Negative
cases cover named-flag syntax/order/value drift, OS/PyConfig vector confusion,
missing/replaced independent installation pins, descriptor/binding artifact mode,
size and target mismatches, version/ABI/encoding/path/module drift, callback-shaped
inputs and zero external effects. Historical token observations remain parseable
for inspection but refuse successful verification.

The native-input test stages real local request/memory files through the existing
API, then verifies that current static argc-one OS argv receives exactly
`rsi_native_inputs_marker_missing`; no bootstrap/launch binding is read or written
and original bytes/inodes/mtime remain unchanged. This explicitly retains the
unresolved RSI launch contract. No real CPython build/runtime, OpenEvolve/Shinka
campaign, remote evaluator or production admission is exercised. The new gate is
annotated/uploaded with the existing gates;43 focused plus3 full CI phases belong
to this final source and cannot inherit previous PR acceptance. Contract:
`runtime-observation-contract.md`.

## 2026-10-12 bounded local interruption recovery

The dedicated `rsi-python-interruption.xml` gate requires24 unique cases and zero
failures/errors/skips. Final local matrix passes24 in66.936seconds; disjoint existing
inert recovery/publication compatibility passes75 in135.910seconds. Root independently
passes36 overlapping matrix and journal recovery cases in65.935seconds; that overlap
is not added to99 unique local cases. First failed XML and final XML remain separate
under ignored main-workspace reports `python-interruption-matrix-20261012`.

The matrix uses actual ledger rows and retained process/publication files. Repeated
reopened recovery checks exact durable rows, bytes and file metadata. It forbids process
spawn, cleanup and real evaluator entry. Missing/malformed journals exposed an exception
contract defect, now normalized at all three recovery parser reads. The dedicated gate
is annotated/uploaded alongside existing gates. This source needs its own three-version
full CI and independent audit; inert file recovery does not establish runtime execution,
sealed CPython, actual solver lifecycle or production admission.

## 2026-10-12 BRS first-CI failure and bounded progress correction

Original PR46 run38156193067 failed the same two BRS fixture watchdogs on all three
Python versions; full regressions were skipped. Preserve the original ZIP/XML/log and
metadata under ignored `pr46-final-ci-run38156193067-11875b8-v2`, including the final
failure-retention record. The former10-second sibling waits and20-second publication
watchdog did not allow repeated proof observations on CI filesystems. Neither failure
is reclassified as a passing source.

Only the two fixture watchdog sites now allow60seconds. Original absolute execution
deadline/budget, event order, worker count, ordinal result save and refusal assertions
stay intact. The offline Python3.13.12 gate passes103 cases in194.462seconds, zero
failures/errors/skips. Retained trace proves acknowledgement, settlement, slot release,
queued dispatch and successful return of every sibling, with no hidden worker exception.
Root Python3.11.15 independently passes the same103 cases. XML/trace and static checks
remain under ignored `pr46-ci-progress-diagnosis-20261012`. This is test progress
verification, not runtime acceptance; the corrected source needs new three-version CI.

## 2026-10-12 local BRS owner ready/ack

The new `rsi-python-brs-admission.xml` gate requires103 unique cases with zero failures,
errors or skips:63 channel,22 controller owner and18 worker publication cases.
Root final-source Python3.11.15 verification passed103 in108.919 seconds (retained
`.lunar-evolution/reports/brs-final-20261012f.xml` in the main workspace). The final
nested-dispatch and owner-save CAS fixes also passed independent focused replay;
independent actual `run_brs` fixture confirms unrelated durable head drift is preserved
and no ordinal execution save occurs. Independent review found no remaining blocker.
Final-source DRS owner/store/checkpoint compatibility passed78 in65.768 seconds
(`.lunar-evolution/reports/brs-cross-path-20261012g.xml`), with no failures/errors/skips;
these disjoint final inventories contain181 unique cases.

Auxiliary compatibility evidence remains distinct:100 facade/DRS/prepared-observer
cases,70 facade/store/checkpoint cases,86 flow/checkpoint/controller cases, and an
independent230-case overlapping six-suite run passed. These runs began before the last
nested/CAS fixes and are not additional final-source acceptance or additive inventory.
The final103-case gate covers both fixes. Original failing/intermediate XML files remain
retained in ignored main-workspace reports; no failure was overwritten by success.

Actual BRS futures service ready from any pending worker while saving results ordinally,
including waves larger than the worker pool. The parent retains the mutation lock and
original whole-wave budgets/frozen memory. A separate observation lock surrounds exact
CAS pin, reference-only in-memory acknowledgement and channel delivery; waits and caller
control callbacks happen outside it. Pin followed by cancellation/delivery failure retains
the durable row/reference, restores only the precise in-memory increment and stops progress
with stale state for recovery. Active ordinal saves use the captured wave head rather than
synchronizing/adopting latest durable state. Fresh dispatch tokens cannot be reminted by
nested calls or borrowed by recovered/direct/wrong-thread workers.

One transaction runs through durable prepared evidence and owner pin to an inert evaluator
boundary. Real controller/runner/ledger futures and settlement tests use inert gateway and
transaction seams, not the actual native gateway or a sealed CPython runtime. One original
Python admission child plus ordinary siblings is supported; independent Python children
require a separate original proof/journal/attempt routing contract. Production admission
stays false. Real scheduler inputs, runtime/process/journal interruption coverage, actual
Feature189/190 acceptance and local OpenEvolve/Shinka lifecycle remain open.

The controller-lock fix narrows filesystem OSError translation to lock acquisition.
Deadline/timeout/provider OSError raised inside its body now propagates unchanged while
cleanup releases the lock; three regressions cover this previously masked deadline.
Ruff across src/tests/tools, compileall and diff checks pass. The40 focused plus3 full
phases require this source's own Ubuntu3.11/3.12/3.13 CI and raw/source/tree audit before
merge. Earlier PR43–45 evidence cannot approve this BRS slice.

## 2026-10-11 owning-thread DRS first pin

The new `rsi-python-admission-owner.xml` gate requires30 cases with zero failures,
errors or skips:23 owner/facade/settlement cases and7 prepared observer cases.
Root final-source Python3.11.15 verification passed30 in64.948 seconds,222 publication/
transaction/control/store compatibility cases in113.754 seconds, and the controller
agent passed86 flow/producer-checkpoint/controller compatibility cases in192.519 seconds.
The three retained XML inventories contain338 unique cases, without double-counting
the independent review's overlapping cases. Ruff across src/tests/tools, compileall
and diff checks pass. Independent read-only review found no confirmed source blocker.

The owner context captures the original active DRS state and checkpoint on the thread
already holding the controller lock. The prepared observer runs after durable intent
and handoff/anchor verification, before evaluator or terminal replay; pin uses the original
CAS and acknowledgement compares the complete expected checkpoint with only the exact
reference added. Missing rows, unrelated state/head drift, wrong owner/thread, callback
changes, cancellation and deadline refuse. A crash after durable pin but before ack
preserves the row/reference and leaves old state stale, requiring explicit recovery.
An initial compatibility run exposed four legacy direct-dispatch refusals; the scope
now binds only the actual current episode, preserving those older paths without granting
them active-flow authority. The corrected full86-case compatibility run passes.

One integration uses the actual transaction through prepared pin to an inert evaluator
boundary. The successful settlement integration runs the real controller/runner/facade/
ledger, but uses an in-process `_NoSolverGateway` and a transaction callback spy; it
explicitly publishes the fixture native result before real episode/flow settlement.
It proves reference retention and no stale checkpoint adoption, not an actual
`NativeRSISolverGateway`, worker or sealed CPython run. BRS ready/ack scheduling, real
Python scheduler runtime/handoff inputs and the full process/runtime crash matrix remain
open. `production_admission=false`; no real solver, remote evaluator or toolchain ran.
The39 focused phases plus3 full phases require final-source Ubuntu3.11/3.12/3.13 CI
and independent raw/source/tree audit before merge. Existing dependency CI is separate.

## 2026-10-11 controller-bound publication and read-only recovery

The new `rsi-python-publication.xml` gate requires83 cases with zero failures,
errors or skips:52 facade/reference/row/file/SQLite/callback cases, one actual
candidate-move interruption case and30 transaction-control cases. Final local
Python3.11.15 verification passed83 in138.325 seconds (JUnit
`/tmp/lunar-rsi-python-publication-final83-20261011.xml`). Root also passed193
existing transaction/control/intent/staging/retained-recovery/active-control/store/
durable-reference compatibility cases in145.452 seconds (JUnit
`.lunar-evolution/test-results/publication-compat-final.xml`). The author's19
control cases overlap that193-case inventory and are not additional cases.

Independent review resolved the stale no-control parent deadline and a caller
cancellation predicate running after the evidence gate. Dedicated regressions
cover preparation, numeric timeout and pre-commit row loss; evidence latency is
charged once and local explicit cancellation during evidence still refuses.
SQLite read-only mode prevents missing-DB recreation and journal-mode changes;
tests cover removal before connect, empty replacement, nested exception restoration
and per-ledger/thread isolation. The interruption case performs a real candidate
move before injecting failure, then verifies unknown recovery is unchanged and
invokes no evaluator/producer/retry/repair. Post-commit verification adds no new
budget/cancellation gate and preserves durable evidence on refusal.

The final independent read-only review found no further blocker. Ruff across
src/tests/tools, compileall and diff checks pass. Initial failed evidence is retained;
it is not final acceptance. Final-source Ubuntu3.11/3.12/3.13 full CI and independent
raw/source/tree audit remain required, including the corrected PR43 dependency.
This is an explicit existing-pin facade, not automatic first pin, scheduler state
synchronization or real CPython/runtime acceptance. File/SQLite observations are
not globally atomic against hostile concurrent writers; coherent rewriting of all
trusted pins is outside the local model. `production_admission=false`.

## 2026-10-11 durable RSI admission references

The dedicated `rsi-python-admission-flow.xml` gate requires54 cases and zero failures,
errors or skips. Final local Python3.11.15 verification passed all54 in100.085 seconds
(`/tmp/lunar-rsi-python-admission-flow-final54-20261011.xml`), plus276 existing
late-registration/controller/store/native/producer/budget/reconcile/callback compatibility
cases in290.007 seconds (`/tmp/lunar-flow-compat-final-20261011-3.xml`). Root independently
passed18 selected atomic/recovery/history/BRS/cached-replay cases in28.235 seconds.
Those18 overlap the54 and are not additional inventory. The final five settlement/callback
regressions also passed; earlier49-case evidence predates the final fixes.

Independent review found and resolved three blockers: public lock acquisition during
BRS read-only verification, terminal episode writes before checking fresh-result evidence,
and callback execution after its started checkpoint could lose original evidence. The
private read-only evidence/CAS helper, optional runner `before_settlement`, and guarded
callback close these boundaries. Immutable worker result and physical usage remain retained
on refusal. Existing known-terminal settlement after deadline remains valid; the new
settlement hook does not add a budget refusal. Exact pin replay remains read-only after
terminal/unknown states, required missing rows never get recreated, reference history is
monotonic, and original request/proof/budgets/deadlines/plans and unpinned wires stay unchanged.

Frozen SHA256: controller `3cf2449d282c4baa3d8df9a329f6e82c5048bfe5b99ff1cae6ac5ddaa29ffa5f`,
store `976f567c88a95731c26da5c5261bd793aed4175bb78ed1c0fd63fc0962555199`,
admission `9e28150430523e10477bb2274ffa237b81f9f2728dd3b44c2913aae33ca6a753`, and new tests
`d0aaf1bb0a68c25dad4c5f9a0418091d3bd788e735821eea43a15a5da2c2eebc`.
Ruff, compileall and diff checks pass. Final-source Ubuntu3.11/3.12/3.13 CI and independent
raw/source/tree audit remain required before merge; PR41/42 evidence cannot approve this slice.

This is explicit durable evidence pinning, not automatic scheduling/publication composition
or sealed CPython execution. Separate file observations and SQLite are not globally atomic
against a hostile writer, and the local trust model does not resist rewriting every trusted
pin. `production_admission=false`; only local inert fixtures ran. The next P0 slices are
automatic admission-identity composition and the complete runtime/journal crash matrix.

## 2026-10-11 explicit late controller/ledger evidence

The separate `rsi-python-admission.xml` gate requires128 provider-free cases with zero
failures, errors or skips. Locally the original108 cases and143 compatibility cases
passed together (251), before the final two review fixes. After those fixes, root
independently reran20 new regression cases and2 representative successful wire/replay
cases:22 passed with no failures, errors or skips. First PR42 head `23e4581` run38128598448
then exposed four stale test assertions for malformed checkpoint evidence: they expected
`checkpoint_corrupt`, while the reviewed fixed API returns
`rsi_python_admission_evidence_invalid`. Original failed evidence is retained, and
unexecuted full phases are not accepted. Root corrected only the assertion and reran
all128 cases with zero failures/errors/skips (170.732 seconds; retained JUnit
`/tmp/lunar-pr42-root-full-fixed-20261011-03.xml`). The corrected source requires a new
full matrix and independent audit. The author's27 compatibility cases overlap the earlier
compatibility evidence and must not be added to that inventory. All newly verified local
commands use the shared interpreter Python3.11.15. Earlier3.13.12 labels for the128/796
recovery runs were not independently confirmed from raw interpreter metadata; rely on
each PR's actual remote matrix for version-specific acceptance.

Independent final read-only review confirmed fixed RSI errors for corrupt ledger
payloads and the missing-row gate: run/checkpoint/episode must be running, and the
native claim must have no persisted terminal result. Existing exact rows remain
read-only after terminal/unknown transitions. The matrix checks original request/proof,
historical memory, original budgets/deadlines, native claim/plan, prepared journal,
complete anchor, handoff pin and sidecar; stale/callback DTOs, CAS/lock conflicts and
drift refuse without launch, evaluator, budget charge or evidence repair. Ruff,
compileall and diff checks pass. The final source needs its own full three-version CI
and raw/source/tree audit before merge.

The separate row does not alter the original checkpoint wire or automatically make
ordinary resume detect row deletion. Live identity pinning, scheduler/publication
composition and complete runtime crash recovery remain open. This is evidence-only;
`production_admission=false`. See `late-controller-admission.md`.

## 2026-10-11 independent recovery anchor

The dedicated `python-admission-recovery.xml` gate covers128 local provider-free cases
with no failures, errors or skips on Python3.13.12. Combined Feature191, producer-bundle,
handoff-pin and RSI binding compatibility passes796 cases with the same zero counts.
Independent read-only review reran128 new cases and19 selected existing recovery/pin
cases without a blocker. Ruff across src/tests/tools, compileall and diff checks pass.
Each final source still requires its own Ubuntu3.11/3.12/3.13 full CI and raw/source/tree
audit; local evidence does not establish remote CI or merge status.

The matrix checks all three successful recovery decisions, missing and coherently
rehashed field-drift anchors, unsafe files, final-return mutations, handoff/prepared
drift after anchor I/O, original handoff replacement, allowed same-byte content-anchor
replacement, unknown/prepared no-repair behavior, fractional wire projection and
stale/subclass/callback-bearing DTO refusal. Expected bytes come from the independently
pinned handoff; recovery never creates an anchor, launches, evaluates or refreshes budget.
Non-Python behavior remains unchanged. Late controller/ledger admission and complete
real-runtime recovery remain open; `production_admission=false`.

## 2026-10-11 admission content anchor and detached export

The new `python-admission-export.xml` gate covers 127 anchor DTO/I/O, transaction
interruption/callback and OpenEvolve/Shinka detached adapter cases with zero failures,
errors or skips locally on Python 3.13.12. The broader Feature191/bundle/controller
compatibility result is recorded in HANDOFF.md. Ruff, compileall and diff checks pass.
Independent read-only review passed 169 focused/compatibility cases, including both
prepared-intent interruption windows. Exact-source Ubuntu 3.11/3.12/3.13 CI remains
required before this new slice merges.

The anchor is content consistency: same-byte replacement between operations remains
allowed, while original handoff inode identity is independently pinned. The adapter has
no evaluator/admission entry point and performs no I/O. Controller/ledger admission
binding, exact ABI-profile acceptance and actual sealed
CPython/process observation remain open. `production_admission` stays false.
The independent standalone recovery requirement is implemented by the later slice above.

## Existing accepted contract slices

The Phase A binding, create-only durable sidecar, sidecar-aware native recovery gate, and
zero-side-effect admission composition gate below are complete against inert local fixtures.
No real CPython process/runtime lifecycle acceptance is complete. Until Features189 and 190
pass their dedicated Linux gates, only provider-free inert fixtures may run. The sidecar bound
is 2 MiB, synchronized with the binding parser. The controller checkpoint binding and the
composition gate are covered by focused provider-free tests; neither slice is a proof of runtime
execution, CPython observation, or production admission.

The current focused local command covers the gate, handoff, and lifecycle contracts:
`tests/test_python_producer_admission_gate.py`,
`tests/test_python_producer_admission_handoff.py`, and
`tests/test_python_producer_lifecycle.py`. It passes 198 cases with zero failures,
errors, or skips under the repository's pinned virtualenv. Ruff, `compileall`, and
`git diff --check` also pass. This is provider-free DTO and fixture evidence only;
the gate uses caller-supplied detached owner/envelope/material projections and does not
independently observe a process, filesystem, or evaluator. It does not enable the real sealed
runtime or production admission path.

The dedicated CI report `python-admission.xml` requires this 198-case inventory with
zero failures/errors/skips on Python 3.11/3.12/3.13 and is preserved with the other reports.
Re-signed drift cases independently exercise timeout, native monotonic deadline,
runtime target, stable output capture, producer identity/request count and publication
state checks. Canonical envelope and raw output-file digests intentionally differ;
the executable-owner projection also intentionally differs from child process ownership.
The publication matrix includes durable handoff removal after evaluator return and
verifies refusal without archive changes or a publication marker.

Original handoff identity is a separate retained-file boundary under
`retained-handoff-file-pin.md`. Fifty-five handoff cases cover original exclusive
creation, exact read-only replay, pre-I/O pin validation, same-byte inode replacement,
touch/mode/link/symlink/batch drift, read/write/fsync races and orphan/unknown writes.
Protected publication retains the complete pin in the immutable prepared journal;
callback, direct staging, unknown-marker, terminal/rejected replay and recovery cases
require the same original evidence and assert no evaluator retry or publication on
refusal. Non-Python golden journal bytes stay unchanged. Mutated DTO/callback pin
objects and nested callback mappings are refused before serialization can coerce them.
The dedicated `python-handoff-pin.xml` report includes publication-journal and direct
publication pin regressions, with a frozen 52-case zero-failure/error/skip inventory. The
expanded producer-recovery report has 116 cases. These are provider-free local checks;
controller admission-attempt anchoring and actual sealed CPython evidence remain open.
The final combined local admission/journal/intent/transaction/staging/rejection/recovery
regression passes 354 cases with no failures, errors or skips; final-source full CI
remains required before merge.

The current controller recovery hardening has passed the focused provider-free matrix and
independent boundary review and PR32 final-source CI; it is merged at `6a912609d3e5e9811bc8dbae77b1df077976afe7`. Its
required matrix covers sidecar failure before run
creation; sidecar loss/drift after preflight and before the first checkpoint; a valid retained
sidecar with missing first checkpoint; restart without the required sidecar; symmetric terminal
and nonterminal run/checkpoint proof mismatch; latest/earliest-run-revision proof addition,
removal or replacement; attempted sidecar retrofit into an originally unbound run; pre-fix
producer checkpoint without original-run proof; checkpoint identical/no-op save; direct episode
recovery; and terminal settlement/replay. Callback and native-failure reconcile must cover entry
and pre-publication drift, including already-reserved branches. Each refusal must avoid further
checkpoint/journal/terminal mutation, dispatch/callback execution and budget consumption;
reservations durable before the failed check remain consumed and are not rolled back.
Valid reconstruction must preserve
the immutable run request digest, producer proof, original planned budget/deadline and all
fingerprints. Passing an older PR head does not approve these later changes.

The early CI preparation gate combines the recipe, installation, ELF, binding
and lifecycle suites into `python-preparation.xml`: exactly 226 cases with zero
failures, errors or skips on each supported Python version. This is a pure
contract gate and does not count as CPython build or runtime startup acceptance.

Final-source run37829395862 at37729c9a passed the preparation gate but its
Python3.12 broker regression exposed a pre-existing 0.2-second worker-startup
assumption. The slow-body test now allows two seconds under the original
absolute deadline and verifies the worker's encoded deadline, deadline expiry,
single origin/no redirect and exact reap. The 87-case broker suite passes
locally. Original ZIP/XML/job log and source inventory remain separate in
ignored reports/pr24-first-failed-head-37729c9a; replacement final-source CI is
required and this first failure is not reclassified as a pass.

The separate `python-observation.xml` gate runs exactly 43 provider-free adapter
cases with zero failures, errors or skips. Its compatibility inputs are generated
by the reviewed emitted frozen-main asset with explicit fake sys/loader/pipe
objects. It verifies pure parsing and asset-wire compatibility, including the
fixed path/version/inventories/origins, actual flag types, one broker JSON frame,
one optional stdout newline and bounded callback-free dict shapes. These tests
are not observations of a running static CPython image and do not complete real
runtime observation, startup or loader-negative enforcement acceptance. The
workflow annotates both contract reports and retains both XML files separately.

| Area | Required evidence | Refusal cases |
| --- | --- | --- |
| Binding parser | **Complete Phase A:** canonical nested DTO round trip, exact type/order/bounds, shape-gate, digest/deadline/limit drift and fixed errors | unknown field, bool-as-int, duplicate key, placeholder digest, callback-bearing collection, path/env/target drift |
| Durable binding sidecar | **Complete provider-free slice:** canonical bytes are published create-only through a temporary file and hard-link; final file is regular `0600` with one link; controller-retained digest/size/device/inode/mode/nlink/mtime/ctime pins are checked before workspace I/O and against pre/read/post file observations; sidecar is bounded at 2 MiB | existing sidecar, batch already started, missing batch/sidecar, malformed retained pin, binding mutation, byte/digest drift, replacement, touch, mode/link/inode drift, symlink, oversized record, temporary-file residue |
| RSI controller checkpoint binding | **Complete provider-free slice:** sidecar preflight precedes durable run creation; immutable run request/digest retain canonical producer proof/pin; latest proof equals earliest ledger run proof and each checkpoint matches symmetrically; missing first checkpoint reconstructs from the original run proof/budget/fingerprints with live sidecar revalidation; intent preparation, cached execution reuse, post-admission/pre-gateway dispatch, direct/native episode recovery, save/no-op and terminal settlement/replay revalidate; callback completion and callback/native-failure reconcile revalidate at entry and pre-publication, including previously reserved branches; legacy producer checkpoints without original-run proof fail closed; provider-free checkpoints keep their existing shape. Local evidence: 61 dedicated recovery cases and 131 controller/replay cases, zero failures/errors/skips; independent boundary review and PR32 final-source CI complete; merged at 6a91260. | proof addition/removal/replacement, unbound-run sidecar retrofit, missing checkpoint proof, run/binding/pin mismatch, deleted/replaced/touched sidecar, drift after preflight, admission, native replay, callback or between episodes, restart omitting the sidecar, terminal proof bypass, no-op save bypass, direct recovery/settlement/reconcile bypass, extra budget/journal on refusal or rollback of prior durable reservations, producer workspace supplied without a sidecar |
| Pure terminal/reconcile | **Complete contract slice:** 99 focused tests cover canonical DTOs, retained digest recheck, complete known-terminal evidence, original identity/journal/deadline/stream pins, exact collection shapes, and optional retained admission-anchor identity/fingerprint checks before replay/reconcile | mutated reused DTO, missing/zero digest, drifted registration/owner/executable/journal/stream, missing or out-of-order timestamps, refreshed deadline/request count, callback mappings/iterables, publication claim, relabeled attestation consumption or discarded known exit evidence |
| Pure fixture observation adapter | **Complete contract slice:** 43 cases generated from the reviewed frozen-main asset with fake runtime inputs; independently supplied broker bytes and pycache fact | host path/version/ABI substitution, inventory or module-origin drift, wrong exact flag type, invalid/nested/duplicate/multiple/truncated broker frame, extra stdout newline, zero binding digest, callback-bearing dict/list/text, aggregate overflow |
| Runtime closure | Original manifest/tree digest, no-follow identity snapshots and target ABI | missing interpreter, symlink/hardlink, unlisted file, changed inode/bytes/resource/native input |
| Launch | Exact argv/env, intent+attestation, private owner and original deadline | host Python substitution, argv/module/path injection, env leak, deadline/nonce drift |
| Loader policy | Readable decoy source/pyc/extension/zip and unknown codec are refused | permission-only denial, `sys.path` discovery, `.pth`/site/customization/pycache |
| Fixture execution | Real CPython version/cache tag/flags, fixed computation, one broker exchange, bounded envelope | fabricated observation, oversized output, second request, malformed response |
| Lifecycle | registration, ready/release/start/terminal, request journal, reap and FD census | parent loss, cancel, signal, nonzero exit, cleanup uncertainty, missing terminal |
| Resume/recovery gate | **Complete provider-free slice:** `recover_python_producer_terminal` requires the retained sidecar, verifies it before native inspection and after native inspection, and never creates a recovery lock/marker or consumes a budget; pure resume/reconcile still preserves original deadline, journal and evidence pins | blind restart, refreshed budget, changed binding/fingerprint, changed journal, missing sidecar, sidecar replacement during recovery, cleanup unknown/missing, native recovery-required |
| Admission | **Provider-free plumbing and composition gate complete:** canonical handoff, create-only persistence, journal/evaluation links, canonical DTO reparse, sidecar/checkpoint pin, identity/deadline/limit/authority links, brokered native receipt, terminal/runtime claims, and caller-supplied detached envelope/owner/material consistency pins are covered by local synthetic fixtures; the gate is read-only and always returns `production_admission=false` | external score/correct/generation used as Lunar rank or validity; unknown/failed journal or cleanup, drifted DTO/receipt/identity/deadline/authority pin, missing independent pin, unbrokered receipt, protection claim, or any attempt to treat the local gate result as sealed-runtime/production admission |
| Adapters | Explicit OpenEvolve wrapper and Shinka program/result export through common envelope | automatic project discovery/start, remote/Slurm/network campaign |

The dedicated run must retain raw process terminal, broker journal, runtime
observation, source/tree identity, ELF/static audit and first failure artifacts.
An independent review must verify that `execution_performed` and successful
publication are derived from observed Python/process/evaluator evidence, not from
descriptor fields or child claims. `runtime_load_protection`,
`production_admission` and `general_code_origin_protection` remain false.

## Python scheduler pre-staged input join

Final local Python3.11.15 gate passed **81 cases** in66.608 seconds, with zero failures,
errors or skips. The disjoint existing native-input/plan/scheduler and Python binding /
checkpoint/runtime-tree compatibility gate passed **250 cases** in33.743 seconds;
the two final inventories contain331 unique cases. Root evidence remains in ignored
reports `python-scheduler-inputs-final-20261012e.xml` and
`python-scheduler-inputs-compat-20261012c.xml`. Earlier71-case selected and10-case
boundary runs are auxiliary evidence, not additional unique cases. Initial failures
and independent review findings remain retained separately.

The gate covers immutable context, canonical retained sidecar/checkpoint join, stable
repeated plans, original deadline preservation, cross-domain identity/runtime drift,
two-read replacement races, file metadata and zero-side-effect guarantees. Exact DTO
shape and plain-collection gates precede callbacks, readers and serializers; original
caller request/memory/context are rechecked after observations. Opaque strategy, broker,
control and ledger objects are neither compared nor invoked. Foreign mapping proxies
and instance serializer shadowing refuse. The factory commits to31 named local code
dependencies without claiming general dependency discovery or remote authenticity.

Independent frozen-source review passed81/81 with source and test hashes unchanged.
Ruff across src/tests/tools, compileall and `git diff --check` pass. The new CI report
`rsi-python-scheduler-inputs.xml` requires81 cases and zero failures/errors/skips and is
annotated/uploaded. The final source still requires its own Ubuntu3.11/3.12/3.13 full CI
and independent raw/source/tree audit; this workflow has41 focused and3 full phases.

Only inert local fixtures ran and `production_admission=false`. No Python runtime,
native gateway, OpenEvolve/Shinka campaign or production CLI acceptance occurred.
Original sidecar/runtime and request/memory timestamp drift refuses. Existing native
manifest/launch records self-bind bytes/device/inode without an independently retained
original timestamp, so a touch completed before observation remains accepted. Two reads
are not an atomic filesystem snapshot. Live runtime/handoff composition and the full
process/runtime/journal interruption matrix remain separate work.
