# Feature 196 — publication validation matrix

Only local provider-free/inert fixtures are allowed. Keep public native BRS and
production admission closed. Matrices below separate the bounded implemented
refusal from future online owner bridge acceptance.

## PB-01 focused refusal and compatibility

| ID | Scenario | Required assertion |
| --- | --- | --- |
| RF-01 | Named worker helper called directly, in DRS owner scope or unscoped thread | Same fixed `rsi_python_publication_brs_worker_publication_forbidden`; no input parsing, callback, ready, transaction, ledger/workspace write. |
| RF-02 | Actual selected BRS worker before prepared ACK calls named/generic/DRS mutation facade | Fixed refusal occurs before `_plan_snapshot`, `_capture_admission`, native transaction, `_python_admission_inputs` or ready request; SQL/files and gateway count unchanged. |
| RF-03 | Actual selected worker after retained ACK/durable result calls those facades | Existing refs cannot bypass ownership; same zero-effect refusal. Original service completes its sole ACK/result and sibling stays unstarted. |
| RF-04 | Active worker supplies callback-bearing admission plan | Serializer/attribute callbacks remain zero; fixed refusal precedes caller DTO observation. |
| RF-05 | Named helper gets expired/cancelled control and caller guard | Neither control nor caller guard sampled; fixed refusal leaves original files/rows unchanged. |
| RF-06 | Import compatibility | Named symbol and `__all__` remain; original call signature retained. |
| RF-07 | DRS/direct generic and read-only recovery | Existing publication/admission owner suites remain exact; no read-only resume gate added. |
| RF-08 | Scheduler separate direct route | Original live scheduler BRS worker refuses before direct transaction; pin-only ready/ACK remains permitted. Separate integration ownership/evidence. |

The actual selected fixture uses the existing service/channel, original wave, real
running/result/terminal ledger records and inert gateway. It does not manufacture
success publication. This gate closes no owner bridge task.

## Future PB-02/PB-03 owner bridge acceptance (not implemented)

| ID | Boundary | Required assertion |
| --- | --- | --- |
| OB-01 | Online prepared lifetime | Owner acts while original worker/running episode/started claim remain live; no completed-return or fabricated DRS scope. |
| OB-02 | Success before/prepared | Original owner captures before snapshots and acknowledgment with exact checkpoint CAS/read-back; no latest adoption or extra reservation. |
| OB-03 | Success staged/precommit | Existing manifest/after pins retained before first move; stale checkpoint/prefix/inode/source/control refuses under original lock order. |
| OB-04 | Success terminal | Existing native commit/read-back and owner terminal CAS match exact selected result; only then published head advances. |
| OB-05 | Rejection C1/P/C2 | C1 binds original all-rejected native terminal; P is original create-only provenance; C2 retains its publishing-FD pin; no published head/memory advance. |
| OB-06 | Callback/thread refusal | Worker/nested callback cannot acquire lineage authority, mutate checkpoint or publish; source hooks/waits outside observation mutex; arbitrary worker DTO callbacks remain zero. |
| OB-07 | Unknown boundaries | Partial native evidence, missing before/staged/terminal, C1 without P, orphan P without C2, durable unknown marker or post-write read-back drift preserves original obligation/stale capture; no retry/repair/sibling. |
| OB-08 | Recovery | Exact historical request/memory/claim/pins only; read-only inspection cannot mint owner, acknowledgment or execution authority. |
| OB-09 | Serial successor | Next ordinal uses fresh handoff and verified head after original terminal/result; original M0/reservation retained; duplicate prior nonce/journal/claim/receipt refuses. |
| OB-10 | Public/default compatibility | Existing public native BRS refusal and DRS/single-child canonical bytes stay unchanged. |

## Evidence

Focused runs must retain source/install/import identity, exact inventory, raw JUnit,
all exit records, static argv/cwd/logs and source before/after hashes. Do not add
counters from different source hashes into one acceptance claim.

Required current slice checks include `test_rsi_python_brs_publication.py`, existing
`test_rsi_python_publication.py`, `test_rsi_python_admission_owner.py`, and selected
service/checkpoint regressions, plus Ruff over `src tests tools`, compileall and
`git diff --check`. Final-source CI and independent evidence review remain separate.

No current run result is recorded yet. Future OB cases are requirements, not test
or runtime completion claims.
