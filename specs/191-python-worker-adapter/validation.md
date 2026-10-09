# Validation plan

The Phase A binding, create-only durable sidecar, and sidecar-aware native recovery gate below
are complete against inert local fixtures. No real CPython process/runtime lifecycle acceptance
is complete. Until Features189 and 190 pass their dedicated Linux gates, only provider-free inert
fixtures may run. The sidecar bound is 2 MiB, synchronized with the binding parser. The
controller checkpoint binding is covered by focused provider-free tests; neither slice is a
proof of runtime execution or CPython observation.

The current controller recovery hardening has passed the focused provider-free matrix and
independent boundary review; exact-final-source CI remains pending for the final source. Its
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
| RSI controller checkpoint binding | **Complete provider-free slice:** sidecar preflight precedes durable run creation; immutable run request/digest retain canonical producer proof/pin; latest proof equals earliest ledger run proof and each checkpoint matches symmetrically; missing first checkpoint reconstructs from the original run proof/budget/fingerprints with live sidecar revalidation; intent preparation, cached execution reuse, post-admission/pre-gateway dispatch, direct/native episode recovery, save/no-op and terminal settlement/replay revalidate; callback completion and callback/native-failure reconcile revalidate at entry and pre-publication, including previously reserved branches; legacy producer checkpoints without original-run proof fail closed; provider-free checkpoints keep their existing shape. Local evidence: 61 dedicated recovery cases and 131 controller/replay cases, zero failures/errors/skips; independent boundary review complete. Exact-final-source CI remains pending. | proof addition/removal/replacement, unbound-run sidecar retrofit, missing checkpoint proof, run/binding/pin mismatch, deleted/replaced/touched sidecar, drift after preflight, admission, native replay, callback or between episodes, restart omitting the sidecar, terminal proof bypass, no-op save bypass, direct recovery/settlement/reconcile bypass, extra budget/journal on refusal or rollback of prior durable reservations, producer workspace supplied without a sidecar |
| Pure terminal/reconcile | **Complete contract slice:** 98 focused tests cover canonical DTOs, retained digest recheck, complete known-terminal evidence, original identity/journal/deadline/stream pins and exact collection shapes | mutated reused DTO, missing/zero digest, drifted registration/owner/executable/journal/stream, missing or out-of-order timestamps, refreshed deadline/request count, callback mappings/iterables, publication claim, relabeled attestation consumption or discarded known exit evidence |
| Pure fixture observation adapter | **Complete contract slice:** 43 cases generated from the reviewed frozen-main asset with fake runtime inputs; independently supplied broker bytes and pycache fact | host path/version/ABI substitution, inventory or module-origin drift, wrong exact flag type, invalid/nested/duplicate/multiple/truncated broker frame, extra stdout newline, zero binding digest, callback-bearing dict/list/text, aggregate overflow |
| Runtime closure | Original manifest/tree digest, no-follow identity snapshots and target ABI | missing interpreter, symlink/hardlink, unlisted file, changed inode/bytes/resource/native input |
| Launch | Exact argv/env, intent+attestation, private owner and original deadline | host Python substitution, argv/module/path injection, env leak, deadline/nonce drift |
| Loader policy | Readable decoy source/pyc/extension/zip and unknown codec are refused | permission-only denial, `sys.path` discovery, `.pth`/site/customization/pycache |
| Fixture execution | Real CPython version/cache tag/flags, fixed computation, one broker exchange, bounded envelope | fabricated observation, oversized output, second request, malformed response |
| Lifecycle | registration, ready/release/start/terminal, request journal, reap and FD census | parent loss, cancel, signal, nonzero exit, cleanup uncertainty, missing terminal |
| Resume/recovery gate | **Complete provider-free slice:** `recover_python_producer_terminal` requires the retained sidecar, verifies it before native inspection and after native inspection, and never creates a recovery lock/marker or consumes a budget; pure resume/reconcile still preserves original deadline, journal and evidence pins | blind restart, refreshed budget, changed binding/fingerprint, changed journal, missing sidecar, sidecar replacement during recovery, cleanup unknown/missing, native recovery-required |
| Admission | **Provider-free plumbing only:** the canonical handoff, journal/evaluation links and synthetic native composition are covered by local fixtures; runtime-gated production admission is still false until sealed CPython and lifecycle evidence are accepted | external score/correct/generation used as Lunar rank or validity; DTO/receipt claims without independently observed runtime/process/evaluator evidence |
| Adapters | Explicit OpenEvolve wrapper and Shinka program/result export through common envelope | automatic project discovery/start, remote/Slurm/network campaign |

The dedicated run must retain raw process terminal, broker journal, runtime
observation, source/tree identity, ELF/static audit and first failure artifacts.
An independent review must verify that `execution_performed` and successful
publication are derived from observed Python/process/evaluator evidence, not from
descriptor fields or child claims. `runtime_load_protection`,
`production_admission` and `general_code_origin_protection` remain false.
