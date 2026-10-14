# Feature 196 validation plan

BRS-2a now has a pure detached handoff value and gate. It has no controller, ledger,
workspace, channel, CAS, worker dispatch or native BRS integration. The local focused
checks cover H01 identity serialization, H02 fixed worker count, H06 owner/head/source/
policy drift, and H07 nonce replay and selection drift. The remaining matrix is for
later integration. Tests must use local fixtures; no network, process campaign, WebAgent,
remote evaluator or company platform is allowed.

| ID | Scenario | Required assertion |
| --- | --- | --- |
| H01 | Fresh handoff shape | **Pure helper covered:** exact run/wave/episode/ordinal, M0, request, owner, head, source and policy pins serialize canonically; mutable subclasses are refused. |
| H02 | Policy and worker count | **Pure helper covered:** `max_workers=1`; existing child preflight requires BRS mode. Controller mode upgrade and pre-I/O integration gate remain open. |
| H03 | Owner lock boundary | Worker and nested callback never acquire the controller, lineage or checkpoint owner; owner-only CAS remains the sole mutation path. |
| H04 | Ready/ack meaning | Valid ready pins only the exact admission reference and returns its digest; it cannot launch, evaluate, publish, promote memory or settle C1/P/C2. |
| H05 | Queue while ordinal waits | Owner services a queued ready request while an earlier future runs without holding a wait lock; no deadlock at `max_workers=1`. |
| H06 | Head/state drift | **Pure helper covered:** changed head, state, controller, ledger, workspace, sidecar, owner thread, source, policy or execution-control fingerprint refuses. Durable evidence preservation remains an integration test. |
| H07 | Duplicate/foreign request | **Pure helper covered:** consumed nonce, wrong wave/ordinal and owner-thread drift refuse. Channel replay, sibling/nested/recovered requests and admission-reference uniqueness remain integration tests. |
| H08 | Ack failure / owner exit | Durable pin survives ack failure; close wakes workers before executor shutdown; no rollback, synthetic ack or missing-row repair occurs. |
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

A gate success only validates a snapshot. The eventual controller must atomically consume
the nonce under its owner lock before any worker effect; this helper alone does not
provide exactly-once dispatch or make native BRS available.

The final acceptance must additionally compare complete source inventories before and
after, canonical tree and parent commits, all raw JUnit files and every durable
workspace/ledger/inode pin. A focused fixture pass cannot claim native runtime,
external worker authenticity, distributed ownership or production admission.
