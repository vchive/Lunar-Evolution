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
