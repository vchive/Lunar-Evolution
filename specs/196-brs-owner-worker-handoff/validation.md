# Feature 196 validation plan

This feature has no implementation or passing runtime evidence yet. The following
matrix is the minimum provider-free test plan for the later implementation. Tests
must use local ledger, thread, channel, CAS and file fixtures; no network, process
campaign, WebAgent, remote evaluator or company platform is allowed.

| ID | Scenario | Required assertion |
| --- | --- | --- |
| H01 | Fresh handoff shape | Exact run/wave/episode/ordinal, M0, request, owner, head, source and policy pins are accepted; mutable or path-only substitutes are refused. |
| H02 | Policy and worker count | `max_workers=1` and fresh BRS policy are required; `max_workers>1`, old DRS, mode upgrade and policy drift refuse before I/O. |
| H03 | Owner lock boundary | Worker and nested callback never acquire the controller, lineage or checkpoint owner; owner-only CAS remains the sole mutation path. |
| H04 | Ready/ack meaning | Valid ready pins only the exact admission reference and returns its digest; it cannot launch, evaluate, publish, promote memory or settle C1/P/C2. |
| H05 | Queue while ordinal waits | Owner services a queued ready request while an earlier future runs without holding a wait lock; no deadlock at `max_workers=1`. |
| H06 | Head/state drift | Changed head, payload, state, controller, ledger, workspace, sidecar, thread or source fingerprint refuses and preserves durable evidence. |
| H07 | Duplicate/foreign request | Replayed, wrong-wave, wrong-episode, sibling, nested, recovered or foreign-thread handoff is rejected; no second admission reference is created. |
| H08 | Ack failure / owner exit | Durable pin survives ack failure; close wakes workers before executor shutdown; no rollback, synthetic ack or missing-row repair occurs. |
| H09 | Deadline/cancel/unknown | Deadline, cancellation and unknown close the selected handoff, preserve budgets/evidence and do not auto-retry or dispatch a sibling. |
| H10 | Serial head continuity | After a completed or rejected child, the next ordinal gets a fresh handoff against the new head while all requests remain bound to M0 and the original reservation. |
| H11 | Partial-wave resume | Completed child references remain in the wave scope; only the missing selected ordinal may receive a fresh handoff; terminal resume is read-only. |
| H12 | Mixed publication | Success/rejection follows existing v2 owner CAS and C1/P/C2 rules; worker cannot publish or promote memory and rejected result never advances memory. |

Focused commands after implementation:

```bash
PYTHONPATH=src pytest -q \
  tests/test_rsi_python_brs_admission.py \
  tests/test_rsi_python_brs_owner.py \
  tests/test_rsi_python_brs_publication.py \
  tests/test_rsi_python_brs_recovery.py \
  tests/test_rsi_python_brs_handoff.py
ruff check src/lunar_evolution tests/test_rsi_python_brs_*.py
python -m compileall -q src tests
 git diff --check
```

The final acceptance must additionally compare complete source inventories before and
after, canonical tree and parent commits, all raw JUnit files and every durable
workspace/ledger/inode pin. A focused fixture pass cannot claim native runtime,
external worker authenticity, distributed ownership or production admission.
