# Opt-in memory regression before solver dispatch

`generation_revalidate_before_dispatch=False` preserves existing controller behavior. Enabling
it requires the same-ledger generation coordinator, frozen regression tasks and explicit local
trial runner. The flag is part of the durable run fingerprint.

For each new episode intent with nonempty memory, the controller derives the validation ID
`dispatch:<request.digest()>` and revalidates the corresponding exact generation before reserving
or publishing the solver intent. Empty bootstrap memory skips this check. The same request's
before-run check reads the completed validation and never re-evaluates or consumes a second
budget reservation. BRS prepares these validations in the owning controller thread; dispatch
workers perform only the verified read-only replay while the controller owns the parent lock.
This replay independently reconstructs the expected `GenerationCampaignRunner` source/config
fingerprint from the actual manifest, raw trial runner, live controller components and original
parent run/request/database/planned-budget identity. An unrelated explicitly registered verifier
cannot prepopulate the same validation ID to bypass this gate. Live flag/configuration drift is
also refused immediately before dispatch.

All child trials and explicit recovery consume the original parent account and retain its
absolute deadline. A valid regression rejection quarantines the generation and blocks the solver;
it does not rewrite the request to use a different memory snapshot. Unknown revalidation raises
`rsi_generation_revalidation_reconcile_required` on both initial execution and resume, before any
solver launch. It cannot be bypassed by an older completed validation. Explicit child/outer
evidence reconciliation is required before the same intent may proceed. Completed terminal-run
diagnostics remain read-only.

Focused provider-free fixtures cover opt-in configuration, repeated before-run replay, DRS/BRS,
unknown recovery and explicit reconciliation, failed regression quarantine, shared-budget stop,
publication interruption and configuration drift. No background scheduler or real evaluator is
introduced by this local dispatch policy.
