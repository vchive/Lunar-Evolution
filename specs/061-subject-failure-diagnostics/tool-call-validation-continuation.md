# Continuation: reject ambiguous tool-call batches

Status: specified before implementation; implemented and locally verified,
2026-10-26. Final branch CI and merge remain pending.

The final `3799f509` source passed the combined 49-file, 1,600-node local
regression with zero failures, errors or skips, including all 43 tool-call
validation cases. This does not close the separate Linux mixed timeout or the
historical model case failure. Raw JUnit and source inventory remain under the
primary workspace's ignored `release-closeout-20261025/provider-final-union-5jroxt52/`.

## Problem and boundary

The ordinary OpenAI-compatible parser accepts duplicate tool-call IDs in one
response, including a collision between a generated fallback ID and an explicit
ID. AgentLoop then executes that batch and sends two tool results with the same
ID in the next request. The parser also accepts an empty function name. These
are locally reproducible protocol-validation defects. There is no evidence that
they caused the fourth-request header timeout in the frozen ordinary-model
attempt of 2026-10-25; its missing conversation cannot be reconstructed.

This continuation intentionally changes acceptance for these malformed provider
responses. The prior success test for an empty name must become a typed-failure
test. It does not claim that all historical response acceptance is unchanged.

## Contract

1. Parse the entire response batch before AgentLoop can execute any tool.
   Reject a repeated final tool-call ID with the existing `ModelRequestFailure`
   reason `invalid_tool_calls` and the already observed response status.
2. Retain the existing positional fallback `call-<index + 1>` for a missing,
   empty or non-string ID. Check uniqueness after this fallback is applied,
   against both earlier explicit and generated IDs. Do not silently rename
   a collision, discard a call or execute a valid prefix.
3. Reject an exactly empty `function.name` string through the same typed failure.
   Preserve the existing string-type check. Do not strip names, reject nonempty
   whitespace names, add a name regex, or change nonempty unknown-tool recovery.
   Determine emptiness with `str.__len__` after that string-type check. Direct
   helper callers may supply a `str` subclass: do not dispatch its custom
   `__bool__` or `__len__`, and preserve the original nonempty name object in
   `ToolCall.name`. A subclass cannot hide nonempty characters or make an empty
   name pass by overriding truthiness. This is another direct-helper boundary;
   standard JSON wire parsing produces ordinary strings.
4. Compare IDs exactly and only within the current response batch. Preserve
   valid explicit IDs, fallback numbering, argument parsing/defaults, tool-call
   ordering, response text/model/usage, request construction and all budgets.
   For direct private-helper callers supplying a `str` subclass, use a plain
   string only as the internal set key: exact strings remain unchanged and
   subclasses use `str.__str__` directly. Do not invoke the subclass's custom
   `__str__`, `__hash__` or `__eq__` for deduplication, and preserve the original
   accepted ID object in `ToolCall.id`. Standard JSON wire parsing does not
   produce these subclass objects; this protects the existing direct-helper
   compatibility boundary from a new callback path.
5. Keep failure messages fixed and free of response IDs, names or arguments.
   Reuse existing failure timing/diagnostic handling. No success receipt,
   automatic retry or follow-up request is authorized by an invalid batch.

## Focused verification

Use synthetic in-memory HTTP responses and existing loopback fixtures only.
Cover explicit duplicates, both fallback-collision orders, all existing fallback
shapes, exactly empty and invalid-type names, preservation of nonempty whitespace
and unknown names, exact ID comparison, and reuse of IDs across independent
responses. Through the real parser and AgentLoop, prove a valid first tool is
not executed when a later call in its batch is invalid; the model is called once
and the diagnostic retains `invalid_tool_calls`, HTTP 200 and validation phase
without response secrets. Preserve valid request/tool pairing in the next turn.
Direct-helper tests additionally cover unique and duplicate subclass IDs,
both ordinary-string/subclass duplicate orders and fallback collisions, with
foreign hash/equality/string-conversion traps that must never run. Check original
ID object retention and unchanged empty-subclass fallback.
For name subclasses, test custom boolean and length traps with nonempty,
whitespace-only and empty text. Preserve nonempty original objects and reject
intrinsically empty names through the existing typed error without callbacks.

Run the new focused tests and related runtime, loop, failure, timing, transport
and subject-history tests, then Ruff, compileall and `git diff --check`. Retain
raw commands, outputs, return codes, JUnit and source-file hashes in a fresh
ignored validation directory. No real model, evaluator, benchmark, controller
or mixed-runtime run is part of this slice.

## Initial local result

The new focused file passed 30 tests. The related union passed 366 tests,
including those 30, with zero failures, errors or skips. Ruff, compileall and
`git diff --check` passed. Product and test file hashes were unchanged during
the union. Raw commands, outputs, return codes and JUnit are retained under
`.lunar-evolution/validation/release-closeout-20261025/tool-call-batch-union-jo1llyvw/`
in the primary workspace. The first focused run also retained unrelated
existing global pytest temporary-directory cleanup warnings; the union used
its own fresh `--basetemp` and did not touch those existing directories.

These are local synthetic/loopback results. They do not diagnose the historical
header timeout, complete a model E2E acceptance or change frozen mixed-runtime
failures. This result paragraph was added after tests without changing product
or test bytes.

Independent review then found the direct-helper subclass callback path above.
The initial 30/366 results predate that follow-up; its changed product/test bytes
were subsequently verified by a fresh 37-test focused run and 373-test related
union, with zero failures, errors or skips. The union includes all 37 focused
tests. Ruff, compileall and `git diff --check` returned zero on those final
product/test bytes. The retained evidence directory is
`.lunar-evolution/validation/release-closeout-20261025/tool-call-subclass-verified-o9schk36/`.
The preceding iteration passed tests but failed Ruff because it did not infer
`pytest.fail` as a non-returning hash/string trap; the final tests use explicit
`raise AssertionError`. Both raw results remain retained. This final result
paragraph was added after verification; product and test bytes stayed equal.

A later direct-helper check also reproduced custom name truthiness callbacks:
nonempty names could be rejected, a foreign exception could escape, and an
empty name could be accepted. The `str.__len__` follow-up requires fresh local
verification; the resulting 43-test focused run and 379-test related union both
passed with zero failures, errors or skips. The union includes all 43 focused
tests. Ruff, compileall and `git diff --check` also returned zero. Product/test
bytes stayed equal throughout verification; only this result paragraph followed.
Raw commands, outputs, return codes, source hashes and JUnit are retained in
`.lunar-evolution/validation/release-closeout-20261025/tool-call-name-verified-8hmfoaqy/`.
This does not change the unavailable historical timeout evidence.
