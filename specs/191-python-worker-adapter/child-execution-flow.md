# Opt-in controller child execution flow

## Scope

Continue the existing per-episode staging and atomic child claim APIs. The new
`RSILearningController(..., producer_child_execution=True)` is an explicit local
Python opt-in, requires the original exact Python producer gateway, ledger and
stager, and is retained in the immutable original run request and controller
checkpoint. Default staging-only, BRS and CLI behavior remain unchanged. No
legacy run may gain or lose this mode on resume. Production admission stays false.

## Fresh dispatch and authority

Only the same owning DRS stack frame that successfully stages and acknowledges
ready evidence can continue. Under the original controller lock and active flow,
resolve a child gateway from the original root and existing durable child proof;
never replace controller.gateway, producer_sidecar or runtime hooks. Revalidate
original checkpoint, request, historical memory, plan and control before claim.
The existing guarded claim is created before the runner writes a running episode.

A protected native fresh-dispatch context creates a local, thread-bound,
once-call continuation only after a newly acquired claim. It does not accept a
caller-provided started claim. The continuation is invalid outside its original
context, after one invocation, on config/plan/claim drift or on lost owner scope.
The original receipt provider, mapper and publication path are reused.

The existing runner records running, usage, durable worker result, terminal
state and independent verifier. The scheduler's late prepared observer retains
the existing admission pin/reference and publication boundaries. No new claim,
receipt, admission DTO, budget reservation or ledger is introduced.

## Recovery

Reading ready or started evidence never recreates a continuation. Interruptions
between claim, running, provider, prepared admission, publication and settlement
retain the original started/unknown obligation and partial artifacts. Resume
uses the historical request memory and original child gateway for retained
terminal validation, and never launches a provider. If the native result was
durably published before interruption, the controller may finish the existing
episode settlement and verifier records; this does not rerun native work or
reserve a second budget. A subsequent completed resume is read-only. If only
publication exists, without a durable native result, resume keeps the unknown
gate rather than reconstructing a fresh execution. Explicit native failure
reconcile selects the same child and reuses the existing pinned failure policy.
Missing result or terminal evidence refuses without retry, restaging, a new
nonce, budget consumption or adoption of current disk pins.

The retained candidate reader reconstructs the evaluation receipt with the
original published journal's Python handoff digest, only after the existing
publication recovery has verified its pinned handoff and attempt anchor. The
unbound candidate projection omits that field; legacy journals without a Python
handoff keep their original canonical receipt bytes. Source or handoff drift is
still a refusal, never an opportunity to recompute authority from current files.

## Acceptance and limits

A single target fixture must traverse actual guarded claim, running episode,
prepared admission, original publication transaction/receipt mapper, result,
verifier and terminal read-only replay. Only the lowest inert process/evaluator
seams may be replaced. Additional cases cover cancellation, fixed deadlines,
claim/running interruption, unknown result, evidence drift, root preservation,
mode retrofit/removal and started-claim relaunch refusal.

Run focused tests, Ruff, compileall and diff checks, then final-source CI and
independent raw/source/tree audit. This slice does not accept real CPython,
toolchain, sealed runtime or OpenEvolve/Shinka project lifecycle. Multi-episode
DRS with changed approved memory and multi-child BRS require separate complete
acceptance; neither is implied by a single target passing.
