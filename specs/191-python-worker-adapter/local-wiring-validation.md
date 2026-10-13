# Integrated local scheduler and producer export validation

This continuation joins `late-prepared-scheduler-join.md` and
`local-python-producer-export.md` on the same source. It also fixes the existing
DRS bridge return contract: the real owning controller returns an exact canonical
`RSIPythonAdmissionRecord`, while BRS returns the acknowledged record digest.
The bridge validates the DRS record's bounded callback-free shape, canonical
digest and run/episode/journal/native-plan/prepared/anchor identity before extracting
the digest. Historical string hooks retain their behavior. No controller return
wire or durable checkpoint schema changes.

## Final local results

Python 3.13.12 passes 348 distinct cases with zero failures, errors or skips:

- Scheduler/bridge: 164 cases across the two new join suites, the real local
  DRS/BRS owner/transaction composition suite and the five existing
  scheduler/outcome/prepared/bridge suites. JUnit:
  `/private/tmp/lunar-integrated-scheduler-final-20261013.xml`.
- Export: 184 cases across the new source reader and the four existing
  adapter/binding-export/OpenEvolve/Shinka suites. JUnit:
  `/private/tmp/lunar-integrated-export-final-20261013.xml`.

Both selections ran concurrently in the final integrated worktree with explicit
`PYTHONPATH=src` and separate pytest base directories. The JUnit inventories have
no overlapping case keys. Whole `src/tests/tools` Ruff, compileall and
`git diff --check` pass. Prior probe/bridge evidence remains retained under its
own earlier source; repeated or overlapping cases are not added to this count.

The actual local composition tests use the original ledger/controller CAS, retained
handoff/prepared/anchor files, publication transaction and BRS ready/ack channel.
Only the native process stages and evaluator boundary are inert. Both DRS and BRS
acknowledge the first record before evaluation; removing that row after acknowledgement
prevents evaluation and leaves the durable checkpoint obligation intact. Replaying a
valid foreign record or callback-bearing nested record fails closed.

The initial composition run exposed the DRS return mismatch, plus a test assertion
that incorrectly attempted to read a checkpoint after deliberately removing its
required admission row. Their first XML remains
`/private/tmp/lunar-root-scheduler-join-20261013.xml`; the intermediate four-case
repair and 44-case bridge results remain separate. The final 348-case source and
oracles supersede them for local acceptance without erasing the first failures.

## Outstanding acceptance

The final integrated PR87 source still needs the complete Ubuntu Python
3.11/3.12/3.13 matrix and independent raw/XML/source/import/tree audit before merge.
Older PR87 results do not approve this revision. A later main push has separate
integration status; cancelled or superseded jobs are never counted as successful.

No real sealed CPython/toolchain, project campaign, model, WebAgent or remote
evaluator ran. The local exporter neither invokes an evaluator nor creates an
export directory. Real source/build/startup, authoritative Python RSI inputs,
runtime/process/owner/FD recovery and production CLI/Linux acceptance remain in
`docs/current-release-backlog.md`. `production_admission=false`; P2 stays deferred.
