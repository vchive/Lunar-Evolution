# Exact owner mailbox result composition

## Problem

The private owner bridge returns a three-field status summary, while the existing
`deliver_brs_owner_result` parser requires the complete selected request, handoff,
native plan and transaction journal binding. The two implemented primitives cannot
currently compose. PR124's recovery obligation does not fix this response boundary.

## Contract

1. Reuse `build_brs_owner_result_payload(result, request, original_handoff)` in the
   private owner mailbox bridge. Do not introduce a second response protocol, permit
   or result receipt. Preserve the existing bridge result's transaction/payload API.
   This explicitly upgrades this private wire from the former status summary to
   the existing exact-result protocol; no new summary compatibility layer is added.
2. Accept only an already supported kernel terminal with the builder's exact
   journal/selected identity and candidate rules. The actual BRS kernel currently
   refuses `all_rejected`; retain that refusal and its evidence/fence. The builder's
   separate pure-DTO rejection support does not enable a native BRS rejection route.
   Unknown or malformed transactions never produce a successful response.
3. The original owner, mailbox and native preparation gates and durable recovery
   registration still run before service. Capture the original handoff/request
   binding and retain exactly the bytes returned to the selected worker. Do not
   rebuild a response after delivery or adopt mutable latest objects as new capture.
4. Extend existing source/policy fingerprint and canonical globals/alias checks to
   the result builder and its parsing/projection dependencies. Rebinding, source
   drift or substituted globals must fail closed before publication/delivery.
5. On the original worker, the real response must pass `deliver_brs_owner_result`
   using the original request/handoff and expected native plan/journal. The resulting
   gate invokes a detached callback at most once. A callback failure remains unknown
   and cannot be retried.
6. Delivery/settlement here means the existing detached result callback only. It
   does not mark an episode terminal, save a solver result, settle a controller wave,
   prove process cleanup or consume a reconcile obligation. Even a successful
   publication and callback retain the durable recovery fence. Ordinary resume must
   continue to refuse while that fence remains.
7. Public native BRS, production admission and online publication remain closed.
   No real provider, campaign, subprocess evaluator or remote system runs in this
   slice. Automatic terminal recovery and real runtime acceptance remain open.

## Work and validation

The bridge and policy changes are one implementation stream. Real waiting-worker
integration tests and response/callback fault tests are another. Source review,
documentation, CI and frozen macOS/Linux validation are an independent stream.

Cover known publication and the unchanged rejection refusal through the real inert
native kernel; exact response parsing on the original worker; duplicate and
callback-unknown settlement; request/plan/journal drift; canonical-globals/source
drift; and retained fence/no synthetic terminal ledger writes. Existing parser and
mailbox refusal tests remain applicable. Freeze one final source, run disjoint
focused groups with own editable environments on macOS and 5090gpu Linux, and keep
collection/JUnit/import/source/exit evidence. Run Ruff, compileall and diff checks.
The complete GitHub Actions matrix and dependent PR merges remain separate gates.
