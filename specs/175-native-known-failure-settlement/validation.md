# Validation

Status: not yet run for Feature 175. PR #9 validation is prior-feature evidence only.

Required: real local inert C exit7 and accepted-start cancellation; current terminal-v1 with
consumption-v2 deadline chain; exact native read-only recovery; original broker closed read with
complete=false live stop; active/timed-out/missing pin refusal. Unknown handshake is accepted only
under the verified formal cancellation exception. Cross-boot, legacy unanchored consumption,
missing terminal, unclean cleanup, stream/deadline/file drift must refuse.

Provenance: strict schema, no-follow/hardlink/mode/bounded canonical reads, original publishing FD,
create-only identical replay, replacement/valid-rehash drift and dual sidecar refusal.
Gateway/controller: same ledger inode/original created_at claim, no saved-only failure replay,
immutable unknown conflict, stale CAS, historical memory, original fingerprints and one reconciliation
reservation across result/episode/checkpoint crashes. Expired dispatch evidence registration grants
no new dispatch budget. Assert no launch/evaluator/transport/signal/promotion on restore.

Run appropriate focused suites after changes, Ruff src/tests/tools, compileall and git diff --check.
Final exact head must independently pass the existing Ubuntu Python 3.11/3.12/3.13 current/archive/
frozen and early native suites. Retain first failure artifacts; do not retry current failures or
borrow results from earlier PRs. Darwin platform skips do not establish Linux enforcement.

## Local final evidence

Five-module known-failure suite:153 passed,0skips/failure/error,50.675s;
`/tmp/lunar175-known-final-v1.xml`. This covers actual C exit7 and accepted-start cancellation,
DRS/BRS, immutable failure publication/restart, four crash boundaries, expired dispatch evidence
registration, original claim timestamp and file/ledger/checkpoint drift. Existing success and
controller/scheduler/producer composition:179 passed,0skips/failure/error;
`/tmp/lunar175-composition-final.xml`. A native/legacy composition247 passed and B composition95
passed plus final pin46 passed overlap these suites and cannot be added. Full Ruff src/tests/tools,
compileall and git diff check passed. Independent A/B review closed original publishing digest
loss, checkpoint pins/root identity and reader callback CAS windows. Final source requires its own
complete three-version CI and merge; no prior feature's CI is reused.

Earlier local XML is preserved: B new-fixture error and old success read-only atime-only snapshot
failures; root empty-BRS, missing test import and lock-required fixture mistakes. They were
corrected before final focused validation. Read-only preservation snapshots retain bytes, inode,
mode, nlink, size, mtime and ctime; normal read atime is excluded. No production deadline,
compiler strictness, schema, safety assertion or platform skip was weakened.

Final transaction/CAS refinement:162 passed,0skip/failure/error;
`/tmp/lunar175-known-final-v2.xml` =157 known-failure cases +5 existing claim cases. Adds actual
SQLite claim timestamp mutation immediately before result transaction and reader-driven
checkpoint/episode drift after budget reservation but before result publication. Both refuse
without result creation, retaining already-appended competing evidence. Existing ledger/native
gateway/controller/durable flow transaction composition:100 passed,0skip/failure/error;
`/tmp/lunar175-transaction-composition.xml`. Counts overlap earlier suites. Independent third
review reproduced old CAS failure effects and verified new refusal leaves result absent.
