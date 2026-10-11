# Late controller admission evidence

## Scope

Extend Feature191 with an explicit local controller/ledger evidence registration API.
The admission anchor contains post-execution evidence. It must never change the
original pre-execution run request, producer proof, native plan, gateway fingerprint
or existing controller checkpoint wire. This slice is not automatic scheduler
admission, successful runtime observation or a production launcher. Every record
retains `production_admission=false`.

The existing scheduler lacks Python runtime/handoff inputs. Connecting its live
path before Feature189/190 runtime acceptance would expand this slice improperly.
An independent evidence row also does not make ordinary resume detect deletion of
that row; a future live flow must explicitly pin its required admission identity.

## Interfaces and immutable identity

`rsi_python_admission.py` supplies a bounded strict canonical evidence DTO/parser.
Identity binds the original run request digest and first run record digest, original
producer checkpoint proof digest, episode ID/request digest, original native claim
digest and native execution-plan digest, prepared publication-journal digest, complete
admission anchor and original handoff file pin. It retains run/journal/attempt IDs.
Reused DTOs and nested objects are reparsed; duplicate keys, callback-bearing or
subclass collections, zero digests, altered types/fields and authority upgrades refuse.
Original fractional anchor budget/deadline values survive exactly.

`RSILearningController.register_python_admission(run_id, episode_id, *, native_plan,
prepared_journal, expected_anchor_sha256)` explicitly registers existing evidence.
`validate_python_admission` takes the same inputs plus `expected_record_sha256` and
only reads an existing record. Both use the controller's original producer workspace
and sidecar, not arbitrary newly discovered runtime/handoff files. The prepared journal
is an exact retained `prepared`/`preflight` DTO with its original Python handoff pin.

The native plan is a different protocol from the bundle admission plan: compare its
digest to the original native claim, and its launch/intent/attestation identities and
deadline to the original Python binding. Never compare its digest directly with
`anchor.admission_plan_sha256`. Its request must equal the existing checkpoint intent
request and episode attribution, including the original memory digest.

## Registration and replay gates

Require an existing original producer-bound run, controller checkpoint with the same
proof, attributed episode/intent, and existing native claim. Do not retrofit a proof
into a run that was originally unbound. Revalidate the original binding sidecar, pinned
handoff, content anchor and immutable prepared association at entry and after evidence
I/O. Check run/episode/journal, binding, authority fingerprints, deadline/limits and
sidecar-pin domain links rather than trusting detached field equality alone.

The ledger uses a separate create-only table. Under the existing controller lock,
one `BEGIN IMMEDIATE` transaction rechecks the first/current run proof, checkpoint,
episode and native claim, compares caller-retained head digests, then inserts only
when the run/checkpoint and attributed episode are active and running, and the native
claim has no persisted terminal result. A missing row on terminal/unknown run,
episode or native result state must refuse registration; explicit validation may inspect a previously retained
row in those states. Exact existing bytes replay read-only without changing timestamps,
budget, run/episode revisions, checkpoint, claim, journal or filesystem evidence.
Different bytes under the same identity and duplicate attempt ownership refuse.

No external callback, solver, evaluator, launch or budget reservation occurs. Unknown
SQLite/write outcomes retain evidence and require inspection; no automatic row repair,
evidence regeneration or success settlement is added. The existing local trust model
does not resist coherent rewriting/deletion of every trusted database/file anchor.

## Required verification

Focused provider-free tests cover registration and exact no-write replay; explicit
read-only validation after terminal/unknown; refusal to backfill missing records in
those states; unbound retrofit and original proof drift; missing/mismatched episode,
request, memory, native claim or plan; journal/handoff/anchor/pin/fingerprint/limit drift;
evidence changes during reads; CAS/controller lock conflicts; fractional values;
stale DTO/subclass/callback collections; unchanged original run/plan/checkpoint bytes.
Malformed retained run/episode/checkpoint payloads use fixed RSI refusal codes instead
of leaking parser exceptions. Test legal episode/native terminal transitions while the
parent run is still running, both before first registration and during existing replay.
Every refusal avoids further mutations, solver/evaluator calls and budget charges.
Run focused and compatibility tests, Ruff, compileall and diff checks, then the
final source's full Ubuntu3.11/3.12/3.13 CI and independent raw/source/tree audit.

The original run request digest is recomputed from its first retained payload;
re-signing a producer proof while leaving that original request unchanged refuses.
Original, current and checkpoint planned budgets must agree, the frozen intent
request keeps that planned snapshot, and binding/native-plan deadlines match its
original deadline. Reuse a validated current-thread controller lock; a foreign
owner still refuses. A final anchor content read precedes renewed original
handoff/prepared/sidecar checks. SQLite CAS and file observations are separate
resources, not one globally atomic transaction against a concurrent hostile writer.
