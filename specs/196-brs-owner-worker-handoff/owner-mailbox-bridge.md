# PB-03 — private owner/mailbox composition slice

The exact-result composition follow-up upgrades this private response to the existing
result-delivery protocol; see [the follow-up contract](exact-mailbox-result-composition.md).
The summary below describes this original slice, not the current follow-up wire.

This slice composes the existing one-shot `BRSOwnerPublicationMailbox` with the
private original-owner native success dispatch.  The owner calls
`run_brs_owner_publication_mailbox` on its original thread after the worker has
submitted the detached receipt/output/handoff request.  The helper services exactly
one request and invokes `_run_original_brs_native_publication` on the owner; the
worker only waits for an observation-only response.

The response carries a bounded status summary (`protocol`, `publication_status`,
and admitted candidate identifiers).  It contains no drafts, paths, evaluator
objects, lineage owner, admission reference, controller checkpoint, or retry token.
The worker response is therefore not publication authority and cannot settle a
controller result by itself.  Mailbox closure or lost delivery remains an unknown
obligation under the mailbox contract.

The helper is private and opt-in.  It requires the exact original preparation DTO,
mailbox class, owner control and callable check.  It does not create a mailbox,
refresh captured head/state pins, adopt current files, retry a transaction, settle a
worker result, advance a sibling ordinal, or run a rejection C1/P/C2 path.  Existing
policy fields remain `online_publication=false` and `production_admission=false`;
provider-free fixtures are the only validation boundary.  Public native BRS and
production admission remain refused.
