# Feature 196 validation plan

BRS-2a now has a pure detached handoff value and gate. It has no controller, ledger,
workspace, channel, CAS, worker dispatch or native BRS integration. The local focused
checks cover H01 identity serialization, H02 fixed worker count, H04 channel-level
selected ready/ack, H06 owner/head/source/policy drift, H07 nonce/replay/selection gates,
and H08 selected-channel close/error wakeups. The remaining matrix is for controller
integration. Tests must use local fixtures; no network, process campaign, WebAgent,
remote evaluator or company platform is allowed.

| ID | Scenario | Required assertion |
| --- | --- | --- |
| H01 | Fresh handoff shape | **Pure helper covered:** exact run/wave/episode/ordinal, M0, request, owner, head, source and policy pins serialize canonically; mutable subclasses are refused. |
| H02 | Policy and worker count | **Pure helper covered:** `max_workers=1`; existing child preflight requires BRS mode. Controller mode upgrade and pre-I/O integration gate remain open. |
| H03 | Owner lock boundary | Worker and nested callback never acquire the controller, lineage or checkpoint owner; owner-only CAS remains the sole mutation path. |
| H04 | Ready/ack meaning | **Channel helper covered:** ready/ack is bound to the single selected episode and exact ready digest. Durable pin-only semantics and non-escalation remain controller integration tests. |
| H05 | Queue while ordinal waits | Owner services a queued ready request while an earlier future runs without holding a wait lock; no deadlock at `max_workers=1`. |
| H06 | Head/state drift | **Pure helper covered:** changed head, state, controller, ledger, workspace, sidecar, owner thread, source, policy or execution-control fingerprint refuses. Durable evidence preservation remains an integration test. |
| H07 | Duplicate/foreign request | **Pure helper covered:** consumed nonce, wrong wave/ordinal and owner-thread drift refuse. Channel replay, sibling/nested/recovered requests and admission-reference uniqueness remain integration tests. |
| H08 | Ack failure / owner exit | **Channel helper covered:** selected-channel close and handler error wake waiters. Durable pin retention, owner exit ordering and no repair remain controller integration tests. |
| H09 | Deadline/cancel/unknown | Deadline, cancellation and unknown close the selected handoff, preserve budgets/evidence and do not auto-retry or dispatch a sibling. |
| H10 | Serial head continuity | After a completed or rejected child, the next ordinal gets a fresh handoff against the new head while all requests remain bound to M0 and the original reservation. |
| H11 | Partial-wave resume | Completed child references remain in the wave scope; only the missing selected ordinal may receive a fresh handoff; terminal resume is read-only. |
| H12 | Mixed publication | Success/rejection follows existing v2 owner CAS and C1/P/C2 rules; worker cannot publish or promote memory and rejected result never advances memory. |

Focused commands for this slice:

```bash
PYTHONPATH=src pytest -q \
  tests/test_rsi_python_brs_child_policy.py \
  tests/test_rsi_python_brs_handoff.py
ruff check src/lunar_evolution tests/test_rsi_python_brs_*.py
python -m compileall -q src tests
git diff --check
```

The channel atomically consumes the nonce under its in-memory condition lock and gates
ready messages to the selected episode. It does not verify that its caller holds the
controller mutation lock; future controller integration must call it inside the exact
owner scope. Channel completion checks acknowledged, non-cancelled, error-free request
state; it cannot observe the executor future. The caller must observe that future's
successful terminal outcome before invoking completion. The helper alone does not
provide native BRS dispatch or production admission.

The final acceptance must additionally compare complete source inventories before and
after, canonical tree and parent commits, all raw JUnit files and every durable
workspace/ledger/inode pin. A focused fixture pass cannot claim native runtime,
external worker authenticity, distributed ownership or production admission.

## Private selected owner-service slice

The controller now has a private, provider-free selected-service seam. It binds one
selected child from a complete BRS wave, checks original planned budget/deadline and
request budget before executor creation, runs source/configuration fingerprint hooks
outside the short observation lock, then rechecks strict handoff identity and owner
CAS pins inside that lock. The worker returns only a validated `EpisodeExecution`;
episode/request/result/verifier DTO types and verifier-to-episode consistency are
checked before durable result comparison. Channel ACKs are detached from caller
objects and completion verifies the retained owner fields.

The focused tests are split so their exact counters remain auditable:

| Scope | Cases | Result |
| --- | ---: | --- |
| Existing BRS admission/owner/publication | 104 | provider-free pass |
| Detached ACK channel | 13 | provider-free pass |
| Detached handoff contract | 30 | provider-free pass |
| Selected owner service and drift/lock/result gates | 28 | provider-free pass |

