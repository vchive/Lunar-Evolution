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
| Selected owner service and drift/lock/result gates | 28 | provider-free pass |

The public `_drive_brs` entrance remains refusal-only and no native producer,
sealed runtime, external worker, remote evaluator or production admission is enabled.
The 145 local cases are focused seam evidence, not native BRS acceptance.
