# Fixed observations of rejected tool-argument JSON

Status: implementation, focused/static/final-source CI and original-evidence review
complete (2026-11-04). Integration identity is checked separately. Starting from main
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
- [x] Runtime: owned observation, decode-boundary capture and selected-branch finish.
- [x] Logging: exact-type bounded revalidation and optional fixed projection.
- [x] Dedicated fixture suites: direct/bounded HTTP, Unicode/EOF/syntax positions,
  exact ValueError/real isolated recursion, selected versus fallback branches,
  all finish categories, default silence, unchanged early length refusal, later
  invalid calls rejected before tools/usage, and the other five parser failures.
- [x] Adversarial suites: subclasses, spoofed document/positions, bool/negative/
  oversized/inconsistent numeric groups, mutated observation/enum values,
  foreign mappings, hostile properties, legacy failures/callers and privacy.
- [x] Run one combined focused batch, Ruff, compileall and diff check, then
  independent review and final-source CI. Preserve original failure evidence.
- [x] Push, create PR and prepare verified integration using existing authorization.

Do not change existing acceptance assertions to fit the implementation. Review
source pins without broadening fixed build inputs. Ordinary-model scored E2E P0
and native RSI P1 remain open; production_admission=false and
online_publication=false.


## Implementation and validation record

runtime.py captures the owned frozen observation at the original decode rejection;
model_request_logging.py independently validates fixed enum identities, plain
storage and numeric invariants. Only the actually selected choice message may
supply a normalized finish reason. Original failure/cause and all acceptance
conditions remain unchanged. No fixed producer/build source pin inputs changed.

The original 14-file batch at d556994e52150345fde015b4686ac59dc44a608c had
619 cases: 618 passed and one new fixture failed inserting its hostile key before
terminal projection. Preserve that failed original. Reconstructing the same
hostile key in a fresh dictionary corrected only the fixture; its complete
64-case safety file passed at 06f3368be69678f6335eca10bc569002758fd635 in
1.242805375251919 seconds, zero failures/errors/skips/retries. Product bytes were
identical. The 49 integration additions passed in the first batch and all 64
safety additions in the supplement; do not describe the first batch as 619 pass.
All 240/235 actually loaded package modules matched frozen Git. Ruff, compileall
and diff checks passed; 1,294 temporary compilation cache entries were removed.
Independent local review e971198332d675b25f933c6ade6ff713ff251569224f50833197332821c7a3b5
passed with no findings.

Original CI41766909351/attempt1 completed all 45 jobs successfully at head
06f3368be69678f6335eca10bc569002758fd635, tested merge
840ad5ce27948295321c477548325dd3a2beeb15, tree
7f4984eecc4bbeb0b6f5d0a4e4f46f3b25da8377 and base
faa30e0b5e49a10970466f6d72a4c5ec81a8cb36. Python3.11.17/3.12.15/3.13.17
each executed 28,668 current cases: 28,534 pass plus the exact original 134 skips.
All 113 additions and PR223's prior 52 additions passed; no old node was removed.
Historical 2,294+24 cases passed without skips/retries; all 83 focused groups,
including 65 zero-skip gates, passed from original reports.

The 45 original ZIPs total 21,964,421 bytes and were not extracted. Root audit
SHA256: d1e5b10c5d9fd77169e67d7c8aad4201b481760ca8033f73482dcf4d482252d9.
Independent original review SHA256:
580a7aeb167c38def663cfd08dd882e053ec04be4c87fc4f5c88862aecf1e14f.
Its wrapper's UTC precheck failed before starting the checker; that failure is
retained separately. The unchanged reviewed checker executed only once, passed,
and performed no tests, network, product import or extraction. CI import samples
are not a complete CI loaded-module inventory. Originals remain in primary ignored
validation/tool-argument-decode-20261104/.

This four-Markdown closure reuses the verified software only after exact source,
test, tool, workflow and pin equivalence is confirmed. The closure tree differs
from the tested documentation tree; actual PR224/main parents/tree are checked
separately in the integration original. There is no new model invocation or
scoring. The next independent same-case/model/profile attempt has a read-only
preparation plan and capture-path check, with no new manifest/launch/result yet.
Ordinary-model scored E2E P0 and native RSI P1 remain open; production/publication
remain false. Old failures and source/ZIP evidence remain unchanged.
