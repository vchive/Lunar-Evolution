# Local batch validation — 2026-10-27

The root ran twelve new/directly affected test files together: the three Shinka
source-profile files and existing handoff, both build-executor files, origin and
assignment, existing worker evidence/process evidence, native claims and callback
journal. Actual HMAC, local SQLite and the inert C helper run; no upstream solver,
model request, remote evaluator or remote worker runs.

The original run has **364 passed / 2 failed / 0 error / 0 skipped** in 366 cases.
Both failures were the new synthetic inventory-limit test: repeating full records
exceeded the independent recipe byte limit before reaching the count gate. The
test now supplies a bounded list of null records, reaching the intended count
gate before any record validation. Product limits and refusal order are unchanged.
Style fixes affect assignment tests, Shinka snapshot fixture imports and the
source-tool package initializer. Only the affected selection was rechecked:
**96 passed**, no failures/errors/skips. The two reports cover **366 unique cases**,
all latest outcomes pass; they must not be added as 462 unique cases. The original
failure report and log remain retained.

Final repository Ruff, compileall over src/tools/tests and git diff checks pass.
The first Ruff report identified style issues, all corrected before the final
check. Original pytest also warned while automatically attempting cleanup of old
shared pytest garbage; the affected recheck uses a fresh explicit basetemp. This
task performs no manual cleanup or permission changes to those old directories.

Staging exposed one extra EOF newline in the new Shinka entrypoint asset; the
unstaged diff check had not included this untracked file. Remove exactly that
newline, verify identical AST, and update its pin to 20,091 bytes /
`b42fe9f7876888784332ec9605e332a043db4ec6be380a5dd0a87ed901cdfeb9`.
The three affected Shinka files alone were rechecked: **91 passed**. All three
reports still cover 366 distinct cases. Final staged diff checks include all new
files; source checks must not rely only on the unstaged diff.

The retained Shinka archive was prepared once per asset version by its actual
CLI, preserving both output trees. The final 13 files include ten Python modules,
both notices and manifest:
`5a6e716142cf71d944adbc7e1622cb1a147f7ef9eaba556e9bb1f707680ecffa`.
The earlier manifest `bfede29438cc227fc25f149e7df952a0d7ef365351328950b42983dd94ac9be3`
is retained only for the preceding asset version. Neither preparation executes
upstream algorithms or accepts a sealed runtime.

Local evidence is retained in the primary workspace ignored directory:
`.lunar-evolution/validation/parallel-batch-20261027/source-integration-rqp65_iv/`.
`focused.xml` SHA is
`2b74e9a861fb52d55aec513c74d4374c9dbaf0855d794c1bd12bc48beab71718`;
`affected-recheck.xml` SHA is
`8610b762eec609642c14f8a27e5d767f08efd6b6f855187c52e72e4649f56f7b`.
`shinka-final-recheck.xml` SHA is
`9b7848c0fd4114631947ea56d453f70a8e5c1bfc6820c4f94dbd5faab2fb952f`.

Cross-review found no blocker within the authored source/assignment boundaries.
Tests cover crash/reopen, exact receipt bytes, unknown and replay fencing, original
locks/checkpoints/claims and alternate namespace refusal. They do not establish
simultaneous remote-controller deployment, secret provisioning, remote cleanup,
full runtime/build closure or production CLI acceptance. Those tasks stay open.
P0 PR189 CI remains failed on the separate original mixed timeout; this local
batch does not close it. Full integration CI is deferred until the known blocker
has an actual source correction, avoiding another known-failing matrix.
