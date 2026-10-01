# Controller generation admission

An explicitly configured `RSIGovernanceCoordinator` plus a frozen holdout manifest and local
trial runner makes post-practice admission automatic. The controller persists the original
parent and immutable candidate before holdout; only an entirely active generation becomes the
next episode's snapshot. Rejection keeps the parent. Unknown evaluation blocks the whole run
and requires explicit evidence reconciliation; it never launches a second uncertain callback.

The manifest, policy, coordinator and trial-runner fingerprints belong to the durable run
identity. Child campaigns also bind the complete generation intent and original parent run
budget, sharing transfer/evaluator/unknown-retry limits and the absolute deadline. Completed
generation replay does not consume budget or dispatch trials. Inherited items are re-admitted
with explicit active-parent lineage, allowing multiple generations in one DRS/BRS run.
Each completed controller marker binds the actual immutable generation admission checkpoint.
Recovery checks candidate/source proof and the independent governance phase; a self-rehashed
controller checkpoint cannot turn an unadmitted candidate into a completed run. Later revocation
does not erase historical terminal diagnostics, but still refuses new retrieval.

`generation_campaign_runner(run_id)` exposes the same durable child campaign composition for
explicit recovery after uncertain trials have been reconciled. A caller may obtain the frozen
request from coordinator inspection, recover the child report, then call `reconcile_holdout`
with exact outer callback evidence. These are trusted local APIs, not remote authenticity proof.
Revalidation may be called explicitly or enabled with `generation_revalidate_before_dispatch=True`;
a failed report quarantines the generation and the solver gate refuses it. See
`controller-dispatch-revalidation.md`. This does not add a background scheduler or real evaluator.

Focused validation covers multi-generation DRS, ordered BRS, rejected and unknown holdout,
shared budget exhaustion, publication interruption/replay, drift and post-activation revocation.
