# Ordinary-model long-run acceptance — 2026-11-02

Status: failed; independent original-evidence audit complete. The single fresh
attempt ran from 02:13:07 to 03:03:09 Beijing time on 2026-11-02
(`2026-11-01T18:13:07.414622+00:00` to
`2026-11-01T19:03:09.057330+00:00`). No local evaluator was invoked.

## Registered conditions

This is the independently specified [long-run acceptance](../specs/061-subject-failure-diagnostics/ordinary-model-long-run-acceptance.md),
using the same model and unchanged copied train-delay case as the earlier
ordinary smoke. It uses frozen product main
`5c62ca270d78c605ca189399c8b8caadcd11e1b7`, tree
`febb48196250768cb01e66c51b9f499b17e3f0a7`: all 2,808 files and 308 directories.
The product's original 45 CI jobs and independent 28-check artifact review
passed before this preparation. No product source, test or tool changed for
the new measurement.

The fresh profile changes only the timeout and maximum tool steps. Its fixed
allowance is 3,000 subject seconds, 40 individual tool calls and 160,000
observed tokens, one attempt and zero retries. Observed tokens are not a hard
server billing cap. Each model call receives the existing remaining subject
time. The outer watchdog is 3,020 seconds with at most five-second TERM and
KILL waits. A local evaluator may run once with a 30-second execution deadline
and at most five seconds for KILL/reap, only after subject completion and full
original receipt validation. A completed E2E additionally requires an actual
submission, evaluator rc0, finite score fields and `validity_score == 1`.
No minimum quality threshold is introduced.

Only unchanged `instruction.md` and `data/instance.json` are initially projected
to the subject. All eleven copied-case files and the original benchmark remain
unchanged. No WebAgent, remote/company evaluator or native RSI campaign is
included.

## Preparation evidence

The prelaunch registration commit
`0c87fac9b341c736cdfdad3b2b84306bbaf11a3a` was pushed before execution.
The private, create-only manifest is 5,105 bytes with SHA256
`ab471ba658db3aa8771336e1fc04bf727ab3b6543959a30a87aa8ceddde75260`.
Independent static review passed 46 checks; its report SHA256 is
`bf652c2493c9a265a02d6de802ef329425a4f1fa32e0ba1c901f2210136516cb`.
The reviewed bounded supervisor is unchanged from the earlier attempt.

Evidence is retained under the primary workspace:

```text
.lunar-evolution/validation/ordinary-model-acceptance-20261102/
  long-run-5c62ca27-7773cy38/
```

The launcher retains actual UTC boundary observations, bounded redacted
captures, original usage/failure/history evidence, before/after source/case/
profile checks and loaded-module origins. Configuration is loaded privately
only at the actual launch. The new endpoint fingerprint cannot reconstruct
either historical endpoint; no key digest is recorded.

## Actual result and independent audit

| Observation | Original result |
| --- | --- |
| Subject process | rc2, 3,001.085719 seconds; original child reaped and pipe EOF verified |
| Outer watchdog | No timeout reason, no TERM/KILL signal attempts |
| Completed interactions | Four model responses, eight tool results; batches 2/2/1/3 |
| Failed request | Fifth model request; schema7 `stage=model`, `code=timeout`, `transport_timeout` |
| Local transport observation | `open_response` timed out after 2,935.404 seconds; last milestone `wait_response_headers` |
| Retained history | Fourteen messages, complete strict pairs, zero pending results, no prefix compaction |
| Accepted usage | Partial: 7,999 input + 4,359 output = 12,358 tokens, four responses; cost unknown |
| Completed receipt / selected submission | Neither produced |
| Local evaluation | Skipped as `evaluation_skipped_not_completed`; scores null |
| Evidence integrity | 48/48 independent checks passed; acceptance=false, actual status=failed |

The failed request's actual serialized body is 11,837 bytes with SHA256
`5e440461a891fdf2898003332f0e80e10e95c6070611139c8c3a8e555dfebc33`.
No request body was retained. This fingerprint identifies bytes, not the cause
of delay. The last local milestone was observed 179 ms into HTTP exchange 1;
it is not a measurement of server queue/inference time or proof of cancellation.
The failed request's usage and billing remain unknown.

The independent audit executed once after the original launcher terminated,
using the previously reviewed v2 script. It read no configuration and ran no
subject, model, evaluator or product tests. It verified the full Git/archive
source and modes, 2,808 files/308 directories, eleven copied case files, exact
two public files, profile/request bindings, 239 loaded Lunar module origins,
launch UTC order, single attempt with zero retries, original bounded capture
and secret-scan geometry, and original evidence before/after audit. Root then
verified the report hash and checked the actual failed classification.

The create-only `independent-original-result-audit-v2.json` is 12,724 bytes:

```text
5202e0b66e8e2725c13892846a83f7d87ecc98317f23c961d1f16f30d5bccc41
```

Its 48 evidence checks passing does not mean the model task passed. The
original `summary.json` remains failed, with `completed_e2e=false`,
`receipt_validator_passed=false`, `evaluator_invoked=false` and null scores.

## Public contract correction

The unchanged public instruction does not specify a fixed answer filename or
JSON fields. The normal prompt permits an answer file identified through
`_agent_summary.md` for an extractor; this helper instead selects fixed
schedule filenames and calls the evaluator directly. This interface mismatch
cannot explain the model transport stall. It does mean that a missing fixed
filename alone is insufficient evidence of no semantic answer.

A separate [public-contract variant](../specs/061-subject-failure-diagnostics/ordinary-direct-evaluation-contract.md)
preserves the original instruction and publishes only the required filename,
matrix fields/dimensions and minutes. Its existing-entrypoint interface passed
one four-case provider-free check: one intact fake call and three pre-call
rejections, zero real requests/tools/evaluations. That preview did not alter
this attempt or the benchmark and has not undergone real model acceptance.

## Interpretation

The two historical 600-second/12-step attempts remain failures. This new
3,000-second/40-step result has its own denominator and cannot repair their
response-header stalls, establish a matched-budget result or imply WebAgent
parity. The new larger-budget attempt also failed, and ordinary-model E2E
remains open. Neither the server-side cause nor a causal client defect has
been established. Do not resume this attempt or automatically retry it.

This is a trusted local smoke. Source readbacks and origin checks do not prove
immutable consumption, OS confinement, private-evaluator inaccessibility,
server cancellation, complete foreign-process cleanup or billing completeness.
Native RSI runtime, production admission and online publication remain false.
