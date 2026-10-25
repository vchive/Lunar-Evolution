# Continuation: accepted usage on a later model-request failure

Status: narrow P0 implementation contract, 2026-10-25. The ordinary model smoke
retained three completed model turns and four tool results, then a fourth
request timed out. The old evidence cannot recover the three known usage
samples because they were never persisted; it must remain unchanged.

## Contract

Preserve the existing private per-run UsageLedger and request, step, deadline,
retry, scheduling and session-history behavior. Do not pass a new shared ledger
or change require_complete. Extend the existing InvocationDiagnostics with an
optional accepted_usage using the existing immutable UsageSnapshot, default
None. Reset it per invocation and update it from the current owned ledger
snapshot after accepted response accounting. An interrupted request must never
be added as zero or as an invented response.

On a later model-stage failure only, the subject may wrap its otherwise valid
v1, v3, v4 or v5 failure diagnostic as v6 with exactly two additional fields:

- accepted_usage: the existing input_tokens/output_tokens/total_tokens,
  nullable cost_micros and rounds snapshot; rounds must be positive and equal
  the already recorded successful model-turn count.
- usage_completeness: the fixed string partial. These counters cover accepted
  successful responses only. Consumption of the failed request remains
  unknown; they are neither the complete run total nor a billing receipt.

Do not mix the v2 budget branch into v6. Keep old v1-v5 fixed field sets,
normal/deep request identity, sidecar paths, maximum 4096 bytes, safe publication
and collector validation unchanged. Unknown prices remain cost_micros=null.
No profile-owned valid snapshot, zero completed responses, malformed/oversized
snapshot or a non-model failure must fall back to the existing diagnostic;
a failure in optional accounting/publication must not mask the original error.
Success receipts and unprofiled runtime behavior remain unchanged.

The v6 reader first identifies an exact supported legacy field set, validates
it with the existing normalizer, then checks the two fixed accounting fields.
No provider text, model/tool contents, credentials, endpoints, paths, new score
or production authority is retained. This change does not create session or
tool-transcript storage and does not replay a model request.

## Focused verification

Use local fake runtimes only. Check three accepted responses/four tool results
followed by timeout, exact known subtotal with unknown failed-request usage,
nullable and priced cost behavior, correct successful-response count, no retry,
per-invocation reset, legacy first-failure/unprofiled/success compatibility,
strict malformed v6 refusal, no v2 mixing and safe diagnostic failure fallback.
Check normal and deep collection preserve a valid v6 under the same identity
checks and reject malformed/stale variants. Search schema-version consumers;
run related focused tests, ruff, compileall and git diff --check. Do not call a
real model/evaluator, rerun frozen cases or amend old smoke artifacts.

## Verification on 2026-10-25

405 focused tests passed in 6.14 seconds across the accepted-usage, agent-loop,
subject diagnostic/adapter, staged runtime/adapter, normal/deep collection,
model-failure, transport-diagnostic and transport IPC suites. These use local
fake runtimes and loopback transport fixtures only. Added failure tests cover
both staged master/build aggregation and the cooperative checkpoint/resume
path, plus optional snapshot-capture and publication failure fallback.

Ruff and compileall passed for the three changed source modules and the two
new test modules; git diff --check passed. No real model request, frozen case
rerun, original smoke artifact change or success-receipt schema change was
part of this continuation. The old smoke's missing usage remains unrecoverable.
