# Original BRS owner success evidence facades

This slice adds only original-owner `retain_staged`, `verify_precommit` and
`retain_terminal` over the existing first-ordinal staged/terminal checkpoint
primitives. It creates native retained after snapshots and success descriptors;
it never stages, evaluates, commits, settles a worker or dispatches a transaction.
Public BRS, online publication and production admission remain disabled. No DRS
flow context, current-head adoption, recovery retry or successor is introduced.

## Contract and lock order

- The original registered ephemeral owner, owner thread, held run lease, running
  run/episode, started claim without result, selected handoff/channel, original
  strategy/config/authority, source/policy, control allowance and captured head
  remain mandatory. Success requires the original task already equal its episode.
- Both retention facades run full source/configuration/control observations outside
  publication and observation locks. They accept exact native success DTOs only,
  account for shared ready evidence and snapshots and bounded checkpoint bytes
  before any create, retain create-only files, then call the existing exact staged
  or terminal checkpoint. Invalid or ambiguous writes retain evidence and poison
  the owner. There is no retry, cleanup or refresh.
- `_success_observe(stage=None)` is the private lock-outside full gate.
  `_success_fixed(stage=None)` only checks original identities, local control pin
  and cancellation bit, channel, durable head/history and running claim; it never
  invokes source/configuration/control predicates or acquires the run lease.
- `verify_precommit` requires the genuine held workspace publication lock and the
  already-held original run lease. It observes the acknowledged current staged
  checkpoint, all original before/after snapshots, source pins, manifest/materials,
  handoff, deterministic population projection and exact staged marker, without
  callbacks or checkpoint writes. The caller must immediately perform the original
  native `revalidate_after_observation` before its first publication mutation; that
  captured native gate checks the original local and parent deadlines without
  replaying predicates. This slice does not alter the DRS-only dispatch gates.
- Success retention adds final fixed control/channel/evidence gates around its own
  CAS/readback and channel-serialized shared-head advance. Low-level checkpoint
  callers retain their existing contract. No descriptor is an execution grant.
- Each retention has a conservative, ephemeral elapsed-time cap derived from the
  original control's remaining allowance and a system monotonic sample taken before
  full observations. Later samples can only narrow it. Full source/control hooks
  cannot replace or reset the captured cap; pure final evidence, CAS and readback
  time consumes it. Expiry before CAS refuses a write; expiry or late cancellation
  after CAS preserves durable evidence and the original stale capture. The cap is
  cleared at retention exit, never persisted as a new budget, and never created by
  a standalone full observation. Precommit requires no residual retention cap and
  leaves native deadline enforcement to its caller's original numeric revalidator.

## Focused validation plan

Use genuine original native BRS owner fixtures and explicitly written inert staged
and terminal evidence. Block subprocess, sockets, transaction, staging and commit.
Cover exact retained snapshots/descriptors and adjacent CAS; running claim/no result;
lock/phase/foreign DTO refusal; rejection refusal; before/after/source/marker/material
and projection drift; pre-create aggregate/checkpoint capacity; source replacement,
create conflict and ambiguous CAS/readback; final control/channel drift; callback-free
precommit under a genuine lock. Run targeted old compatibility, Ruff, compileall and
diff-check; retain every failed XML separately from final-source results.

## Development evidence boundaries

The first two happy cases correctly refused a legacy fixture's completed ready/ACK
request. The fixture now uses the original-owner prepared-reference pin and separate
prepared-evidence acknowledgment, leaving the selected channel empty throughout.
The success channel contract was not widened. Later happy failures came from a
nonexistent fixture configuration hook and a marker fixture missing its native
digest/pretty encoding; both fixture errors were corrected. All XML remains under
the ignored `.lunar-evolution/reports/brs-success-evidence-facades/` directory.

An earlier 33-case development source passed before the final cap anti-refresh,
strict unbound-owner and additional canonical-globals coverage. It is not final
acceptance. The final module collects 38 cases; an eight-case gate selection passes
on the current product/test bytes. Full final-source development and integrated
platform acceptance are recorded separately and must not add older counts.
