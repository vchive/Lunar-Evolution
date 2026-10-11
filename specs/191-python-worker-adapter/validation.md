# Validation plan

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
| Pure terminal/reconcile | **Complete contract slice:** 98 focused tests cover canonical DTOs, retained digest recheck, complete known-terminal evidence, original identity/journal/deadline/stream pins and exact collection shapes | mutated reused DTO, missing/zero digest, drifted registration/owner/executable/journal/stream, missing or out-of-order timestamps, refreshed deadline/request count, callback mappings/iterables, publication claim, relabeled attestation consumption or discarded known exit evidence |
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
