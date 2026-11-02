# Explicit per-request completion-token limit

Status: specified before implementation, 2026-11-02.

## Problem and scope

The [independent direct-contract attempt](../../docs/ordinary-direct-contract-acceptance-20261102.md)
received nine responses. Its ninth added 65,536 output tokens and raised
observed aggregate usage from 100,651 to 174,152, beyond the fixed 160,000
stop threshold. The existing ledger correctly rejected the response after it
arrived. The request currently sends no completion-token limit.

Add an explicitly configured per-request generation limit using the existing
model profile and OpenAI-compatible runtime. This helps bound a single long
completion; it does not establish task completion, fix historical stalls,
estimate prompt tokens, or enforce a hard aggregate/provider billing cap.
Do not alter or retry any existing attempt, budget, case or result.

## Contract

1. `ModelProfile.max_completion_tokens` is optional, default `None`; configured
   values must be integers in 1..1,000,000 (not bool). It is independent of the
   existing aggregate `max_total_tokens` ceiling. When absent or null,
   `to_dict()` omits the new field so existing canonical profile digests remain
   byte-identical. When configured, canonical profile identity includes it.
2. `OpenAICompatibleRuntime.complete` accepts the same optional keyword-only
   argument. Validate it before request budget accounting or network activity.
   Include exactly `max_completion_tokens` when supplied, for both direct and
   bounded transport; omit it by default. Preserve timeout, tools, request log,
   headers, one-request behavior and zero retries. Do not fall back to
   `max_tokens` when a gateway rejects the field.
3. Both ordinary tool sessions and isolated model calls obtain the limit from
   their profile. Existing no-limit injected runtimes retain their unchanged
   call signature. A runtime lacking the new configured capability must fail,
   not silently drop the policy or make an unbounded fallback call.
4. For an explicitly capped response, a selected choice with
   `finish_reason="length"` is unusable. Reject it before extracting/executing
   tools or accepting final text, using a fixed `ModelRequestFailure` with the
   existing `invalid_response_shape` reason and response status. No retry,
   successful receipt or evaluator call follows. Missing finish_reason and
   existing non-choice response forms retain current compatibility; a gateway
   may ignore the field. Existing aggregate observed-usage checks still apply.
5. A truncated response is a failed request: prior accepted usage remains
   available; triggering-request usage is not represented as accepted or as a
   complete bill. Do not log response text, prompts, model/endpoint or secrets.

The [official Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
defines `max_completion_tokens` as visible output plus reasoning tokens.
Endpoint support and model-specific ranges remain the caller's responsibility.
This feature adds no environment variable, automatic `.env` loading, model
migration, endpoint probing, production RSI permission or automatic real run.

## Implementation and validation

- `profiles.py`: bounded optional field, parsing and identity compatibility.
- `runtime.py`: per-call keyword, exact opt-in wire field and capped length
  rejection in the existing fixed diagnostics/logging path.
- `agent_loop.py`: pass profile policy in ordinary and isolated calls only
  when explicitly configured.
- Focused tests: old profile bytes/digest; configured identity and invalid
  inputs; direct/bounded HTTP payload and no retry; capped text/tool truncation
  refusal; ordinary/deep effect-subject failure with no tool effect, receipt or
  evaluator; ordinary/isolated profile propagation; old injected signatures.
- Run the affected complete test files once after parallel edits, plus Ruff,
  compileall and `git diff --check`. Preserve any failed batch and run only
  justified supplements. Then run one final-source complete CI for the code
  change and inspect its actual outcome before main integration.

## Tasks

- [x] Register the evidence-based opt-in contract and compatibility boundary.
- [ ] Implement profile and transport policy with default identity preserved.
- [ ] Implement ordinary and isolated profile propagation.
- [ ] Independently review implementation and focused tests.
- [ ] Execute focused/static checks and final-source complete regression.
- [ ] Publish exact results and integrate after gates pass.

MVP boundary remains explicit: local task/loop/population/provider-free RSI
control is a technical MVP. Reliable real-model task completion and measured
algorithm-evolution benefits are not yet independently accepted. Native RSI
P1 is a separate runtime dependency, not a prerequisite for the local CLI MVP.
