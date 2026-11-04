# Fixed observations of rejected tool-argument JSON

Status: scoped implementation in progress (2026-11-04), starting from main
faa30e0b5e49a10970466f6d72a4c5ec81a8cb36. This is a Feature 061 continuation.

## Problem and boundary

The November 3 ordinary-model attempt ended in arguments_invalid_json without
retaining a decode category, location or selected response finish reason. That
historical failure cannot be reconstructed, repaired, resumed or backfilled.
Observe the next existing rejection using only fixed labels and bounded integers.
No inference, benchmark execution or scoring is required to validate this slice.

Only runtime.py and model_request_logging.py are product scope. Preserve existing
failure reason/category, schema1–8, observer signatures, HTTP bytes, extraction
and first-failure order, parsing acceptance, deadlines, budget, zero retries,
usage order and evaluator gates. Default logging remains silent. No JSON repair,
fallback, extra budget, call index/count or native RSI admission is included.

## Optional log contract

An exact repository-owned frozen ToolArgumentDecodeObservation is stored in
ModelRequestFailure.tool_argument_observation. Only the existing
invalid_tool_calls / arguments_invalid_json refusal may project a nested
tool_argument_decode object in the opt-in model_request_failed event:

- decoder_category: registered ToolArgumentDecoderCategory identities map to
  json_syntax (exact JSONDecodeError), value_error (exact ValueError), or
  recursion_error (exact RecursionError). Unknown subclasses omit this field.
- argument_characters: length of the original exact built-in string passed to
  json.loads, an exact int excluding bool in [0, MAX_BODY_BYTES] (8 MiB).
  This is Unicode characters, not bytes/tokens or a new parser input limit.
- position/line/column: one optional group. Only an exact JSONDecodeError at that
  decode boundary may supply a plain stored pos, with its stored doc identical
  to the original string. Validate pos in [0, argument_characters], then derive
  1-based line/column using built-in string operations. Never trust exception
  lineno/colno. Require exact bounded integers and numeric consistency again
  at the log boundary; a bad group is wholly omitted.
- finish_reason_category: registered ToolArgumentFinishReasonCategory identities
  map to stop, length, tool_calls, function_call, content_filter, null,
  other_string or invalid_type. Normalize exact built-in strings only. A missing
  field omits it. Obtain it only from the actual choices[0].message branch that
  invoked parsing; top-level fallback and unselected choices cannot supply it.
  Existing early explicit-output-limit length refusal still runs first.

Never log raw arguments, document/message, exception prose, function names/IDs,
unknown remote strings, hashes of arguments or request/response content. Do not
follow arbitrary exception chains or invoke hostile getters, str/int/eq,
mapping-subclass callbacks or arbitrary metadata. Inspect bounded plain-key owned
storage and exact types/enum identities at both diagnostic boundaries. Missing,
malformed or unbounded optional data omits the affected detail. Observing a
failure must preserve its object/cause, terminal reason, status, fingerprint and
timing evidence even if optional projection fails.

## Parallel implementation and verification

- [x] Check latest HANDOFF, backlog, actual implementation and clean Git baseline.
- [x] Record the narrow SDD before editing product code.
- [ ] Runtime: owned observation, decode-boundary capture and selected-branch finish.
- [ ] Logging: exact-type bounded revalidation and optional fixed projection.
- [ ] Dedicated fixture suites: direct/bounded HTTP, Unicode/EOF/syntax positions,
  exact ValueError/real isolated recursion, selected versus fallback branches,
  all finish categories, default silence, unchanged early length refusal, later
  invalid calls rejected before tools/usage, and the other five parser failures.
- [ ] Adversarial suites: subclasses, spoofed document/positions, bool/negative/
  oversized/inconsistent numeric groups, mutated observation/enum values,
  foreign mappings, hostile properties, legacy failures/callers and privacy.
- [ ] Run one combined focused batch, Ruff, compileall and diff check, then
  independent review and final-source CI. Preserve original failure evidence.
- [ ] Push, create PR and merge after verified checks using existing authorization.

Do not change existing acceptance assertions to fit the implementation. Review
source pins without broadening fixed build inputs. Ordinary-model scored E2E P0
and native RSI P1 remain open; production_admission=false and
online_publication=false.
