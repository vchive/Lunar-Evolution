# Explicit per-request completion-token limit

Status: implemented, independently reviewed and verified by final-source complete
CI; merged through PR214 on 2026-11-02. This closeout changes documentation only.

## Problem and scope

The [independent direct-contract attempt](../../docs/ordinary-direct-contract-acceptance-20261102.md)
received nine responses. Its ninth added 65,536 output tokens and raised
observed aggregate usage from 100,651 to 174,152, beyond the fixed 160,000
stop threshold. The existing ledger correctly rejected the response after it
arrived. That attempt sent no completion-token limit.

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
- [x] Implement profile and transport policy with default identity preserved.
- [x] Implement ordinary and isolated profile propagation.
- [x] Independently review implementation and focused tests.
- [x] Execute focused/static checks and final-source complete regression.
- [x] Publish exact results and integrate after gates pass.

MVP boundary remains explicit: local task/loop/population/provider-free RSI
control is a technical MVP. Reliable real-model task completion and measured
algorithm-evolution benefits are not yet independently accepted. Native RSI
P1 is a separate runtime dependency, not a prerequisite for the local CLI MVP.

## Local result

Implementation commit `f1797a5d` passed one batch of thirteen complete related
test files on Python 3.13: 455 tests in 18.148 seconds, including all 47 new
cases, with zero failures/errors/skips. Original JUnit SHA256 is
`18ec0829ca3208edff941439df85c223fcb1bab7d421b677b3e8cf4eabd4e5c2`.
Independent source reviews found no blocker. The tests use synthetic localhost
HTTP or injected runtimes; no real model or evaluator was called.

Initial Ruff found two missing parentheses around implicit test-string
concatenations and one nested context-manager style issue. A test-only style
correction preserves the normalized AST and context-manager acquisition/release
order; product code is unchanged. Corrected Ruff over `src tests tools`,
compileall and `git diff --check` pass. The original focused batch is retained,
not rerun or relabeled as covering a new behavior. Final CI tested the exact
corrected source described below. Evidence is in primary ignored
`.lunar-evolution/validation/completion-token-limit-20261102/`.

## Final CI and integration

PR214 head `1bc380e069016e7b794dc2dfd9871f73706e42b8` completed original run
`41403780073`, attempt 1, with all 45 jobs successful. The actual CI merge was
`c4312610c89a8c06d3e405c0e936f677e717f8d2`, with parents
`44ae4be1de8cc031a3bd1364f158ab24eb0ffe8f` and the PR head. Its tree
`6e0d11c03422cf581ed004d79516e575b67210d8` equals the head tree.

Python 3.11.17, 3.12.15 and 3.13.17 each reported 28,200 current cases:
28,066 pass and the same 134 skips as the preserved PR211 baseline. All 47
new cases passed, with no baseline node removals. History passed 2,294 + 24
cases with zero skips and no retries. All 83 derived focused groups passed,
including 65 zero-skip groups, bound to the original reports and source.

All 45 original ZIPs and audit evidence are preserved under primary ignored
`.lunar-evolution/validation/completion-token-limit-20261102/ci/`:

- Original ZIP audit SHA256:
  `03ef59ce1cc71140372d639bdfea283821cfc918c7794a291be09d78ee1391ee`.
- Independent original evidence review SHA256:
  `5eb4459787c4a3c7beb5a28779e43671ebc1eec5be468b3f71b1a12d9767d122`.
- Root verified-merge receipt SHA256:
  `7db001e8a5f377098f9925228ffdf7d0ba3c6af83baecd021df279cc4bc08ef8`.

PR214 actually merged as main `6adc850a203f6cb35106941ea5469d342eb83392`;
root verification confirmed the same exact tested tree. An initial independent-review report
timestamp serialization failure was preserved; correcting report generation
did not rerun tests or change product code. This documentation-only closeout
reuses the unchanged software regression evidence and adds no model run or
end-to-end acceptance. The historical failures, aggregate-budget boundary and
technical MVP/P0/P1 distinctions above remain unchanged.
