# Mixed integration: operation-local pure reparse reduction

The committed `09d23464` Linux three-child mixed attempt exhausted its original
600-second budget (600.031659438 seconds, process return code -15, zero retries).
Its 120 sparse stack samples identify repeated active history/binding validation;
they do not measure CPU share or prove a storage bottleneck. The attempt has no
terminal JUnit or module-origin report and must not be dispatched again.

This change reduces proven duplicate pure work. It does not change execution
budgets, retries, ordering, wire formats, admission authority or failure policy.

## History reference comparison

Extend the existing bounded, ledger-local, thread-local checkpoint projection.
A projection is still keyed by the complete freshly selected run ID, revision,
parent, original payload text and checkpoint digest. It may retain the complete
seven native-string admission columns only after the original full reference /
plan / journal comparison has succeeded for that exact checkpoint.

On a later visit within the same owner operation, SELECT every admission row
again and run the complete original row parser. Compare all seven raw columns.
Only a complete match from an exact immutable `sqlite3.Row` may reuse the earlier
pure reference comparison. Dictionary and foreign row backends keep the original
full matcher. A changed
row takes the full matcher; a missing or corrupt row preserves the original
refusal. Every history still decodes fresh payload JSON, checks the entire chain
and monotonic references, and returns detached mutable bodies. No parsed DTO or
caller-owned mapping is retained. Reuse remains subject to the existing original
helper-graph checks before and after the operation, entry/unit bounds and finally
cleanup. Different threads and later owner operations do not share projections.

## Parser-local runtime

A binding parser already strictly parses the runtime manifest from its JSON input.
Before exposing any result, it can reuse that fresh runtime for local assembly
when the original parser/helper/type/code seams remain unchanged and an exact,
callback-free structural observation still matches. Keep the original declared
shape and digest checks. Any unsupported type, changed seam or structural drift
uses the original public reparse path. Public constructors, serializers and
caller-owned DTO validation retain their complete mutation/refusal behavior.

The complete launch attestation, runtime/tree join, binding digest and canonical
wire comparison remain required. No filesystem observation is cached.

## Gates and regression

Do not combine gates across cancellation callbacks or remove later independent
fresh observations. Keep controller locks, physical file/inode observations,
SQL/JSON reads and terminal admission checks. Software fixture success cannot
supply installed root/account authority or immutable build/runtime custody.

Develop and independently review both changes before one affected focused union.
Cover retained-row mutation/deletion/corruption, all seven columns, changed fresh
reference bytes, helper drift, bounded retention and scope cleanup. Cover parser
round trips, public and nested DTO mutation, seam replacement and canonical /
digest refusals. Use behavior and original-call observations, not elapsed-time
assertions. A novel meaningful committed HEAD may receive its one original
600-second mixed dispatch after focused validation. Do not infer mixed success
from focused results. Full CI and the actual mixed gate must pass before merging.
`production_admission=false`; `online_publication=false`.


## Frozen affected regression

Tree `1093f1fdc02d92c05621e270fe63ccc86cc8a099`: one Linux invocation,
16 workers, zero retries, 32 complete files and the original one-selector
published/rejected two-child integration. The retained terminal reports
1,446 passed, zero failures/errors/skips in 297.395911978 seconds. All 29 new
runtime and 14 new history nodes executed. Source before/after matches all
3,016 archive entries; 2,708 Git file pins and 290 module origins match.
These provenance checks are not extra product tests or immutable build custody.
Independent terminal audit confirms unique collection/execution, all 16 worker
completions and the per-file/node outcomes above. Ruff, compileall and staged/unstaged diff
checks pass after two pre-freeze style-only if/with corrections. The final
commit may update Markdown records only relative to this tree. Mixed and full
CI remain separate gates; the original failed 09d23464 attempt remains failed.


## Committed mixed outcome and next narrow correction

The single Linux mixed execution on `672ce351` failed at the unchanged
600-second allowance: raw process 600.016517692 seconds, return code -15;
runner 600.266790694 seconds, outer dispatch 602.588094042 seconds. There
is no terminal JUnit, origin report or sampler completion. All 120 sparse
samples and matching before/after source inventories remain retained. The
independent audit confirms failure-evidence consistency, not test success.
This HEAD is consumed and must not be dispatched again or receive Darwin
fallback. The prior `09d23464` failure remains failed.

Source inspection identifies a separate concrete handoff omission. The native
provider already supplies an identity/control/deadline-only `wait_check` to
the terminal endpoint, but the endpoint supplies the full check to all three
stage ACK loops. Once callback state is `callback_returned`, each such full
check redoes the complete selected source/fingerprint gate. Sparse samples
are consistent with that path but do not measure its cost or prove that it
accounts for the full timeout.

