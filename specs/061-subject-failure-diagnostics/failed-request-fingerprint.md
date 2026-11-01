# Failed model request body fingerprint

Status: specified before implementation; implemented and locally verified,
2026-11-01. Final-source CI/integration is pending.

## Problem and scope

The fresh ordinary-model attempt on main e19be0d1 failed while waiting for the
ninth request's response headers. The retained history has eight accepted
assistant turns and eleven paired tool results, but cannot reproduce the exact
HTTP request: AgentLoop adds dynamic budget text to request copies. Existing
`request_sha256` identifies the subject protocol request, not the HTTP body.
No local cause of the timeout has been established.

Add a bounded, score-free fingerprint of the serialized model request body to
future failure diagnostics. This is an investigation aid, not a timeout repair,
provider receipt or proof of remote processing. Do not change requests, model
parameters, timeouts, retry counts, success receipts, scoring or resume behavior.
Do not add a new CLI or run a real model/evaluator for this change.

## Contract

1. Runtime attaches an optional frozen `ModelRequestFingerprint` to the same
   concrete `ModelRequestFailure` it already raises. Fields are `body_bytes`
   and lowercase hex `body_sha256`, computed from the exact serialized bytes
   supplied as `Request.data`; do not reserialize transcript/messages. It
   describes the initial local request body, not HTTP framing, redirects,
   remote consumption or immutable source custody.
2. Compute it on the existing failure path, preserving successful behavior,
   the original exception/cause, one HTTP exchange and timeout forwarding.
   Fingerprint computation failure must leave the original failure intact.
   Retain no body, endpoint, headers, credentials or model text in this object.
3. Diagnostic schema7 wraps an otherwise valid model-failure schema3/4/5 or
   schema6 partial-usage projection with exactly one `request_fingerprint`:
   `{"body_bytes": integer, "body_sha256": "64 lowercase hex characters"}`.
   Every schema7 projection requires a validated `model_failure`; legacy
   schema6 without that evidence stays readable as schema6, without upgrading.
   Bytes must be between 1 and the existing 64MiB request bound, excluding
   booleans. Unknown keys, wrong types, unsafe digests, scores, budget-failure
   mixing and non-model classifications are rejected. The existing 4096-byte
   file bound remains unchanged.
4. Bind this projection only to the same accepted concrete model-failure node
   in the existing bounded cause traversal. Invalid or absent fingerprints
   retain existing schema1–6 behavior. Invalid optional timing/transport detail
   must not suppress a valid fingerprint or the original fixed failure reason.
5. Preserve accepted-response partial usage when present; failed-request
   consumption remains unknown. Schema7 normal/deep collectors reuse the
   existing request identity and safe file checks. A failed subject never gains
   a success receipt, score, promotion or harness invocation.
6. Existing schema1–6 data remains accepted without migration or backfilling.
   In particular, never invent a fingerprint for either retained real attempt.

## Verification

Use local deterministic fakes only. Check failure fingerprints against the
actual `Request.data` for bounded transport and direct seams, including Unicode,
tools, changing messages, transport/HTTP/response validation failures, missing
or invalid clocks, optional-projection failure and manually constructed errors.
Assert one request, identical timeout, original exceptions and no sensitive text
in the diagnostic projection. Strictly exercise schema7 mutations and normal/
deep collection with and without partial usage, preserving failed-subject score
boundaries. Run the combined affected-file regression once after parallel work,
then Ruff, compileall and diff checks; expand only for an actual failure or
newly identified concern. Update the existing CI inventory if required, keeping
observed local counts distinct from predicted final CI counts.

## Tasks

- [x] Inspect current code and original evidence; specify this bounded gap.
- [x] Add runtime-owned optional failure fingerprint and deterministic tests.
- [x] Add strict schema7 projection with legacy/partial-usage compatibility.
- [x] Verify normal/deep failure collection and non-authority boundaries.
- [x] Review and run one combined regression; update current release status.
- [ ] Push, review and integrate with the repository's final-source gates.

Ordinary-model E2E P0 and native RSI P1 remain open throughout this change.
The previously rejected namespace-holder mechanism is outside this scope.

## Local validation

One fourteen-complete-file Python3.13 batch produced 659 passes and three failed
new-test assertions. Those three failures were test assumptions about existing
protocols: a nested timeout preserves the pre-existing schema1 classification
of that synthetic budget cause chain, and failed deep records omit
`cost_micros`. Product code did not change after that run. The corrected tests
preserve those behaviors; one six-node supplement passed with no failure or
skip. The other passing nodes were not rerun. Both original JUnit reports are
retained under primary ignored
`validation/failed-request-fingerprint-20261101/` as `local-focused.xml` and
`local-supplemental.xml`; the first batch remains a failed batch.

The final added inventory is 121 test identities: 27 runtime and 94 diagnostic/
collection cases. Existing actual-runtime assertions expect the new schema7
wrapper while retaining their original failure, timing, transport and safety
checks. Manual legacy fixtures still assert schemas1–6. Ruff over src/tests/
tools, changed-file compileall and `git diff --check` pass. Existing current CI
discovers both new files automatically; no focused groups, jobs or historical
pins change. The predicted full inventory is 28,094 keys, not an observed CI
result. No real model request or score evaluator ran in this implementation.
