# Follow-up diagnostics from the DeepSeek attempts

Status: implementation complete, focused/final-source validation pending
(2026-11-03). Development starts from main a7db4f99 after PR217/218; the
original attempts and their missing historical values remain unchanged.

## Evidence and goal

The hospital attempt failed on invalid_tool_calls without retaining the specific
parser branch. The extended steel attempt stopped with runtime/input_required;
its schema1 receipt retained8model rounds/12tools but no token subtotal. These
historical values cannot be recovered or inferred from later runs. See the
[hospital record](../../docs/deepseek-benchmark-case-acceptance-20261102.md) and
[extended record](../../docs/deepseek-steel-extended-acceptance-20261102.md).

Read-only inspection found that AgentLoop records each accepted UsageSnapshot
before tool execution, and effect_adapters already passes this snapshot to
emit_failure. Two model-only diagnostic gates currently omit it for input_required.
The parser has six rejection branches that currently share invalid_tool_calls;
usage parsing occurs after tool parsing, so the rejected response usage remains
unknown. Preserve this ordering and every existing acceptance decision.

## Proposed bounded slice

1. Add a narrow new failure schema8 for runtime/input_required, http_status=None.
   Reuse the existing bounded accepted-usage projection only for a repository-owned
   typed snapshot with positive accepted rounds equal to model_turns. Require the
   existing fixed partial-subtotal semantics and nullable validated cost; do not
   infer remote fees or claim completed task usage. Missing, malformed, unprofiled
   or nonpositive snapshots retain schema1 fallback. Keep schemas1–7, their exact
   allowed classifications, v2 budget and v7 failed-request behavior unchanged.
2. At the six existing parser rejection sites add an optional concrete owned enum:
   batch_not_list, call_not_object, function_or_name_invalid, arguments_invalid_json,
   arguments_not_object, duplicate_call_id. Retain invalid_tool_calls as the public
   failure reason. Only opt-in model_request_failed logs may project a fixed label,
   after exact typed validation for that reason. No IDs, function names, arguments,
   response bodies, exception prose, branch indices or arbitrary remote fields.
   Invalid optional metadata omits the detail, preserving the original failure.

These changes do not change HTTP bytes, tool acceptance, extraction order,
deadlines, budget decisions, pause/recovery, zero retries or evaluator gates.
No automatic answer to ask_user, silent argument repair, old-attempt resume,
model fallback or native RSI admission is included. Default logging stays off.
Ordinary benchmark execution-environment declarations belong to a separately
registered public-input contract, not a diagnostic workaround.

## Implementation and verification plan

Expected product files: subject_diagnostics.py, runtime.py,
model_request_logging.py. No AgentLoop, ledger or adapter change is currently
needed; recheck this against the implementation before editing.

Extend accepted-usage/partial-usage collection, runtime tool validation and
request-logging tests. Cover schema8 exact fields/classification/round agreement,
typed snapshot bounds, nullable cost, strict rejection and legacy fallback;
all six parser labels; privacy and malformed optional metadata; default silence;
and unchanged request/tool counts, parser acceptance and legacy receipts.
Use existing model-failure, session and fingerprint suites for compatibility.
Review producer source pins if a selected dependency changes; preserve exact
guards and generated broker behavior. Batch the focused regression once after
the full slice, then Ruff, compileall, diff and final-source CI before merge.
Do not rerun historical inference or scoring to validate these diagnostics.

- [x] Establish actual gaps and inspect existing ownership/data flow read-only.
- [x] Independently review the scoped schema/log contract; recheck final code scope before editing.
- [x] Implement both bounded diagnostics with compatibility/privacy tests.
- [ ] Run the combined focused and final-source checks; review original evidence.

## Implementation scope

Three product files implement the slice: subject_diagnostics.py adds the
independent schema8 projection/validator; runtime.py attaches ToolCallErrorCategory
at the six original rejection sites; model_request_logging.py emits only the
owned fixed label from bounded plain-key instance metadata. Existing parser
conditions and usage/extraction order remain unchanged. A malformed optional
category cannot suppress the terminal reason. Legacy schema1–7 paths are retained.

New coverage is isolated in test_subject_input_required_usage.py and
test_tool_call_error_categories.py; existing test files are unchanged. The
independent downstream/pin audit found that collectors already delegate to the
shared normalizer, while fixed producer generators pin only producer_broker_ipc.py
and http_transport.py. Neither pinned source changes in this slice.

Focused regression is planned as one combined batch including both new files and
the existing usage, collection, runtime, logging, session and receipt compatibility
suites. Artifacts use primary ignored
`.lunar-evolution/validation/model-failure-followups-20261102/` (UTC preparation
date); final CI identities and actual counts will be recorded after execution.
No new inference, benchmark scoring or historical attempt rerun is included.

This is a P0 observability follow-up, not a fix for general model reliability.
The ordinary-model E2E P0 and real native RSI P1 remain open.
production_admission=false and online_publication=false remain unchanged.