Carry the existing optional wait check through delivery, callback-started and
callback-finished exchanges. Full checks must gate each stage entrance and
the acknowledged transition, outside the condition. Incomplete polls use the
original liveness/control/cancellation/deadline check, never a retained success
result. Recheck original primitive handles and ACK/failure state after checks.
For the opt-in path this includes the endpoint entry/post-response cold gates,
mailbox hot polls, and each stage cold/hot callback. Refuse a replaced exchange
or Condition before using it. Exceptional cleanup marks and wakes only the
original exchange under its captured original Condition; never enter a foreign
transport. Only a callback that actually began can produce a callback-finished
unknown observation; an earlier wait/gate failure stops without a new stage.
Do not combine gates across the callback; keep the final provider reobservation.
The new wait method participates in the explicit finite policy graph. A completed
cold policy also retains its function/code pin in that operation only; recheck
it before any warm policy return, require the original empty defaults/closure,
and refuse a missing or malformed pin. Compare before and after cold graph
construction so a changed helper cannot establish a pin for an older graph.
Scope cleanup drops both graph and pin. This adds no global authority cache
or repeated full graph build to idle polls.
A missing wait check keeps the original poll/call-order behavior. Failed checks,
failed exchange, expiry and callback exceptions must not permit subsequent
settlement or callbacks. No wire, deadline, retry, SQL/history, file, authority
or default production behavior changes.

Develop tests for each stage, delayed ACKs, original-handle drift, pre-stage
and post-ACK refusal, cancellation/timeout, callback failure and the default
path. Independently review before one affected union and the next meaningful
committed HEAD's single mixed run. Do not rerun the unaffected previous union.
A proposal to hoist per-row broad history helper guards remains analysis only;
it is not part of this correction.


## First terminal-wait focused outcome and retained failures

Frozen tree `890d3c47` executed once: 569 unique, 567 passed, two failed,
zero skips/errors in 115.568332827 seconds; no timeout or retry. All 53 new
ACK-wait and 43 policy nodes passed. Independent artifact review confirms
matching source before/after, exact archive/Git file modes, 285 module origins
and all 16 worker collections; two workers exited 1 without crashing. These
checks retain the failures and do not give the union passing credit.

The native completion fixture compared full stat results and rejected an atime
update caused by a read. Its replacement snapshot excludes atime only, keeping
original bytes and dev/inode/mode/nlink/uid/gid/size/mtime_ns/ctime_ns. The heavy
published-rejected setup encountered the expected original global-alias drift
when mixed with a different inert native fixture's process-wide policy. A
setup-only diagnostic identifies `_run_native_trusted_producer`'s
`run_native_trusted_attempt` alias precisely. Existing `tools/run_tests.py`
already requires a fresh pytest process for each heavy BRS wave. Restore that
scheduling for its affected supplement; do not reset or weaken production
policy state to accommodate fixture hooks. The ordinary affected union and
the original heavy selector use independent interpreters. The new committed
three-child mixed still gets only its original 600 seconds and zero retries.


## Final affected union after development freeze (2026-10-29)

Frozen tree `cf19f440383da3acaa128cc9db1cd1f88dedfe4f` passed the ordinary affected
12-file Linux union: 487/487, no failures/errors/skips, 79.679989151 seconds,
16 workers all exiting zero, zero retries. This includes helper-loader 47/47,
v4 stdio 47/47, original completion 27/27 and CI aggregation 82/82. The original
published-rejected selector ran separately under the existing fresh-interpreter
heavy rule: 1/1 passed, 223.475495526 seconds, one worker, zero retries/skips.
Both exact source archives share the same 3019-entry inventory and 2711 Git
blob/mode pins. Terminal source before/after, complete worker collections and
unique executions, JUnit node identities, 320/285 module origins and raw exits
were independently audited. The original 569-node failed union remains failed;
these are explicit affected supplements on changed source/scheduling.

No source guard was reset or relaxed to repair the scheduling failure. Only
published-file atime is excluded from the fixture snapshot; content, inode and
modification metadata remain strict. The earlier 1446-node unaffected union and
terminal ACK/policy 53/43-node passes remain retained without redundant reruns.
CI manifest is 83 groups, 65 zero-skip groups, expected sum 6888. Final changes
after this validation are status Markdown only. The meaningful committed HEAD
still needs its one original 600-second mixed and full CI; both older consumed
mixed HEAD failures remain retained and cannot be rerun or replaced by Darwin.

The old 672ce351 CI run 40726287750 is now terminal cancelled: 42 jobs cancelled
and three downstream aggregation jobs failed after cancelled/missing inputs.
This is not a passing result. Production admission and online publication remain
false. Complete accepted input/build/runtime/CLI, original fixed-U and finite
writer acquisitions, original accepting monitor join and installed root/account
acceptance remain unimplemented or unaccepted as recorded in their own specs.
