# DRS owning-thread first admission pin

## Bounded continuation

Build on the explicit existing-pin publication facade. Add a provider-facing publication
entry point that can install the first admission reference while an active DRS episode
is executing on its controller's owning thread. Use only inert local provider fixtures.
This does not wire a sealed CPython runtime or the real OpenEvolve/Shinka providers.
BRS worker-to-owner ready/ack scheduling remains separate: a worker cannot take the
owner lock while the owner waits for its future, and this slice adds no such wait.

## Original owner context

During fresh `_execute_intent`, scope an ephemeral per-controller, per-thread binding
to the exact active DRS state, run and episode, original checkpoint head and canonical
payload. Bind only when a producer sidecar is supplied and the executing thread already
owns the controller lock. Existing unbound/direct calls and BRS behavior stay unchanged;
the new entry point refuses when this owner context is absent. Restore the previous
scope on success and exception. It grants no new lock, launch or evaluator authority.

The internal first-pin helper requires that exact context, the same ledger/workspace,
the owning thread, unchanged active state and the original durable checkpoint. It
validates the original run/episode/native plan, existing sidecar/handoff/prepared/anchor
through the established admission API. Native results must not already be terminal.
Keep the public explicit `pin_python_admission` and stale-state refusal semantics.

Atomically pin the row and reference using the captured checkpoint CAS. Retain the
returned checkpoint digest. Independently reread the head and require its payload to
equal the original captured state with only the precise reference added. Revalidate
the original evidence, then update only `state['python_admission_refs']` and the
ephemeral captured head/payload. Never clear/update the entire state from the latest
durable checkpoint, refresh a budget/deadline or alter the run request/proof/plan.
If pin succeeds but acknowledgement fails, preserve the durable obligation and leave
the old state unadopted; recovery must load and verify it explicitly.

## Prepared boundary

The standalone transaction accepts an optional `prepared_observer`. Call it once after
the original prepared journal is durable and the original handoff/content anchor have
been verified, before terminal replay or the first evaluator. The earlier
`producer_prepared_intent` checkpoint is not a durable notification and may repeat.
After the observer, recheck checkpoint/cancellation/deadline and all original evidence
before proceeding. Observer failure preserves prepared material and invokes no new
evaluation or publication. Existing callers without the observer retain their wires.

The new `run_rsi_python_bundle_publication_for_active_flow` entry point requires the
caller-retained native plan, exact prepared journal, expected content-anchor digest,
strategy/drafts and admission plan. Derive publication identity from the retained
journal. Before pin, require unchanged owner context and original producer proof;
at the prepared callback, require the generated journal to equal the retained journal,
then pin and acknowledge it. After pin, require the complete existing admission
binding at every evidence boundary and successful return, just like the old facade.
Missing required rows never get recreated. Recovery keeps using the existing read-only
facade with an independently retained record digest; the new entry point is not resume.

Do not retrofit the record digest into the prepared journal, which the record already
binds. Do not invoke a provider twice, repair an unknown journal, automatically adopt
an unrelated checkpoint or fabricate runtime observations. `production_admission=false`.

## Verification

Cover owner-only DRS first pin and exact replay; unchanged original state except the
reference; public stale-state refusal; wrong checkpoint/episode/thread/BRS context;
unrelated durable or in-memory changes; evidence drift before and after pin; crash
between pin and acknowledgement; missing row on replay; timeout/cancellation during
the prepared callback; and prepared observer success/failure before any evaluator.
Include an inert provider/active-controller flow proving pin precedes native terminal
settlement and the acknowledged state can continue without losing the obligation.

Run focused and relevant compatibility tests, Ruff, compileall and diff checks. Final
source requires full three-version CI and independent raw/source/tree audit. SQLite
and file observations are not globally atomic against a hostile concurrent writer;
coherent rewriting of all trusted local pins remains outside this local trust model.
