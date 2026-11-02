# Capped benchmark case acceptance — 2026-11-02

Status: both real ordinary-model attempts failed. Independent original-evidence
audits passed; neither case produced a completed receipt, submission or score.
Ordinary-model E2E P0 remains open.

## Registered measurement

The [registered plan](../specs/061-subject-failure-diagnostics/capped-benchmark-case-acceptance.md)
selects two public-format variants copied from local benchmark materials:
`train_delay_rescheduling` and `hospital_or_scheduling`. Original files and
historical attempts remain unchanged. The model receives only the declared
public instruction/data/format files; no solution or scoring baseline is added
to those inputs. This trusted local measurement does not establish OS isolation
or private evaluator inaccessibility.

Frozen main is `16447a6b632d4806344b2c9ac6435e14542112e0`, tree
`6bef093284d724fafbb4537dd474ddb675d0e2c2`, with 2,822 files and 308
directories per independent source copy. Its software equals the PR214 version
already tested by [CI 41403780073](https://github.com/vchive/Lunar-Evolution/actions/runs/41403780073):
all 45 jobs successful. No product code, tests, tools or dependencies changed
for this measurement, and no complete software regression was repeated.

Registration commit `19b40179e11917d75f1d0a8be8faf5830f4a7d86` was pushed
before dispatch. The create-only batch registration SHA256 is
`89440c7a6ad6fec9a0e1280561730ef53c271f3d46388b3e44b54863b0f06e3e`.
Both attempts launched once at approximately `2026-11-02T11:52:58Z`
(19:52:58 Beijing time). Each used the previously configured model, 3,000
subject seconds, 40 individual tool calls, a 160,000 observed-token stop
threshold, explicit `max_completion_tokens=16384` and zero retries.

The original bounded supervisor, completion/receipt gate and conditional
local evaluator path were reused. The cap is a newly configured profile
policy, not a hard aggregate billing cap or proof of gateway enforcement.

## Actual results

| Observation | Train delay | Hospital operating rooms |
| --- | --- | --- |
| Subject outcome | rc2, 141.094818 seconds | rc2, 140.329087 seconds |
| Accepted model responses / tool results | 2 / 4 | 3 / 9 |
| Request events | 2 completed, then 1 failed | 3 completed, then 1 failed |
| Terminal reason | schema7 `model/model_failed`, `transport_error` | schema7 `model/model_failed`, `transport_error` |
| Failed-request elapsed | 129.302 seconds | 126.993 seconds |
| Remaining request allowance at dispatch | 2,989.400 seconds | 2,987.854 seconds |
| Last local phase / milestone | `open_response` / `wait_response_headers` | `open_response` / `wait_response_headers` |
| Observed HTTP status | null | null |
| Accepted partial usage | 3,494 input + 64 output = 3,558 tokens | 5,989 input + 156 output = 6,145 tokens |
| History | 8 messages, 2 complete tool batches, zero pending results | 14 messages, 3 complete tool batches, zero pending results |
| Completed receipt / submission | neither | neither |
| Evaluator / scores | not invoked / null | not invoked / null |
| Original child / pipes | reaped / EOF verified | reaped / EOF verified |
| Outer watchdog / signals | none | none |

All five early accepted requests returned HTTP 200. The failed requests ended
well before the configured deadline and did not return an observed HTTP status.
These results are transport failures, not observed budget exhaustion or the
explicit capped-length rejection. The fixed observations do not identify
which client, network, gateway or inference-service component failed.

Failed-request token usage, server cancellation, complete billing and complete
foreign-process cleanup remain unknown. The accepted counters are partial;
they must not be presented as a complete usage bill. No failed response was
accepted and no score was fabricated or replaced with a fixture result.

## Retained evidence

The primary workspace retains each run under ignored
`.lunar-evolution/validation/capped-benchmark-cases-20261102/`, in child
directories named after the two cases. Each includes its frozen manifest,
source archive/copy, case, profile, original request/receipt-failure/history,
redacted logs, process facts and before/after evidence. Secrets and private
model/profile contents are not published here.

The reviewed `audit-original-terminal-v1.py` executed once per case, without
model, evaluator, configuration or product-test execution. Its SHA256 is
`a33329af15d618379054f0c67a81ade1dd06383fd92cb55d0912f142c8a2bede`.
Both audits passed and independently classified acceptance as failed:

| Original audit | Bytes | SHA256 |
| --- | --- | --- |
| Train `terminal-original-audit-v1.json` | 869,192 | `91768765654a1409ff862599a0efa8e5a06cb0482d9bea65723c15a5502ac28a` |
| Hospital `terminal-original-audit-v1.json` | 864,917 | `5b05cc866d50b94eaaa4184b72e6381455ac14933735e74b4d8318de0801e0e8` |

The audits verified source/case bytes and modes, opaque profile byte/hash
bindings, 240 actually loaded Lunar module origins per run, receipt/evaluator
refusal, original secret-scan scope, strict history pairing and complete
request-event chains.
Failed-event and failure-diagnostic fingerprints/reasons/statuses match;
their independently sampled elapsed values agree to the millisecond.
Audit success verifies the failed records, not task completion.

An independent direct crosscheck passed 48/48 evidence checks without rerunning
the audits, inference or evaluation. Its 7,207-byte report SHA256 is
`c05a16640eb3a6db04f6ea3d0b56fd262803252f67016b1a27f5f83d1c865610`.

The original serialized HTTP bodies were not retained. A separate independent
check reconstructed candidates entirely in memory from frozen source literals,
the retained history and the request-only budget advisory. Both byte counts
and SHA256s exactly match the original failed-request fingerprints:

| Case | Serialized bytes | Original / reconstructed SHA256 |
| --- | --- | --- |
| Train | 10,456 | `593be7b7a7eb74191e6c529111b515b7bff6e600d83ba071a7e35ee0c9d44085` |
| Hospital | 14,132 | `27556e57f6258ceaf4f2f22c9239247ab8a3031587fe13fd0fbb13a092560467` |

Each matching candidate contains `max_completion_tokens=16384`, five ordinary
tool schemas and a strictly paired tool history, with zero pending results or
normalization markers. The reconstruction used a restricted static AST reader
and standard-library JSON, without importing the product or making requests.
No candidate body, prompt, tool content or model identity was retained in the
report. Its 12,965-byte SHA256 is
`6cc753ce9974e8011a0a37331dd31efe3207ba1ba65f7f6b90001cdcd09509da`.
This supports the initial serialized request shape; it is not an original wire
capture or proof of endpoint receipt, gateway enforcement or failure cause.

The earlier preparation review's title/lineage assumption errors and their
corrections remain recorded separately; prepared execution bytes did not change.

## Next boundary

The useful next diagnostic is a fixed, non-sensitive distinction between
transport failure categories; the current generic reason cannot distinguish
a peer close, connection reset, DNS/TLS failure or another local transport
error. No server-side cause is established by this measurement.

These two failures extend real-case coverage while leaving reliability and
solver quality unaccepted. Native RSI P1 remains separate, with
`production_admission=false` and `online_publication=false`. No WebAgent,
remote/company evaluator, native RSI campaign or historical attempt rerun
occurred.
