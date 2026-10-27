# Call-local admission checkpoint projections

Status: narrow P0 implementation and focused tests; regression evidence is recorded separately.

## Problem and boundary

`_python_admission_state_tx` validates the complete controller history for staging,
then selects the same four journal columns again and decodes every large payload
again for budget, snapshot and episode attribution checks. The second SELECT and
its validation boundaries are required. Repeating pure JSON work for unchanged
rows within that same call is unnecessary, especially as reserved child history
retains growing lineage and admission plans.

The two 600-second mixed observations locate the remaining work in this chain;
they do not establish a continuous profile or prove this change meets the deadline.
The later observation reached the third rejected child's owner settlement before
termination, with no retained successful settlement/whole-case completion evidence.

## Contract

- The legacy `_controller_checkpoint_history_tx(connection, run_id)` signature and
  list return remain unchanged. A private observation helper also returns its exact
  fresh `(revision, parent_sha256, payload, checkpoint_sha256)` input.
- Only `_python_admission_state_tx` retains a call-local projection. It independently
  copies `budget_state`, `producer_checkpoint_binding`, `run_id`, `root_snapshot`,
  `memory_snapshot` and `generations`; growing lineage and admission bodies are not
  copied for every historical checkpoint. No mutable staging result aliases that
  private projection.
- The original second complete SELECT remains at its original boundary. All four
  columns (read by explicit column name for SQLite and mapping rows), row ordering
  and row count must equal the original input before the
  projection and already calculated pure checkpoint digests can be reused.
- Every chain, budget, proof, run identity and snapshot validation still executes.
  The latest complete state is decoded again from the second fresh raw row before
  the original selected-proof, intent, episode and claim checks; returned state
  aliases neither the staging history nor the private projections.
- Changed raw inputs and replaced/in-place-changed history/digest/JSON helpers use
  the previous complete per-row parsing path. Mid-loop decoder drift refuses with
  the existing checkpoint-drift error. No success verdict, current head or mutable
  DTO is cached across calls, threads, owner operations or resumes. Decoder function
  defaults and keyword defaults, canonical encoding helpers and SHA-256 identity
  are included in the pure-work eligibility gate. Optional projection type/value/
  recursion failures preserve the already read history and use the old second pass.
- Existing BRS, reserved and rejection-ready executable/shadow inventories cover
  the new helper edges and module projections. There is no new execution authority.
- No SQL read, CAS, filesystem observation, worker terminal gate, configured budget,
  retry policy or mixed selector changes in this work.

## Validation plan

Focused tests compare optimized and forced-original results and error codes; count
full checkpoint decoder entries without replacing the decoder; verify both SELECTs
remain; inject changes in every selected raw column and row count/order; mutate the
staging validator's returned nested dictionaries; change history/decoder seams; and
check the enclosing policy refuses changed helpers/aliases. Repeated calls must
perform the same fresh work and returned state mutation must not affect later calls.

A pure-stdlib synthetic diagnostic with 30 rows of 135,864 characters, 300 rounds,
measured 0.630 seconds for the old second full-decode pass versus 0.0347 seconds for
small detached projections plus the latest full decode. This is a shape diagnostic,
not product timing evidence or acceptance of the mixed case. The final consolidated
focused/static checks and any newly reserved mixed run belong to the parent task.
