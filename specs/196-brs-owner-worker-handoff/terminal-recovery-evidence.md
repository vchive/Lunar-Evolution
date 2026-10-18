# Independent terminal recovery evidence

## Scope and existing boundary

This successor starts from PR126's frozen `74a3f52`. Its 561 distinct scoped
fixtures passed independently on macOS and Linux; full GitHub CI is a separate
pending gate. Do not modify that candidate or the primary checkout's local work.

The four mailbox observations prove transport history only. They do not prove
callback completion, a naturally terminal episode, or native producer cleanup.
This slice adds those independent observations and a read-only composer, then
reuses the existing explicit atomic obligation consume. It covers the private
published path with local inert/provider-free fixtures. Public native BRS,
production admission and online publication remain disabled. Native all-rejected
C1/P/C2, serial successors, real runtime/project acceptance and P2 are separate.

## Independent facts and ordering

Keep the v1 selected obligation and its original capture unchanged. Add a separate
append-only `rsi-brs-terminal:<obligation digest>` namespace with four adjacent
events: `delivery`, `callback_started`, `callback_finished`, `worker_terminal`.
All events retain the original mailbox binding, request/plan/claim/handoff and
owner/worker identity. The delivery retains bounded exact request/response bytes
and original publication terminal sources; message hashes never substitute for
a canonical saved SolverResult digest. Stay within the existing 8 MiB checkpoint
limit and existing fingerprint size/depth/container limits.

The original worker endpoint waits until the owner has durably recorded and read
back delivery and callback-start observations before invoking the existing
one-shot settlement callback. This closes the race where the worker completes
before the old writer records transport. Callback-return values grant no proof.
A callback exception or an uncertain write is unknown and is never retried.

Only the original owner session can observe its actual Future, executor and
worker Thread. Worker-terminal requires natural Future completion, executor
shutdown/join, mailbox close and the actual thread no longer alive. This is
distinct from the earlier native producer OS process. The original producer
capture must independently reobserve exit, absent process group and verified
cleanup; a capture originally unknown stays unknown forever.

Publication terminal must be reread from the original immutable lineage,
publication journal and material pins. It is not inferred from callback return,
transport receipt or a saved result. The natural PracticeEpisodeRunner must save
the original native result and append the legal terminal episode successor.
Do not manufacture legacy ready/ACK or selected-return evidence.

## Read and consume

A coherent read-only ledger snapshot contains root/mailbox/terminal histories,
episode history, original native claim and exact saved request/result. The
composer reparses each independent domain, reobserves original native records,
and detects head changes before returning. It returns ready only for complete,
matching evidence; missing or uncertain legs remain unknown, drift is rejected.
An inspection report, even with a correct self-digest, is not authority.

The explicit controller method acquires the existing run lock and freshly
composes from original contexts. Only a ready composition reaches the existing
consume. That transaction rechecks root and side heads, original obligation,
actual episode, claim and saved result in the same BEGIN IMMEDIATE as checkpoint
CAS/removal. Unknown inspection does not write a checkpoint, retry a solver,
advance a cursor or clear the default resume fence.

## Verification

- Natural inert worker completion through the actual runner and immutable result.
- Durable callback ACK ordering, one-shot invocation and unknown preservation.
- Independent producer cleanup versus worker-thread completion; unknown capture
  cannot be upgraded by files that appear later.
- Missing stages/legs, exact-envelope substitutions, publication material drift,
  legal terminal descendants and consume-time concurrent ledger changes.
- Rebuilt-ledger read-only inspection and explicit ready-only consume.
- Compatibility with mailbox observations, reconcile/default recovery gates,
  native result delivery and owner identity/source policy.

Run focused tests, Ruff, compileall and git diff --check. Freeze one source for
matching macOS/Linux scoped verification and independent review before a stacked
PR. Full prerequisite GitHub CI must pass before merging in dependency order.
