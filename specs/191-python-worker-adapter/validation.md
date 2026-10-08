# Validation plan

The Phase A binding and pure lifecycle contract checks below are complete and
run against inert local fixtures. No durable process/runtime lifecycle acceptance
is complete. Until Features189 and
190 pass their dedicated Linux gates, only provider-free inert fixtures may run.

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
| Pure terminal/reconcile | **Complete contract slice:** 98 focused tests cover canonical DTOs, retained digest recheck, complete known-terminal evidence, original identity/journal/deadline/stream pins and exact collection shapes | mutated reused DTO, missing/zero digest, drifted registration/owner/executable/journal/stream, missing or out-of-order timestamps, refreshed deadline/request count, callback mappings/iterables, publication claim, relabeled attestation consumption or discarded known exit evidence |
| Pure fixture observation adapter | **Complete contract slice:** 43 cases generated from the reviewed frozen-main asset with fake runtime inputs; independently supplied broker bytes and pycache fact | host path/version/ABI substitution, inventory or module-origin drift, wrong exact flag type, invalid/nested/duplicate/multiple/truncated broker frame, extra stdout newline, zero binding digest, callback-bearing dict/list/text, aggregate overflow |
| Runtime closure | Original manifest/tree digest, no-follow identity snapshots and target ABI | missing interpreter, symlink/hardlink, unlisted file, changed inode/bytes/resource/native input |
| Launch | Exact argv/env, intent+attestation, private owner and original deadline | host Python substitution, argv/module/path injection, env leak, deadline/nonce drift |
| Loader policy | Readable decoy source/pyc/extension/zip and unknown codec are refused | permission-only denial, `sys.path` discovery, `.pth`/site/customization/pycache |
| Fixture execution | Real CPython version/cache tag/flags, fixed computation, one broker exchange, bounded envelope | fabricated observation, oversized output, second request, malformed response |
| Lifecycle | registration, ready/release/start/terminal, request journal, reap and FD census | parent loss, cancel, signal, nonzero exit, cleanup uncertainty, missing terminal |
| Resume | Completed replay is read-only; unknown reconcile is idempotent under original deadline | blind restart, refreshed budget, changed binding/fingerprint, changed journal |
| Admission | Local exact evaluator receipt and atomic seed/publication evidence | external score/correct/generation used as Lunar rank or validity |
| Adapters | Explicit OpenEvolve wrapper and Shinka program/result export through common envelope | automatic project discovery/start, remote/Slurm/network campaign |

The dedicated run must retain raw process terminal, broker journal, runtime
observation, source/tree identity, ELF/static audit and first failure artifacts.
An independent review must verify that `execution_performed` and successful
publication are derived from observed Python/process/evaluator evidence, not from
descriptor fields or child claims. `runtime_load_protection`,
`production_admission` and `general_code_origin_protection` remain false.
