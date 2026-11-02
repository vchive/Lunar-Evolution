# Capped ordinary-model benchmark case acceptance

Status: both single real attempts failed on transport errors, 2026-11-02.
Original-evidence audits passed; no completed receipt, evaluator or score.

## Scope

Use frozen main `16447a6b632d4806344b2c9ac6435e14542112e0`, whose software
equals the fully regressed PR214 version. Reuse original CI `41403780073`,
attempt 1, all 45 jobs successful; do not repeat software regression for this
measurement-only work.

Run ordinary model/tool sessions on two copied local benchmark cases:

- `train_delay_rescheduling`: the previously published direct-format variant,
  retaining its original instruction, instance and numeric schedule contract.
- `hospital_or_scheduling`: original instruction, business clarification and
  four public CSV inputs, with a separately published CSV submission contract.

Keep every original case file byte-identical. Add only `public-task.md` with
the original instruction and the required submission filename/schema; publish
no algorithm, solution, evaluator or private baseline. Register the resulting
variants and public ledgers separately from unchanged reference cases. The
external benchmark checkout and all historical attempts remain untouched.

## Fixed conditions

Each case gets one fresh attempt, zero retries, the previously configured
model, 3,000 subject seconds, 40 individual tool calls, 160,000 observed-token
stop threshold and explicit `max_completion_tokens=16384`. These are new
profile identities, not changes to an old attempt. At most two cases run
concurrently. The generation cap requires gateway support, includes reasoning
tokens, and is not a hard aggregate billing cap. A capped length finish fails
under the existing runtime contract; do not continue or silently change caps.

Freeze the full Git source archive, actual interpreter, exact helper bytes,
profile, original and variant case inventories, request template and public
ledger before dispatch. Reuse the existing bounded supervisor unchanged:
3,020-second subject watchdog plus at most five seconds each for TERM/KILL;
1 MiB per captured stream. The new child changes only its profile guard to
explicitly require the registered cap. Enable existing session history and
model request logs; logs remain terminal captures, not a new live sink.

An independent agent reviews the exact prepared files before the root writes
the one-shot authorization and launch marker. Push the registration before
launch. Configuration is loaded privately only at actual launch; never print
or retain endpoint/key values in the evidence exported to Git.

Only successful subject completion, original receipt/profile validation and
clean supervisor observations allow scoring. Select the declared filename
before inspecting scores; do not repair, substitute or generate a submission.
Invoke each unchanged copied local evaluator at most once, without provider
credentials, with 30 seconds and at most five seconds for KILL/reap.

Functional E2E requires a valid completed receipt, an actual submission,
evaluator rc0 and finite validity/quality/overall scores with validity exactly
1. Report quality separately; impose no new quality threshold. Record a
missing, invalid, truncated or timed-out result as its actual outcome.

## Evidence and limits

Preserve source/case/profile before-and-after checks, actual loaded module
origins, original history/usage/failure/request events, redacted captures,
UTC/process/reap/EOF observations and evaluator output. Independently review
the original terminal evidence without rerunning inference or scoring.

Report the two cases separately, retaining failed denominators. Success on a
new capped public-format variant does not replace a historical failure or
establish unchanged-benchmark parity, general model reliability or evolution
benefit. This is a trusted local smoke, not OS isolation or proof of private
evaluator inaccessibility. No WebAgent, remote/company evaluator, native RSI
campaign or previously refused isolation mechanism is included.
`production_admission=false` and `online_publication=false` remain unchanged.

## Prepared identities

The fresh ignored batch root is
`.lunar-evolution/validation/capped-benchmark-cases-20261102/` in the primary
workspace. Each child root contains its own complete 2,822-file/308-directory
source copy, archive, case, profile and helpers. Frozen main has tree
`6bef093284d724fafbb4537dd474ddb675d0e2c2`.

