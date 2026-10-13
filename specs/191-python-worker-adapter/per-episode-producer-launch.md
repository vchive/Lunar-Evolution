# DRS per-episode durable producer staging

## Current deliverable and status

This is the controller-called staging slice following PR88 source
`5bb90c915f8a3bd0e729ae6ede750595c406edb1`. The implementation creates native
request/memory inputs, binds a child launch and exclusively persists its Python
producer sidecar. It durably records `preparing → ready|unknown` in the existing
controller journal, then explicitly refuses dispatch before a running episode,
native claim, attestation consumption, registration or evaluator invocation.
`ready` is retained staging evidence, never dispatch authority.

Only local inert fixtures validate this slice. Full DRS execution/admission,
BRS, real CPython/toolchain/project runtime, upstream campaigns, model/evaluator
calls, CLI production and P2 remain open. `production_admission=false`.

## Preserved authority and opt-in

PR88's gateway pins one pre-staged request/memory/launch. DRS changes requests
and approved memory, so its pure plan factory cannot stage the next request.
This slice does not widen that gateway or rotate `self.producer_sidecar`.
The initial run retains its original `producer_checkpoint_binding`, original
sidecar, runtime/profile and absolute deadline in every checkpoint. Child proofs
cannot replace the root proof.

A new DRS run explicitly includes the immutable staging policy and dependency
fingerprint in its original run request. A legacy/unbound run cannot gain that
mode on resume, and an opted-in run cannot remove/change it. BRS opt-in refuses
before run creation. Legacy controller/gateway/wire behavior stays unchanged.

## Implemented durable sequence

1. Pure callback-free DTO and capacity preflight runs before budget reservation.
   It includes the pending episode/request intent and bounded budget/phase growth.
   `_prepare_intent` then preserves the existing once-only budget reservation and
   durably saves the original planned episode and complete SolverRequest.
2. The owner controller rechecks its original root/profile, existing ledger and
   absence of episode/result/native claim effects before first staging. It derives
   deterministic journal/launch IDs from the original run/episode/request digest.
3. The next checkpoint exclusively records a `preparing` entry against the captured
   original intent checkpoint CAS. Identity retains the original first run record
   and request SHA, exact durable episode/request, approved origin memory, digests,
   journal/launch IDs and policy. `origin_checkpoint_sha256` names the immediately
   preceding durable intent checkpoint, not the preparing checkpoint itself.
4. Only the adjacent successful preparing-CAS stack frame receives a transient,
   one-call permit binding stager, exact state object, captured preparing head and
   owner thread. `stage` requires exact controller/ledger types, its held existing
   controller lock, matching durable preparing state and this permit; it consumes
   the permit before effects. Restart, readback and nested calls cannot remint it.
5. Existing `prepare_native_rsi_inputs`, `bind_native_rsi_launch` and
   `persist_python_producer_binding` exclusively create child inputs/launch/sidecar.
   The original intent is copied with only deterministic IDs, episode task and
   native input argv replaced. An explicit stable fixture supplier provides a fresh
   attestation. Its callback cannot change the retained launch policy/config/root.
   No nonce is consumed and no process runs.
6. The complete returned binding, original sidecar bytes/inode/mode/link/time pin,
   input descriptor/manifest and native execution plan are reread/reparsed and
   saved `ready` against the same captured preparing CAS. Full child intent and
   binding must match the root template plus controlled episode/input fields.
   The controller then returns fixed `dispatch_not_accepted` before any execution.

The staging module and controller are the only product changes. No gateway,
store, scheduler, CLI, runtime owner or build asset is widened in this slice.

## Retained association and bounds

Use only the existing append-only controller journal. Strict identity validation
rederives request/memory digests and deterministic journal/launch IDs from the
original durable intent and approved origin memory. First preparing must immediately
follow that original intent checkpoint. Every later checkpoint retains all first
preparing identities and ready proofs unchanged. Removing, swapping, duplicating or
retrofitting a proof refuses. Child journal/launch IDs and attestation nonces must
be unique across root and retained children.

Bounds are conservative: at most 1–8 configured episodes, root/child binding at
most 32 KiB, request and memory each at most 8 KiB, workspace text at most 512
characters and prospective journal payload at most 112 KiB. The existing 128 KiB
ledger payload limit is unchanged. Growth includes full binding, repeated inputs,
retained identity and bounded pins/plan. If actual ready evidence exceeds its
preflight allowance, retain uncertainty and original partial evidence; do not
increase limits or remint the attempt.

The immutable policy fingerprints the fixed helper/validator/parser/type dependencies
and all capacity constants. Every ready observation rereads its original pins;
current disk stats are never used to reconstruct a new proof.

## Unknown, interruption and CAS

Any preparing entry without its acknowledged original ready checkpoint is uncertain,
including interruptions after input/sidecar creation or supplier return. Preserve
partial files and first refusal evidence. Resume is read-only: preparing/unknown
requires existing unknown reconciliation, ready rereads evidence and refuses dispatch.
It never restages, adopts a sidecar from disk, renews deadline/budget, picks new
IDs/nonces, rotates root proof or consumes another invocation reservation.

On staging failure, save only fixed `staging_failed` against the original preparing
head. Unknown persistence failure or an unrelated newer checkpoint returns fixed
`staging_checkpoint_conflict`; no subsequent finish/save refreshes CAS or adopts that
head. Successfully saved unknown may use the existing terminal unknown behavior
against its captured acknowledged checkpoint. This slice adds no staging repair
or new reconciliation authority.

## Full DRS closure remains future work

A complete execution slice requires an explicit episode-scoped resolver across:

- controller dispatch/replay/cache/save and `_python_admission_inputs`,
  `_python_admission_evidence` and prepared reference validation;
- gateway composition/read-only child plan/provider selection;
- store admission anchor and original child association checks in existing transactions;
- scheduler prepared bridge and lazy handoff hooks.

These consumers currently use the original global sidecar/root proof. Selecting a
child must preserve independent root validation and existing native claims,
admission receipts, first-pin/CAS ownership, publication and unknown recovery.
Mutating the controller-wide root sidecar or weakening store admission checks is
not a credible closure. A future full slice must exercise target failure,
practice success and target retry with distinct child IDs and changed approved
memory, while keeping original root, parent budget and absolute deadline.

Real OpenEvolve/Shinka execution also requires the separate project runtime
profile. The current fixed frozen module set is startup/codec/fixture material;
it does not provide those upstream SDKs or a production campaign dispatcher.

## Local acceptance

Focused core tests cover hostile serializer/property shapes, bounded preflight,
identity/digest/ID rederivation, immediate origin association, missing/retrofit
history, original pin/plan readback, callback/config drift and reopened preparing
stage refusal. Independent controller cases cover durable intent/preparing order,
ready resume, supplier failure, ready CAS interruption, unrelated CAS conflict,
unknown persistence failure, legacy retrofit refusal, BRS and policy drift.

Focused tests, Ruff, compileall and diff-check are required. Unified compatibility,
source CI and independent audit remain separate merge obligations. These local
staging mechanism results cannot accept sealed runtime, upstream lifecycle,
model/evaluator effects or production CLI.
