# Ordinary-model long-run acceptance — 2026-11-02

Status: the single attempt failed; original evidence independently audited.
It ran on 2026-11-02 from 02:13:07 to 03:03:09 Beijing time. Conditions were
specified before preparation or inference.
This is a new ordinary-model
functional acceptance, using the user's previously authorized 40–50 minute
execution allowance. It does not reopen either historical 600-second attempt.

## Reason and scope

The ordinary train-delay E2E remains incomplete. The 2026-10-25 and 2026-11-01
attempts failed while waiting for model response headers. The latter completed
eight model turns and eleven tool calls, retained 34,627 partial tokens, and
produced neither a submission nor a completed receipt. Its local evaluator was
correctly skipped. No causal client defect has been established.

PR209 is merged as `5c62ca270d78c605ca189399c8b8caadcd11e1b7`, tree
`febb48196250768cb01e66c51b9f499b17e3f0a7`. Its 45 original CI jobs succeeded;
independent original-artifact review passed 28 checks. Each Python version
retained 27,960 pass and the same 134 skip, including all 121 new tests passing.
This product records bounded fingerprints for future failed HTTP request
bodies. That diagnostic change is not a timeout fix.

The existing `effect-subject` CLI already supports the new limits. Its profile
and command-line limits are combined by taking their minimum, so a fresh
profile must be frozen as well. No runtime feature or provider protocol change
is required. This continuation changes measurement conditions before launch;
it does not describe an isolated budget experiment, matched-budget comparison,
or repair of either historical result.

## Fresh fixed conditions

| Condition | Registered value |
| --- | --- |
| Product | Complete frozen source of main `5c62ca270d78c605ca189399c8b8caadcd11e1b7` |
| Case and model | Same eleven-file copied train-delay case and previous model identity |
| Public subject input | Unchanged `instruction.md` and `data/instance.json` only |
| Mode | Ordinary, fresh session history, existing command-tool policy |
| Attempts / retries | One new attempt, zero retries |
| Subject wall limit | 3,000 seconds (50 minutes) |
| Tool-call ceiling | 40 individual calls, not model turns |
| Observed-token stop threshold | 160,000; not a provider-side billing cap |
| Outer subject watchdog | 3,020 seconds, then at most 5-second TERM and KILL waits |
| Conditional local evaluator | One invocation, 30-second execution deadline plus at most 5-second KILL/reap |

The profile changes only its timeout and maximum tool steps. Other model,
provider, sampling, usage and cost fields retain their original values. Each
model call uses the existing positive remaining subject timeout; there is no
new per-request limit, retry, fallback, streaming mode or cancellation claim.
One slow response can consume the full remaining allowance. Unknown consumption
and cost stay unknown. Never extend these limits after dispatch.

## Preparation and dispatch

1. Create a new private, absent-before-creation attempt root and identities.
   Preserve all old roots, manifests, helper bytes and failed results unchanged.
2. Freeze all 2,808 product files and 308 directories from the exact Git tree,
   including modes and blobs, and pin the interpreter, fresh helpers, profile
   and all eleven copied-case files. Do not execute the mutable documentation
   checkout. Do not modify the original benchmark.
3. Independently review the exact manifest and helpers before launch. Reuse the
   already reviewed bounded supervisor. Any necessary offline harness check
   must have a fresh root and must not load credentials, invoke inference or
   run a score evaluator.
4. At the single launch, load the owner's existing private configuration using
   the existing bounded `.env` loader. Refuse a missing or changed model before
   inference. Keep endpoint/key out of argv and retained output. A private
   one-way endpoint fingerprint may identify this new launch; it cannot recover
   the historical endpoint. Never record a key digest.
5. Preserve bounded, explicitly redacted stream captures; original session
   history and failure/usage diagnostics; actual UTC launch/end observations;
   process timeout, exit, pipe and reaping facts; source/case before-and-after
   inventories; and actual loaded Lunar module origins. Do not rewrite receipts
   or histories. A leak or incomplete credential scan blocks publication.

## Completion and scoring

The original `EffectTrialRunner._subject_receipt` normal-mode validator must
accept the original completed subject receipt after subject rc0 without an
outer timeout. Only then select the first regular, nonsymlink submission in
the fixed order `schedule.json`, `output/schedule.json`, independently of score,
and invoke the unchanged copied local evaluator once. No answer repair,
substitute schedule or score-based file selection is allowed.

