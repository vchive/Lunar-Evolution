# Feature 196 — BRS owner publication boundary (draft)

**Status: design-only draft, not implemented or accepted.**

The private BRS service currently returns and settles one selected execution in the
controller checkpoint. It does not publish a candidate, advance a publication head,
perform C1/P/C2, or dispatch an ordinal successor. This document defines the next
owner-only boundary so that implementation does not accidentally turn a worker
result or a prepared admission receipt into publication authority.

This draft is provider-free and applies only to the existing in-process owner and
one selected worker. `production_admission` remains `False`; public native BRS,
external workers, remote evaluators, distributed ownership and real campaigns stay
closed.

## Boundary vocabulary

The terms below describe observations and owner mutations, rather than new public
wire values.

- **Prepared** is the worker's exact native plan, prepared journal, anchor and
  retained admission reference after the owner has verified and acknowledged the
  ready message. It proves that a selected execution may be considered by the
  owner. It does not grant publication, memory promotion, lineage ownership or a
  successor permit.
- **C1** is the owner CAS that binds the prepared selected execution to the
  captured controller checkpoint and `H_before`. C1 retains the original run,
  wave, episode, handoff, source/configuration pins, prepared journal, admission
  record and before archive/state head. C1 is valid only on the original owner
  thread and only while the selected handoff and run lease remain live.
- **P** is the existing owner-side publication transaction. It stages and verifies
  the selected candidate or terminal rejection under the existing publication
  lock, writes the durable unknown marker before the first final move, and
  produces the exact publication terminal/read-back evidence. P never runs on a
  worker thread and never uses a newly observed latest head as its expected head.
- **C2** is the owner CAS that binds the verified P terminal to C1 and the exact
  `H_after` read-back. C2 retains the terminal journal/manifest, after archive/state
  pins, result/receipt association and publication outcome. Only a successful C2
  may update the in-memory wave head and create the next ordinal handoff.

For a successful selected candidate, the intended order is
`prepared -> C1 -> P -> C2`. For a known rejected terminal, the existing rejection
contract remains authoritative: C1 retains the rejection evidence, P means only the
existing verified rejection/provenance transition, and C2 binds the original
terminal result. A rejected result never advances the published head or promotes
memory. The implementation must not invent a new success or rejection wire schema
in this slice.

## Owner-only authority

The owner is the controller thread that created and still holds the original BRS
wave lease. It is the only authority allowed to:

1. create C1 from a current captured checkpoint;
2. invoke the existing publication staging/commit transaction;
3. acknowledge C2 after complete terminal and read-back verification;
4. advance the wave head or select the next ordinal; and
5. close the wave after terminal or unknown recovery rules are satisfied.

The selected worker may run the producer/evaluator seams, validate its own durable
execution, and send one prepared ready message. It must not acquire the controller
or publication lock, call a publication transaction, write archive/state or lineage
files, create/acknowledge C1 or C2, clear an unknown marker, promote memory, or
choose another ordinal. A callback, serialized ready value, retained receipt,
checkpoint read or current-disk file cannot reconstruct owner authority.

The owner-facing publication facade must fail before any staging, evaluator retry,
archive/state write, checkpoint mutation or lock acquisition when invoked from a
worker thread, without the exact selected handoff, outside the active owner scope,
with a foreign dispatch lease, or with a changed run/thread/source/workspace/sidecar
identity. The refusal must leave the prepared evidence and original durable
obligation available for read-only diagnosis.

## Captured head and CAS rules

At C1 entry the owner captures a complete checkpoint head `H_before`, the exact
controller state bytes, archive/state before pins, source/configuration fingerprints,
original budget/deadline and the selected handoff digest. It must use that capture
as the CAS expected value. It may not adopt a newer checkpoint, refresh a source
pin, or derive authority from the current archive after a mismatch.

The P transaction rechecks C1 and the live before prefix under the existing lock
order (controller owner, then publication lock). Its expected head remains
`H_before`. A stale head, payload, checkpoint, archive/state prefix, publication
lock identity, journal, prepared evidence, owner thread or source fingerprint
refuses before the first final move. A failure after the durable unknown marker is
an unknown publication obligation; it is never converted to a known refusal or
success by inspecting current files.

After P returns, the owner reads back the complete terminal and captures
`H_after`. C2 CAS must expect the exact C1 checkpoint and exact P terminal. It must
verify archive/state bytes, candidate trees, sidecars, journal marker and native
receipt identities before publishing the new in-memory head. A C2 CAS failure or
ambiguous read-back leaves the captured owner head stale and preserves the durable
P obligation. It grants no latest-head adoption, repair, replay, retry, memory
promotion or sibling dispatch.

If P is durably committed but C2 is missing, recovery may inspect the original
terminal only with the original pins and owner contract; it cannot rerun producer,
evaluator or publication. If P is unknown or partially committed, the wave is
blocked and the unknown evidence remains durable. If C1 exists without P, or P
exists without an original C2 association, the wave is also blocked; no orphan
worker or later checkpoint may self-adopt it.

## Serial transition and memory

The current slice keeps `max_workers=1`. A later ordinal gets a fresh handoff only
after C2 has durably verified the preceding terminal and the owner has captured the
new head. All ordinals retain the original wave reservation and root memory `M0`;
per-episode memory promotion follows the existing owner policy and is never done by
a worker. A stale prepared record for a prior ordinal cannot be reused for a new
ordinal, and a sibling cannot publish against a pre-bound stale head.

Terminal failure, deadline, cancellation, owner exit, CAS ambiguity and channel
close stop new sibling dispatch. Existing durable episode/result/evidence remains
available for explicit reconciliation under its original identity. There is no
automatic retry, checkpoint repair, budget refresh or current-disk adoption.

## Compatibility and explicit non-goals

The implementation must reuse the existing Feature 153 publication transaction,
Feature 191 controller-bound publication checks, BRS handoff/channel pins and the
private settlement checkpoint. It must preserve legacy DRS and single-child
canonical bytes and keep the public `_drive_brs` entrance refusal-only until a
separate complete native acceptance exists.

This draft does not authorize a new persistence table, RPC, scheduler, external
worker authentication, multi-machine ownership, remote evaluator, public CLI,
OpenEvolve/Shinka campaign or sealed runtime. Any additional checkpoint or lineage
fields require a separate reviewed schema/SDD change.

## Exit criteria for implementation

The boundary is not complete until focused local fixtures prove owner-only C1/P/C2,
zero-write worker refusal, exact captured-head CAS, durable unknown retention,
serial next-ordinal transition, and read-only recovery. A provider-free focused pass
is supporting evidence only; public native BRS remains disabled until final-source
CI and independent raw/source/tree audit cover the complete path.