| Case | Copied variant / public files | One-shot manifest SHA256 |
| --- | --- | --- |
| `train_delay_rescheduling` | 12 / 3 | `35ebf61c3f1652d5161ce641e72a083f70f39b31961b9b2df686f4c691b1be6a` |
| `hospital_or_scheduling` | 14 / 7 | `738aa9bb71e4c47103342ae89ec196200f83495180a63eb70c6701625593ffb7` |

Common and launcher bytes equal the reviewed earlier helpers. The child has
one changed profile guard; no helper was executed during preparation.
Hospital submission is `surgery_schedule.csv` with
`surgery_id,day,room,start_time`; its public task specifies canonical day,
room identifier and time representations without a schedule or algorithm.

Independent preparation review passed 87 corrected checks. Its first report
(`dbf92b1a8c7ca0c8ef92597d22a645087556abfaac0c59abb934880ccbfef57a`)
retains a mistaken prefix assertion about the already approved train task's
title. The hash-linked correction addendum
`b1e2a2184aaab6a217d436e0f482d1a4fc2aca969a46f3a8d0a7d17830017d01`
confirms title plus verbatim original instruction plus public schema; no
prepared bytes changed. Independent public-contract review passed 331 checks,
SHA256 `bc4fb53986c868883d39ac46f897f953df7aede70281a290a7f39f8f169fe522`.
It retains its initial reader's mistaken lineage assumption separately. The
train source deliberately preserves the earlier copied variant and private
cached bytecode; the hospital source is copied directly from the external
case. Neither issue was a model, evaluator or product-test failure.

## Actual execution

Registration commit `19b40179e11917d75f1d0a8be8faf5830f4a7d86` was pushed
before both launches at `2026-11-02T11:52:58Z`. Each ran once, without retry.
Train ended rc2 in 141.094818 seconds after two accepted model responses/four
tool results; hospital ended rc2 in 140.329087 seconds after three/nine.
Their next requests failed with schema7 `model/model_failed`, reason
`transport_error`, in `open_response`; the last local milestone was
`wait_response_headers`, with no observed response status. Failed requests
took 129.302 and 126.993 seconds, well below their approximately 2,989/2,988
seconds of remaining allowance at dispatch. Neither outer watchdog fired.

Accepted partial usage is 3,558 and 6,145 tokens respectively. Triggering
usage/billing remains unknown. No completed receipt or submission exists;
both evaluators were correctly skipped. Original children were reaped and
pipe EOF verified; all source/case/profile checks matched.

The independently prepared, root-reviewed terminal audit executed once per
case and classified both original results as failed. Its script SHA256 is
`a33329af15d618379054f0c67a81ade1dd06383fd92cb55d0912f142c8a2bede`.
Original report SHA256s are
`91768765654a1409ff862599a0efa8e5a06cb0482d9bea65723c15a5502ac28a`
(train) and
`5b05cc866d50b94eaaa4184b72e6381455ac14933735e74b4d8318de0801e0e8`
(hospital). Audit success validates the failed records, not E2E acceptance.
An independent 48-check original crosscheck passed, report SHA256
`c05a16640eb3a6db04f6ea3d0b56fd262803252f67016b1a27f5f83d1c865610`.
Separate static in-memory reconstruction exactly matched both failed-body
fingerprints, including cap16384 and paired tool history. Its report SHA256 is
`6cc753ce9974e8011a0a37331dd31efe3207ba1ba65f7f6b90001cdcd09509da`.
No body was retained or model request repeated; these matching candidates do
not prove original wire capture, endpoint receipt or gateway enforcement.
See the [actual run record](../../docs/capped-benchmark-case-acceptance-20261102.md).

## Tasks

- [x] Select two cases and specify public format, budgets and acceptance gates.
- [x] Freeze and independently review both new preparations.
- [x] Push the exact registration and launch each attempt once.
- [x] Preserve and independently review terminal evidence and conditional scores.
- [x] Publish actual per-case results and update the current release entry points.
