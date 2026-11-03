# Ordinary subject: independent public execution environment

Status: one new attempt finished, failed with invalid_tool_calls, 2026-11-03.
PR219/220 are merged; software baseline is main7038fae1, tree
25e55f36682d357aca05368e30731843a0277fe5. Reuse its completed software validation.

The preceding extended steel attempt stopped at runtime/input_required after
asking which Python to use. Its history had already found a usable interpreter;
this does not establish missing dependencies everywhere or a runtime defect.
Preserve that failure and its unknown historical usage. The next experiment
removes a public execution-environment ambiguity, with independent case,
publication, request, manifest and attempt identities. It does not retry/resume
or replace any old result.

## Contract and implementation boundary

Use existing PublicFile/entrypoint, without a new request field or DTO. Preserve
the previous fourteen copied files byte for byte. Add public-task-environment.md,
retaining the entire old public-task.md as prefix, then append only locally
verified Python3.13/pandas availability and a direct argv example using command
name python3.13. Keep solution.csv and business rules. Do not add algorithms,
answers, baseline, private evaluator details, credentials or local absolute paths
to the preloaded public request. Ordinary tool output remains unchanged.

Bind the new entrypoint consistently in identity basis, publication basis,
case-manifest and request-template, with exact new public ledger and digest.
Use a fresh ignored preparation root ordinary-public-environment-20261103.
Original benchmark, copied old cases, attempts, helpers and evaluator stay intact.

Register subject PATH explicitly as
/Users/liminghan/miniforge3/bin:/usr/bin:/bin:/usr/sbin:/sbin. Every component must
be a nonempty absolute directory. Reject empty, dot or relative components,
exact-value drift, command resolution drift and registered interpreter pin drift
before model invocation. Resolve python3.13 with that PATH in actual subject cwd;
absolute directory components also make executable selection cwd-independent.
Publish only the command name. Private evidence binds executable bytes/mode,
Python version, pandas version/origin and the exact environment. This is a local
observation, not a complete immutable dependency closure or sandbox guarantee.

Keep controller Python separate from subject command Python and evaluator Python.
The subject child process has registered PATH/LANG/PYTHONDONTWRITEBYTECODE; the
actual tool environment also includes LC_ALL and PYTHONUTF8, exactly matching
the adapter's existing five-key environment. The bounded import-only preflight
must use those same five keys and actual subject cwd, direct argv, no login shell.
Use existing libraries only; no installation, download, solver or evaluator.

Use independent process dictionaries. The evaluator process environment is newly
registered as PATH=/usr/bin:/bin:/usr/sbin:/sbin, LANG=C.UTF-8 and
PYTHONDONTWRITEBYTECODE=1. Historical evaluator PATH was not fully recorded; this
is an explicit new private environment, not a reconstruction. Keep original
hash-locked evaluation venv, inventory, flags and evaluator bytes. Do not derive
or mutate this mapping from subject environment.

Only new private measurement helpers change: preparer, environment gates,
subject-child and launcher. Product Runtime/AgentLoop/tools/adapters, HTTP wire,
receipt schemas, ask_user behavior and parser are unchanged.

## Checks before dispatch

Independently review exact scripts before execution. Run one provider-free fake
interface batch: complete new declaration reaches prompt; direct argv/cwd/tool
environment reaches intercepted process seam; missing/drifted/unlisted entrypoint
and mismatched registration reject before fake invocation; PATH shape/value,
resolution and pin drift reject before model invocation; actual prepared ledger
and four identity bindings match. Guard real provider/network/process/evaluator.
Observe both launcher process environments through its seam, proving independent
mappings. Do not mistake adapter acceptance of an old valid entrypoint for a
registration-gate pass.

Prepare fresh inputs without configuration reads. A separately supervised local
import-only check has 60 seconds plus 5 seconds KILL/reap, no TERM grace and
1MiB per-stream capture. It captures actual Python/pandas versions/origins and
rechecks interpreter/environment binding. Preserve failures; do not silently
retry or fabricate availability. Only successful evidence permits publishing the
declaration and final manifest. Recheck exact environment/resolution/binary before
dispatch, and repeat import-only capability check once at launch to reject drift.

Freeze source archive and full source/case/profile inventories, actual loaded
module provenance, exact helper pins and import observations. Independently
review prepared inputs, push concrete registration, then bind existing user
authorization to that manifest and reserve exactly one fresh attempt.

## One independent model attempt

Preserve the original extended profile's exact212 bytes: deepseek-chat,
80 tools, 1,000,000 observed cumulative tokens, 3,000 subject seconds and
max_completion_tokens=16,384. The observed-token threshold is not a hard billing
cap. Zero inference retries/fallback, no increased budget, automatic ask_user
answer, answer repair, extractor or continuation of old attempts.

Preserve subject watchdog3020 seconds, TERM/KILL5 seconds each, 1MiB captures and
existing receipt validator. Only a genuine completed receipt plus original root
solution.csv permits unchanged local evaluator once:30 seconds, no TERM grace,
KILL/reap5 seconds, no model credentials. Verify venv before launch, immediately
before evaluation and after. Require evaluator rc0, finite scores and validity1
for this functional smoke; report quality separately. Failure remains failure.

