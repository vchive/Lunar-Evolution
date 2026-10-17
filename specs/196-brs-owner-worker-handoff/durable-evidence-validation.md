# Durable recovery evidence validation

## Scope

Only local inert/provider-free fixtures are used. Four original-owner observations
and a captured native producer record binding do not settle an episode or consume
its reconcile obligation. Missing original native context remains unknown. The
native known-record tests deliberately double terminal/projection and OS probes;
they do not establish real runtime or solver-project acceptance.

The new focused CI gate covers the 91 distinct cases in:

- `tests/test_rsi_brs_native_process_evidence.py` (34)
- `tests/test_rsi_brs_mailbox_evidence.py` (35)
- `tests/test_rsi_brs_durable_recovery_evidence.py` (19)
- `tests/test_rsi_brs_durable_policy_dependencies.py` (3)

Coverage includes strict wire and separate digest domains, entry and inode drift,
PID/group uncertainty, no backfill or signals, original run/namespace locks,
atomic root/obligation/run/episode/claim checks, partial histories, read-only rebuilt
inspection, actual worker receipt observation, uncertain writes and readbacks,
and late cancellation, channel close or deadline before acknowledging a cursor.

## Final-source acceptance procedure

Freeze one clean Git source after integration and independent product review.
Run the same distinct inventory on macOS Python3.11.15 and 5090gpu Linux
Python3.12.3, using separate own-editable checkouts/venvs and disjoint groups.
The scoped inventory also includes the existing exact result, mailbox, owner,
native dispatch, registration, reconcile integrity and publication-recovery tests,
plus the regression runner/workflow contract tests. Collection is not execution.

Retain raw collection, JUnit, command exits, interpreter/import/editable identity,
commit/tree and actual tracked-file bytes checked against Git blobs before and
after each group. Require the same inventory with no failures, errors or skips,
plus Ruff, compileall and diff checks. Aggregate source and platform evidence only
after every group completes, then independently review the aggregate.

The final-source results and evidence directory are recorded in the PR after
completion; this document is the acceptance procedure, not a claim that the
pending run passed. Any failed attempt remains separately NOT_ACCEPTED.

Complete GitHub CI and prerequisite main merges remain separate gates. Public
native BRS, production admission and online publication remain disabled.

## First frozen attempt (not accepted)

`ef7ee90` macOS ran 561 cases: 560 passed and one old transport-only
fixture failed because its explicit observation seam double was missing. The
product correctly refused the fake owner. Three additional driver failures came
from splitting `::` inside a parameter ID. Preserve all raw results as
NOT_ACCEPTED; do not treat the corrected parser as changing those exit codes.
The follow-up changes the fixture and external JUnit-key parser only, preserving
product bytes. Its same-inventory final-source run is separate.
