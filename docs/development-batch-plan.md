# 2026-10-27 parallel development batch

The user's current direction is to implement P0–P2 in separate slices, freeze one
integration source, and run full regression once. Historical notes saying all P2
work is deferred do not describe this batch. Local development remains the
default; production admission and online publication remain false.

| Priority | Slice | Files / boundary | Validation |
| --- | --- | --- | --- |
| P0 | Original mixed timeout and final release CI | Frozen PR189 source `2486a6dc`; retain failures and collect its natural terminal once | Original 600-second budget, no retry; failures keep release gate open |
| P1 | Pinned OpenEvolve source preparation | `tools/openevolve_fixed_profile/`; already committed `d5da3411` | Focused/source preparation accepted; full runtime/solver acceptance remains open |
| P1 | Pinned Shinka source preparation | `tools/shinka_fixed_profile/`, three new tests and Feature191 continuation | Combined focused run; real archive preparation; no upstream algorithm execution |
| P1 | Command-level build output dependencies | `tools/static_python_rsi_fixture/execution_backend.py`, independent v2 tests and Feature193 continuation | Real inert local helper; preserve v1 checks and limits |
| P2 A | Worker origin | `external_worker_origin.py`, its test and Feature197 spec/plan/tasks | Actual HMAC and strict parsing; no replay consumption or process authority |
| P2 B | Durable assignment and once-only settlement | `external_worker_assignment.py`, its test and Feature197 assignment contract | Actual local SQLite/HMAC, restart and unknown gates; no remote launch |

Authors only check syntax while parallel work is active. After freeze the root
runs one union of new and directly affected focused tests, then Ruff, compileall
and diff checks. Cross-review is read-only; corrections only repeat affected
checks. An integration commit receives full Linux CI after known blockers have
been addressed. A small commit or status-document update does not trigger another
full regression matrix. There are no test retries or relaxed acceptance budgets.

The source preparers do not supply accepted runtime images. The v2 execution
mechanism does not supply a reviewed complete CPython/Zig recipe. Worker origin
and assignment do not supply a remote transport, remote cleanup proof or actual
cross-host deployment acceptance. These are explicit remaining dependencies;
local fixtures must not be reported as finishing all P0–P2 work.
