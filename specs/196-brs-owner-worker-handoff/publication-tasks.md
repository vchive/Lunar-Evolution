# Feature 196 — owner publication task split (draft)

This task split is subordinate to `publication-boundary.md`. It is a planning
artifact only; no item below is complete until its code, focused tests, static
checks and independent review are recorded. Keep the existing private checkpoint
settlement task separate from this publication work.

## P1 implementation slices

| ID | Owner boundary | Deliverable | Required refusal/side-effect proof |
| --- | --- | --- | --- |
| PB-01 | Authority facade | Private owner-only publication entry point consuming the exact selected return receipt, handoff and original prepared reference | Worker thread, missing owner scope, foreign lease, wrong episode, mode drift and public `_drive_brs` calls refuse before lock/I/O; archive, state, checkpoint and budget remain byte-identical |
| PB-02 | C1 capture/CAS | Capture `H_before`, before archive/state pins, source/configuration and budget/deadline under the original owner lease; CAS the prepared execution into the owner checkpoint | Stale controller head, changed payload, source/sidecar/workspace/inode drift, owner-thread drift and duplicate C1 refuse; no latest-head adoption or second reservation |
| PB-03 | P transaction bridge | Invoke the existing Feature 153 owner publication transaction with the exact original plan/journal/anchor and C1 expected head | Worker cannot invoke staging/commit; plan/journal/receipt/attempt/deadline drift refuses before first final move; lock order is owner then publication |
| PB-04 | C2 terminal/read-back | Verify terminal journal, manifest, candidate trees, archive/state and native receipt, then CAS C2 against C1 and `H_after` | CAS/read-back mismatch leaves C1 and durable P evidence intact, owner head stale, no rollback/repair/retry/sibling; successful C2 is idempotent only through exact terminal inspection |
| PB-05 | Unknown/recovery gate | Map deadline, cancellation, owner exit, channel close, unknown marker and partial move to existing durable recovery states | Unknown and missing C2 block successor dispatch; read-only inspection requires original pins and never launches evaluator/producer or adopts current files |
| PB-06 | Serial ordinal transition | Create a fresh handoff against C2's verified head while preserving original wave reservation and M0 | Next ordinal cannot start before C2; prior prepared/receipt/journal cannot be copied; stale sibling publication is rejected |
| PB-07 | Success/rejection policy composition | Route completed success and known rejection through existing owner memory/result policy | Worker never promotes memory; rejection does not advance published head or create success evidence; C1/P/C2 associations remain distinct |

## P1 verification and release slices

| ID | Deliverable | Exit condition |
| --- | --- | --- |
| PB-08 | Focused owner/worker publication matrix | All PB-01..07 cases pass with exact disjoint inventory, no provider/network/process campaign, zero F/E/skip |
| PB-09 | Static and compatibility gate | Ruff over `src tests tools`, compileall and `git diff --check`; existing DRS, admission, settlement and public native-refusal suites pass |
| PB-10 | Independent source/evidence review | Reviewer checks source hash, installed import origin, raw XML, exit chain, archive/state/inode pins and that public native BRS remains refusal-only |
| PB-11 | Documentation/status update | Update Feature196 task/validation/HANDOFF only with observed counters and source hash; keep publication status open until PB-10 |

## Deferred P2 work

- Multiple native children or concurrent publication in one wave.
- External worker authentication, remote transport and multi-machine ownership.
- Public native BRS enablement, production CLI and scheduler integration.
- Sealed runtime/toolchain, real OpenEvolve/Shinka campaigns and remote/company
evaluators.
- New persistence schema, automatic repair/retry or latest-head adoption.

Any deferred item requires its own SDD and acceptance rather than being inferred from
this in-process owner boundary.
