# Feature 196 — owner publication validation matrix (draft)

All cases use local provider-free/inert fixtures. No WebAgent, remote/company
evaluator, real solver/model campaign, sealed runtime or external worker is allowed.
The public native BRS entrance must continue to refuse throughout this slice.

Each case checks both the semantic result and the side-effect invariant. Unless a
case explicitly says `P durable`, no archive/state, final candidate tree, lineage
head, checkpoint, budget or sibling request may change.

| ID | Boundary | Fixture/action | Required result and evidence |
| --- | --- | --- | --- |
| PUB-01 | Prepared | Valid selected return and retained ACK | Prepared observation is accepted; no C1/P/C2 or head advance occurs. |
| PUB-02 | Worker refusal | Call owner publication facade from selected worker thread | Fixed owner-only refusal before publication lock/I/O; all durable bytes unchanged. |
| PUB-03 | Scope refusal | Owner thread without active owner lease/selected service | Refusal before C1 and no checkpoint/budget mutation. |
| PUB-04 | Identity refusal | Foreign run, wave, episode, nonce, owner thread, controller, ledger, workspace or sidecar | Refusal before staging; original selected evidence remains diagnosable. |
| PUB-05 | Source/control drift | Mutate source, policy, evaluator, environment, execution control or deadline after prepared | Refusal before C1/P; no pin refresh or retry. |
| PUB-06 | C1 success | Exact captured head and original prepared reference | One owner CAS records C1; C1 bytes and before archive/state pins are read-back verified. |
| PUB-07 | C1 replay | Invoke C1 twice or reuse a consumed selected return | Duplicate/consumed refusal; no second budget or execution reservation. |
| PUB-08 | C1 stale head | Replace checkpoint/current head before C1 | CAS refusal; old captured head remains stale and latest disk head is not adopted. |
| PUB-09 | C1 callback attack | Callback/equality/serializer attempts during handoff or DTO inspection | Strict detached DTO gate refuses; callback count remains zero; no C1/P side effect. |
| PUB-10 | P success | Valid C1, exact prepared journal and retained native evidence | Existing publication transaction runs only on owner; P terminal and complete read-back are durable. |
| PUB-11 | P worker attempt | Worker directly calls staging/commit/publication helper | Owner-only refusal before transaction/lock; prepared evidence and C1 unchanged. |
| PUB-12 | P plan drift | Change plan, journal, admission, attempt anchor, receipt or deadline | Refusal before first final move; no evaluator/provider replay. |
| PUB-13 | P prefix drift | Change archive/state bytes, inode, mode, parent or publication lock identity | Refusal before final move; source and staged evidence retained. |
| PUB-14 | P unknown marker | Fail after durable unknown marker or during first final move | `P durable` unknown obligation retained; no success/C2, rollback, repair or sibling dispatch. |
| PUB-15 | P pre-marker failure | Fail before transaction unknown marker | Known refusal with no final publication; C1 and prepared evidence remain. |
| PUB-16 | C2 success | Valid P terminal, exact C1 and `H_after` read-back | One owner CAS records C2; terminal/after pins match; only then wave head advances. |
| PUB-17 | C2 stale CAS | Replace checkpoint/head between P and C2 | C2 refusal or unknown according to durable evidence; captured head remains stale, no latest adoption. |
| PUB-18 | C2 read-back drift | Mutate terminal journal, archive/state, candidate tree, sidecar or receipt after P | C2 refusal; durable P evidence is retained and no rollback/repair occurs. |
| PUB-19 | P-without-C2 recovery | Persist valid P terminal but omit C2 | Read-only original-terminal inspection only; no worker adoption, retry, or successor. |
| PUB-20 | C1-without-P recovery | Persist C1 then interrupt before P | Unknown/blocked wave; no publication replay or fresh ordinal. |
| PUB-21 | Result mismatch | Durable episode/result differs from returned execution or verifier | C2 refusal; no candidate/memory promotion and no successful settlement. |
| PUB-22 | Known rejection | Valid owner rejection terminal | Existing rejection C1/P/C2 semantics; published head, archive/state and memory remain unchanged. |
| PUB-23 | Deadline/cancel | Expire shared control before C1, during P, and after marker | Before marker: refusal/no write; after marker: durable unknown; no retry or budget refresh. |
| PUB-24 | Channel close/owner exit | Close channel or lose owner lease while worker waits/returns | Durable evidence retained; no C1/P/C2 completion or sibling dispatch. |
| PUB-25 | Serial successor | Complete C2, then select ordinal 1 | Fresh handoff uses exact C2 head; original M0/reservation retained; ordinal 0 values cannot be reused. |
| PUB-26 | Successor blocked | Leave prior C1/P/C2 unknown or pending | No next ordinal; terminal inspection is read-only. |
| PUB-27 | Public gate | Invoke public `_drive_brs` / native entrance in default configuration | Existing refusal remains exact; this slice does not advertise native BRS. |
| PUB-28 | Legacy compatibility | Run existing DRS/single-child/admission/settlement suites | Canonical legacy bytes and behavior unchanged; no new publication fields on legacy runs. |

## Evidence and commands

A final focused run must record exact test inventory, raw JUnit XML, process exit
chain, source/install/import origins, and disjoint inventory hash. Repeat with the
frozen final source only after implementation; do not combine results from differing
source hashes.

```bash
PYTHONPATH=src pytest -q \
  tests/test_rsi_python_brs_handoff.py \
  tests/test_rsi_python_brs_selected_settlement.py \
  tests/test_rsi_python_publication.py \
  tests/test_producer_bundle_publication.py
ruff check src tests tools
python -m compileall -q src tests
git diff --check
```

The matrix is a design gate, not a claim that these tests or the owner publication
path already exist. Passing the focused matrix would still not authorize public
native BRS, external workers or distributed ownership; those require independent
SDDs and final acceptance.
