# Feature 196 plan

## Dependencies

The implementation must consume the existing contracts in this order:

1. BRS-0/1 preflight and identity/capacity checks: fresh policy, immutable wave
   intents, one reservation, `M0`, source/policy fingerprints, and `max_workers=1`.
2. `rsi_python_brs_admission.py`: existing bounded ready/ack channel, exact run /
   episode / payload digest checks, duplicate refusal and close wakeups.
3. Controller BRS scopes: `_drive_brs`, `_execute_brs_intent`, the worker scope and
   owner service loop. The old DRS flow context remains unchanged.
4. Producer stager/bridge and child claim contracts: one selected ordinal gets a
   one-call owner permit; worker capability is invocation-scoped and cannot carry
   controller ownership.
5. Existing publication-lineage v2 and known-rejection settlement: owner-thread
   CAS and ordinal head continuity after the child returns.
6. Partial-wave recovery: completed child obligations remain in the wave scope,
   while only the selected missing child can receive a fresh dispatch handoff.

No dependency may be satisfied by deleting a DRS gate, accepting latest state,
reusing a retained ready message, or turning a read-only inspector into authority.

## Implementation slices

- **BRS-2a handoff value and gate**: define a detached, canonical in-memory handoff
  and exact selected-ordinal checks; refuse mode, wave, M0, owner, head, source,
  policy, thread, nonce, and `max_workers` drift before worker effects.
- **BRS-2b owner service loop**: bind the existing ready/ack channel to the selected
  handoff, service requests while futures run, and close before executor shutdown.
  Keep controller/observation/workspace locks out of waits and callbacks.
- **BRS-2c worker return boundary**: let the worker return only its execution result
  and retained admission digest. Keep publication, checkpoint save, head advance,
  and all C1/P/C2 decisions on the owner thread.
- **BRS-2d serial next-ordinal transition**: after a durable terminal result, create
  a new handoff against the new owner head. Preserve the original wave reservation
  and `M0`; never prebind every child to one stale publication base.
- **BRS-2e recovery and refusal**: preserve unknown/error/closed obligations,
  reject duplicate or foreign handoffs, and make repeated terminal inspection
  read-only.

Each slice requires focused local tests and static checks before integration. Product
source remains frozen while mixed v2 acceptance is running; no native BRS path is
advertised until a separate complete acceptance proves it.
