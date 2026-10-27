# 2026-10-27 parallel development batch

## Current integration slice

The second parallel slice implements the remaining source-side work together.
Authors run syntax checks only; the root freezes it before one combined focused
regression. An actual configured static build still depends on the previously
blocked isolated environment. No source helper or inert transport fixture closes
that environment or production acceptance gate.

| Priority | Implemented source | Remaining acceptance |
| --- | --- | --- |
| P0 | Runtime ancestry projection and bounded own-stack v2 with truthful terminal states | New clean source's original 600-second mixed run, then full CI |
| P1 | Concrete CPython/Zig compiler, same-source freezer, deterministic archive/link recipe; explicit full-toolchain v3; fixed-solver frozen/native source closure | Reviewed target configuration, isolated real build, ELF/image, expanded installation/startup, solver/lifecycle and native production CLI |
| P2 | Fixed opt-in SSH transport, private installed wrapper/key, original request budget, create-only intent/result, append-only unknown reconciliation, explicit CLI and existing-only ledger opens | Unified local regression, actual inert cross-host SSH; untrusted-candidate isolation and remote cleanup stay separate |

P0's observed failure is a 600-second mixed-case deadline with an unknown attempt
receipt. Historical CPU and stack observations support investigating repeated
JSON/history/runtime validation cost; they do not establish deadlock or one
specific current-head hot function. The ancestry change is a candidate and does
not count as resolving the timeout before the new mixed case finishes. The old
failed source, limits and results are retained without retry or reinterpretation.

Source closure preparation is checked against retained official CPython and real
prepared solver bytes, without importing or executing them. Missing aliases and
interpreter-provided modules are resolved from actual source behavior. A missing
required import remains a refusal; synthetic tests cannot fill that gap. SQLite
has its own source provenance requirement, independent of the host library.

The optional SSH topology remains one local authoritative controller/SQLite
ledger with explicit worker commands. It adds no remote evaluator, HTTP service,
multiple-controller takeover or NFS database. HMAC authenticates the installed
worker's receipt; it does not grant native result or publication authority.

The first completed slice is retained below as history.

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