The public `_drive_brs` entrance remains refusal-only and no native producer,
sealed runtime, external worker, remote evaluator or production admission is enabled.
The 175 local cases are focused seam evidence, not native BRS acceptance.

## Private selected execution checkpoint settlement: validation scope

BRS-2c adds a separate owner checkpoint boundary after the existing worker/result
and channel completion boundary. Its new focused matrix must use the real selected
service, original ready/ACK, durable episode/result, `_save_flow` CAS and readback
on its successful path. Fault injection is reserved for refusal and interrupted
write/readback paths; it cannot manufacture a successful owner grant.

Required checks include original selected result persistence, owner thread and lock,
foreign/changed return values, duplicate settlement, retained ACK/result/source/M0/
budget drift, stale head, CAS and full readback failure. No sibling may launch or
acquire a refreshed request/reservation. A durable write followed by uncertain
readback remains retained with a stale owner head and no automatic retry. Existing
service, ACK, handoff, admission and public native-refusal tests remain regression
obligations. Final counters and source identity will be recorded after execution;
this plan alone does not complete a test or runtime acceptance.


### Settlement source-specific execution record

All runs below use only installed local provider-free/inert fixtures. Original
failures and interrupted attempts remain retained in separate ignored reports.
Counters across different source hashes are not added into one acceptance claim.

| Source / scope | Observed result | Boundary |
| --- | --- | --- |
| First 34-case attempt, 300s runner limit | partial; no complete final XML | Not acceptance or a proven product failure. |
| `132e530` controller / `7983f4d` tests, six groups | 272 distinct: 269 pass, 3 failures, zero errors/skips | Two invalid `None -= 1` budget faults and one expected-code mismatch with the existing checkpoint conflict gate; original XML/source/exit evidence is retained. |
| `eb01d461` controller / `ea478ae` tests, six groups | 274 distinct: 274 pass, zero failures/errors/skips | Real CAS/readback, post-save original owner/state identity, valid budget drift and exact conflict contract. Independent source/install/exit and inventory/JUnit disjoint-union audit passed. |
| Final callback hardening quick scope | 32 pass, zero failures/errors/skips | Exact DTO attribute dictionaries/keys, colliding keys, metaclass type callbacks, flow payload and wave-state rejection; callbacks remain zero. This is a parser/refusal gate, not worker execution acceptance. |
| Final integrated hardening scope | **360 pass; zero failures/errors/skips** | 85 settlement (53 service/CAS + 32 quick refusal), 221 existing BRS, 54 existing admission-flow. Eight exact node-hash groups; installed origins, source freeze, all exits and raw XML/inventory disjoint union independently audited. |

The final code SHA256 is
`5f2d932b21738b7d612da23292c6de2c8df0c52d655d21174b4364af1235da10`;
the final settlement test SHA256 is
`00229c85c1a277c4647454a3f7fe18c9f10f507076cea06c5a25543882c7171d`.
The earlier 274 inventory SHA256 is
`bdf14d90dbbe3ad7e166f068067b851b77bddf4b6cce0c81e18707cb88a5fc98`.
Its raw XML/source/exit receipts are under `final-six-jxxylqq_`; they do not certify
the later callback hardening. The original failed 272 run is `final-six-3mhbexg1`.

The workflow adds a separate 85-case no-skip settlement gate on Python 3.11/3.12/3.13;
the complete current suite still discovers the same module independently. A local
focused pass will close only this private checkpoint sub-slice, not public native
BRS, ordinal/publication recovery, real runtime/producer/CLI or production admission.
Final-source CI and independent raw/source/tree review remain separate obligations.


Final integrated run: `final-eight-1rb__9zs`, group counts
`45/42/42/50/42/44/49/46`, longest group 244.25 seconds. Dynamic inventory SHA256
`c84aa8e73886640ad9784e35b534d35bc85e427ad83d15f5aa92bf45fc0f1943`;
runner result SHA256 `f78b87803ee6e28bd453ed789cf7ebcb3d71e415e1d55e4c873be4449624eebe`.
Ruff over `src tests tools`, compileall and diff-check passed. Both the test owner's
stdlib audit and a separately written root auditor checked actual raw XML, all eight
exit records, exact disjoint inventory, original/actual source hashes, installed
editable import receipts and static argv/cwd/logs. Root audit SHA256
`81eae45be2ee940124c06d8f405796176a4ef1ca1a333c409c8852850340b6f0`.
The root auditor does not import or execute the product. Raw evidence is retained
on the server and copied into ignored local reports. Only documentation acceptance
status was updated after the final freeze; controller, tests and workflow remained
byte-identical to the accepted focused source. CI/integration remains pending.