New declaration and environment constitute different measurement inputs. Success
would not overwrite old failures, establish same-budget parity, general model
reliability or evolution benefit. Native RSI P1 stays separate;
production_admission=false and online_publication=false.

## Tasks

- [x] Scope this independent experiment using the reviewed v2 draft.
- [x] Implement and independently review private helpers and bounded check.
- [x] Prepare new inputs; complete one fake batch and capability check.
- [x] Review concrete frozen manifest and push registration.
- [x] Run exactly one new attempt under existing user authorization.
- [x] Review originals and publish actual result without rerunning scoring.

No new full software CI is needed when tracked changes are documents only and
the frozen product tree remains the accepted baseline. Run focused measurement
checks plus ruff, compileall and git diff --check for the new scripts. Preserve
earlier regression evidence rather than repeating it to obtain new run IDs.

## Prepared registration

Fresh root: primary workspace ignored
`.lunar-evolution/validation/ordinary-public-environment-20261103/steel_coil_cutting/`.
Attempt: ordinary-deepseek-7038fae1-steel-public-environment-20261103-attempt-001.
Manifest7,335 bytes/SHA256:
`04db3c813d5855b73ff7943c550929c0e1b8d86a024fcd5e41bd1f91cbd167a1`.
Source2,835 files/308 directories, new case15 files/public6; original14 and
benchmark13 files preserved. Profile remains212 bytes/SHA256
`a84a457b72f181cae593aa98b62156b3566e0d26df5de5273377ceed2e4052b1`.
Case digest:
`4b2f455718b2bb5592689e3f089e3ef1004e97685fb60228591afac81e6c596b`;
publication digest:
`fa2191c029e59619a76d94dbbba662ce93e08d3d67286e661971fd91ad418979`.

The single preparation took2.274244625121355 seconds/rc0. Its import-only
probe took0.5095894997939467 seconds/rc0/reaped/EOF, no signals, observing
Python3.13.12 and pandas3.0.6. Only interpreter/pandas-init observations are
bound, not a complete dependency closure. The original independent evaluation
venv remains4,586 files/434 directories; its pandas version is a separate fact.

One provider-free interface batch passed in3.4026698330417275 seconds,
rc0/reaped/EOF and no signals:4 adapter scenarios,27 refusal cases and the
real launcher's3 intercepted environment seams. All234 actually imported
product modules match frozen source/origins/Git blobs. No provider, real tool
process, evaluator, score or owner configuration read occurred. Test originals
and exact source binding are in interface-check-v1 stdout/stderr/process.

Independent helper static review SHA256:
`99000fd3ba98e5d80fbcb2d2d56ade4c4e5db10e57259801f6babade05c60435`.
Independent interface-script review SHA256:
`435bf25c05e3363ac4e15a886e3b2a22cbf361451fcb7c72777a32c78ffcd719`.
Independent concrete preparation review SHA256:
`12fd7845eaecefa985f766849ff514d33de829e2ce9bbbd9525f0eae4c202350`.
The expected final request is1,706 bytes/SHA256
`b11ec4b2b4d7480f95aba75df507ab491b2f10c4726bb5294f165ab89f2880ed`,
with profile protocol digest
`1a23936019ee417aad421f1e6f83a4f7583d56012b5d85f5059cb85dc16f3496`.
New-script Ruff, compileall and diff checks pass; temporary compile cache removed.
Preparers/helpers had initial style-only Ruff failures; original versions remain
under pre-lint-scripts. Final lint fixes retain secret-safe refusal semantics.
The outer supervision wrapper's executed original is retained separately as
run-preparation-v1.executed.py; its later import cleanup was not rerun.

These are preparation/interface results, not real model or RSI acceptance.

## Actual outcome

Registrationa2668db3 was verified remotely before manifest-bound authorization.
The single attempt began2026-11-03T05:48:05.698813Z and failed rc2 after
12.861271333415061 subject seconds, original child reaped/EOF and no signals.
SixHTTP200 responses:five completed and the sixth rejected as invalid_tool_calls,
with opt-in fixed category arguments_invalid_json. Accepted5rounds/10tools and
20,135 partial tokens (input19,665/output470), cost unknown; rejected usage unknown.
Two accepted direct python3.13 commands exited0. Both import observations match.
No completed receipt/solution/evaluator/score, timeout or budget failure. Source/case/profile/
evaluation environment checks pass and all240 actual product modules match.
The existing JSON parser, budget and zero-retry behavior were not changed.
Original evidence independent review3,705 bytes/SHA256:
`674eb539250649814e10ed6bea188353d2a4f0fbdf28b49bc22334aff68e631b`.
The review confirms failure and input/usage/process integrity, not acceptance.

See [actual results](../../docs/ordinary-public-environment-acceptance-20261103.md).
P0/nativeRSIP1 remain open, and production/publication authority remains false.
