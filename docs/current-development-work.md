# Current development work

## 2026-10-09 current head

PR24 now contains the Feature189 pure static-runtime preparation and Feature191
Phase A/C local contracts: `PythonProducerBinding` validates the existing
runtime/tree, launch intent, one-time attestation and RSI deadline without I/O;
`python_producer_lifecycle.py` projects existing process receipts into an
immutable terminal view and keeps missing process/cleanup/request evidence in
`unknown` until a read-only reconcile. Focused binding, terminal, runtime-tree,
launcher and process tests pass. No CPython build/startup, host-runtime
substitution, external producer, model or evaluator campaign has run.

PR25 adds Feature192's bounded Linux kernel-global route deny contract and a
dedicated 11-case CI gate. PR24/25 Linux acceptance and merge are still
pending. Feature191 lifecycle spawn, real runtime observations, loader-negative
fixture and OpenEvolve/Shinka process adapters remain open.

As of 2026-10-08, PR15–22 are merged into main after independent final-source
Linux CI/raw audits. Feature188 / PR22 sourcec5973a7/tree61d6f966 passed final
run37747759152: three versions, 22 phases, material274/0 skips and current11984/92
platform skips, zero failure/error/retry. Root verified original ZIP/XML/log/
inventory/source/checkout-tree evidence; merge4f8576d has the identical tested
source tree and expected parents. The first failed mmap-fixture run37747268959
remains separate evidence. Main21 push37744640126 independently passed all21
phases (current11710/92). Main22 push37754528167 independently passed all22
phases (current11984/92, material274/0); its raw evidence and verifier report
are persisted under `.lunar-evolution/reports/persisted-ci-evidence-20261008/`.
Feature190 now fixes controller-owned executable handles as a prerequisite for
Feature189's static CPython fixture. Its first final CI run failed only in two
3.11 `select()`-based native bootstrap test helpers when the runner assigned
FDs above `FD_SETSIZE`; production code and dedicated133/material274 gates
passed. The helper now uses bounded `poll()` and a replacement run is pending.
Feature189 has bounded pure ELF/descriptor inspectors plus an offline recipe
and asset emitter; no toolchain, source archive, image build or CPython launch
has occurred.
The entries below describe current capability gaps;
older feature documents retain their historical submission state.

| Priority | Work | Completion evidence |
| --- | --- | --- |
| P0 | Independent native guardian, including bootstrap death/pause and exact child cleanup (Feature 183 / PR18) | Completed: PR18 raw run37724953798; main merge8f3377f |
| P0 | POSIX message queue syscall control and formal admission gate (Feature 185 / PR19) | Completed: PR19 raw run37725907868; main merge22394d26 |
| P0 | Fixed producer broker HTTP destination (Feature 186) | Completed: PR20 raw run37732579777; main mergec6faf365 |
| P0 | Native keyring syscall control (Feature187) | Completed: PR21 raw run37738544048; main merge518f1f4 |
| P0 | Bounded kernel-global routes (Feature192 / PR25) | Completed: three-version raw run37820105103; main mergee341010, tested treeb06470f. This is a bounded deny contract, not complete Linux containment |
| P1 | Framed immutable runtime material (Feature188) | Completed: PR22 raw run37747759152; main merge4f8576d. All runtime-load/production claims remain false |
| P0 | Original executable ownership and cleanup (Feature190) | Implementation complete; replacement final Linux CI is pending after the high-FD test-helper fix |
| P1 | Python archive/import/loader closure and immutable runtime loading | Feature189 preparation adds bounded pure ELF/descriptor gates and an offline pinned recipe; actual source patches, Linux build, startup and native acceptance remain open |
| P1 | Versioned runtime delivery and formal Python worker admission | Feature191 Phase A binding and Phase C terminal/reconcile gates are implemented; actual launch/runtime observation/admission remain open |
| P1 | OpenEvolve/Shinka Python process adapters | Existing native composition/export paths remain untrusted provenance; common Python process adapter and local inert fixture remain open |
| P1 | Production RSI CLI composition | Wire only admitted workers through durable controller resume, unknown/drift/budget gates and retained provenance; verify a repeatable local end-to-end entry |
| P2 | Multi-host ownership, service operation and distributed scheduling | Deferred by current user scope; these are not prerequisites for the current local fixture work |

The real CPython pipe fixture on main demonstrates startup, SDK exchange and
native lifecycle composition using explicitly trusted host runtime roots. It
does not supply production runtime immutability or general Python admission.

Current verification is restricted to local inert C/Python/filesystem/pipe/socket/
loopback/provider-free fixtures and GitHub CI. No model, WebAgent, remote/company
evaluator or actual solver campaign is run; environment credentials are not read.