A completed long-run E2E needs subject completion, a valid original receipt,
an actual selected submission, local evaluator rc0 and finite numeric
`validity_score`, `quality_score`, `overall_score`, with `validity_score == 1`.
An evaluator can report an invalid answer and still exit zero. Report quality
separately; no minimum quality threshold is introduced. Otherwise retain
`evaluation_skipped_not_completed`, or the actual
conditional-evaluation failure, with this attempt's distinct denominator.

Report the new long-run outcome independently from both 600-second failures.
Even a completed long-run result does not establish the 600-second reference
result, repair its response-header stall, or establish WebAgent parity.

This remains a trusted local ordinary smoke. Source readbacks and module-origin
checks do not prove immutable consumption, OS confinement, private-evaluator
inaccessibility, server cancellation, complete foreign-process cleanup or
complete billing. No WebAgent, remote/company evaluator, native RSI campaign,
namespace-holder mechanism or production/publication authority is introduced.

## Tasks

- [x] Specify the separate long-run conditions before preparing or dispatching.
- [x] Freeze the fresh product, inputs, profile, interpreter and helper manifest.
- [x] Complete independent exact-byte review; reuse the unchanged reviewed supervisor.
- [x] Dispatch the single new attempt after the reviewed manifest and pushed registration.
- [x] Audit original evidence and report this long-run result separately.

## Frozen preparation

Private evidence root, relative to the primary workspace:

```text
.lunar-evolution/validation/ordinary-model-acceptance-20261102/
  long-run-5c62ca27-7773cy38/
```

The create-only `one-shot-manifest-v1.json` is 5,105 bytes, SHA256
`ab471ba658db3aa8771336e1fc04bf727ab3b6543959a30a87aa8ceddde75260`.
It pins all product files/directories, eleven case files, the interpreter,
new profile and exact helpers. The supervisor is byte-identical to the prior
reviewed helper; its previous offline checks are retained rather than rerun.
The new helpers have been statically parsed without executing them.

Independent static review passed 46 checks. Its create-only report is 4,740
bytes, SHA256 `bf652c2493c9a265a02d6de802ef329425a4f1fa32e0ba1c901f2210136516cb`.
No helper, model, evaluator, credential loader or product test was run during
preparation or review. No authorization, launch marker or attempt directory
existed at that review. The fresh launcher also verifies the current raw
profile against its frozen pin before conditional scoring and at final
completion, in addition to the original canonical receipt/profile validator.

These preparation results authorize no success claim. Original postrun facts
must be reported separately after the single actual dispatch.

The registration was committed and pushed as
`0c87fac9b341c736cdfdad3b2b84306bbaf11a3a` before the root execution gate and
one-shot authorization were created. The launch observation is
`2026-11-01T18:13:07.414622+00:00` (2026-11-02 Beijing time).
See the [separate run record](../../docs/ordinary-model-long-run-acceptance-20261102.md).

## Observed result

The subject returned rc2 in 3,001.085719 seconds, without an outer-watchdog
timeout or signal. Four successful model responses and eight completed tool
results preceded a fifth model request whose `open_response` phase timed out
after 2,935.404 seconds. The last local transport milestone was
`wait_response_headers`; this does not establish the server's execution state
or cancellation. The retained history has complete tool-result pairs and no
pending result. No completed receipt or fixed submission was produced, so the
local evaluator was not invoked and scores remain null.

Accepted usage is partial: 7,999 input, 4,359 output and 12,358 total tokens
over four responses. Failed-request consumption and cost remain unknown.
Schema 7 records the failed serialized body as 11,837 bytes and its SHA256,
without retaining the body. More time did not complete this attempt; the
observations establish neither a client defect nor the server-side cause.

The original child was reaped and pipe EOF verified; complete process-group
cleanup remains unproven. All 2,808 files/308 directories, eleven copied case
files, raw and normalized profile bindings and 239 loaded module origins
matched. Independent terminal audit passed all 48 evidence checks, while
deriving `acceptance_passed=false` and `actual_attempt_status=failed`. Its
12,724-byte report SHA256 is
`5202e0b66e8e2725c13892846a83f7d87ecc98317f23c961d1f16f30d5bccc41`.

The [public direct-evaluation contract gap](ordinary-direct-evaluation-contract.md)
was identified separately and the active attempt was not changed. Its new
four-case offline interface check does not replace this failed real attempt.
Ordinary-model E2E remains open; production/publication authority remains false.
