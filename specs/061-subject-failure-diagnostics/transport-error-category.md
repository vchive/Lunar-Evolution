# Fixed transport error categories

## Scope and contract (2026-11-02)

The two capped case attempts stopped while waiting for response headers with the
existing `transport_error` reason. The original exception subtype was discarded
by worker IPC. This slice retains a small local diagnostic category; it does not
identify the responsible remote component or repair historical failures.

- Add a concrete `TransportErrorCategory` enum with fixed values `peer_closed`,
  `connection_reset`, `connection_refused`, `connection_aborted`, `broken_pipe`,
  `dns_error`, `tls_error`, `timeout`, and `os_error`.
- A shared best-effort classifier walks at most eight distinct exceptions through
  concrete `URLError.reason` exceptions or `__cause__`, with cycle protection.
  Check `RemoteDisconnected` before its reset superclass; match stdlib timeout,
  socket DNS and SSL types, never exception prose, arbitrary provider fields,
  errno messages, class-name strings, or `__context__`. Defer generic OSError
  fallback until the walk ends; URLError alone is not a generic OS category.
  HTTPError and unrecognized exceptions produce no category. Failed inspection
  cannot change the existing outcome.
- Append an optional keyword-only `transport_error_category` to
  `TransportFailure`, and a default-None attribute to `ModelRequestFailure`.
  Propagate only a concrete valid enum from worker to runtime; classify the
  direct path with the same helper within its existing exception catch set.
- Worker terminal IPC accepts exactly the old field set, or that set plus
  `transport_error_category` as a fixed enum string. An included null, unknown,
  non-string, extra or duplicate field is invalid. Categories are permitted only
  on transport failures, never success or HTTPError. New readers accept legacy
  frames; old strict readers cannot consume enriched frames. Parent and worker
  must use the same frozen source, as in the current launcher.
- Opt-in failed request logs retain schema version 1 with an additive optional
  `transport_error_category` field, emitted only for the exact concrete runtime
  failure/evidence/enum types and existing transport_error/transport_timeout
  reasons. Malformed category metadata omits only that detail. Never log error
  text, endpoint, key, model, prompt or bodies. Default logging stays disabled.
- Keep receipt schemas 1–7, high-level reasons, legacy timeout/cause semantics,
  catch sets, HTTP request bytes, budgets, deadlines, cleanup and zero retries.
  A supervisor-generated deadline has no inferred exception category.

## Validation and new real attempt

Use focused classifier/strict IPC/log privacy tests plus real localhost peer
close, reset and refusal on direct and bounded paths. Run the related existing
transport/runtime/diagnostic/logging files once as a combined focused batch,
then Ruff, compileall and diff checks. Independently review the final source;
its complete CI is required before merge. A new independently frozen DeepSeek
case attempt may run alongside final CI after focused checks and source review.

The configured gateway's authenticated read-only model discovery returned
`deepseek-chat` on 2026-11-02; use that advertised identity for a fresh profile
and child environment only. Do not edit the owner's .env, reuse old attempt IDs,
resume old failures, retry, or silently fall back to another model/protocol.
Preserve the copied public-task contract, 16,384 completion cap, 160,000 observed
token budget, 40 tool calls and 3,000-second subject budget. Register exact source,
helper/profile/case hashes before dispatch. Only a completed original receipt
and valid submission permit the copied local evaluator. All old failures stay
in the denominator. No WebAgent or remote evaluator is involved.

## Implementation status

Implemented in `http_transport.py`, `runtime.py`, and `model_request_logging.py`.
The independent test author reviewed all three source diffs against this contract;
root separately reviewed them. No blocking source issue was found.

One combined 16-file focused batch produced 766 passes and six failures, all in
new fixture expectations: four omitted the pre-existing `/chat/completions`
suffix; two assumed a bound non-listening socket always yields ECONNREFUSED,
where this Darwin host instead observed timeout. Preserve that failed batch.
No product code changed to satisfy those assumptions. Corrected tests explicitly
preserve Darwin timeout versus Linux refusal, add deterministic concrete/wrapped
refusal propagation and compare complete schema7 projections with/without category.
One corrected-file batch passed all 86 cases, zero skips/errors/failures. Product
source hashes were unchanged; other passing files were not rerun. Ruff across
src/tests/tools, compileall and diff checks passed. Original artifacts are in the
primary workspace's ignored `validation/transport-error-category-20261102/local`.

Complete final-source CI and the new real DeepSeek attempts remain pending.
