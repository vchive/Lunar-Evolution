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

Initial complete CI for PR217/head `24098669` failed on fixed-profile source
pins as recorded below; corrected final-source CI is still required.
The two real DeepSeek attempts have finished as independent failures: train
exceeded observed-token budget; hospital rejected an HTTP200 tool call. Neither
had a transport error. These outcomes do not identify the historical network
failure or establish E2E success; see the
[actual result record](../../docs/deepseek-benchmark-case-acceptance-20261102.md).

## Fixed-profile integration correction

The first full CI revealed a real integration regression: the fixed OpenEvolve
preparer still pins the previous complete `http_transport.py`, and the Shinka
generator consumes that projection. Its deliberate source-drift gate rejects
the new diagnostic source. Preserve the original failed run `41449062257` and
its per-job evidence; it is not passing final CI.

Update the reviewed exact byte count/SHA256 pins and, where necessary, the
explicit broker source-segment/import dependency projection to include the new
enum/classifier helpers. Keep drift refusal, selected-source exactness, broker
transport policy and native admission/publication gates intact. Never bypass
the pins or admit external/native execution. Review both fixed-profile
generators and run their relevant complete focused files; run Ruff, compileall
and diff checks. This correction requires new final-source CI. Previously
passing transport files need not rerun unless their source changes.

The pending steel ordinary-model smoke uses the already frozen f3257898 source
and does not invoke either fixed-profile producer preparer or generated broker.
The identified pin regression is therefore tracked separately from this local
ordinary receipt/submission/evaluator validation. Retain its exact execution
identity; do not describe it as execution of the later corrected source.

Correction changed only two constants in
`tools/openevolve_fixed_profile/prepare.py`: 32,605 bytes and SHA256
`f6a3b35d1acb5c12fb8185755d812c9cfc6b34ac0f9560c6e753f7ce8318e995`.
Shinka consumes the shared guard. Independent static inspection confirmed only
MAX_REQUEST_BYTES/MAX_RESULT_BYTES are selected from transport, so no new enum
dependency enters the target broker. Generated broker remains 8,143 bytes,
SHA256 `5c0474648bf173f0d24a0fcc12e6d1eedc0d9b4169c3cab4d22def2ed38d43b0`.
One combined six-file fixed-profile batch passed all 241 tests in 2.015019
seconds, zero failure/error/skip/retry. Ruff, compileall and diff checks passed.
Transport product source and its already passing focused files did not change.
