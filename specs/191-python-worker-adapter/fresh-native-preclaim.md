# Fresh native gateway preclaim

The native gateway must call a receipt provider's explicit `validate_preclaim`
hook before acquiring a fresh native episode claim. The hook receives the original
request, plan and exact claim ledger. A missing hook or an explicit `None` preserves
the existing injected receipt-provider protocol; other non-callable values refuse
rather than bypassing validation. Hook attribute resolution is itself a read-only
observation boundary and cannot silently replace the execution configuration.

The gateway retains its execution configuration, stable wiring fingerprint and hook
identity across the read-only validation boundary. Hook failure, ledger replacement
or configuration/hook drift leaves the episode unclaimed and never invokes the receipt
provider. The hook uses the ledger's read-only observation scope; actual claim creation
remains the existing create-only SQLite operation after successful validation.

The scheduler's preclaim hook preserves legacy native contexts that were constructed
without a failure ledger. For that path only, it accepts the gateway's exact
`RSILedger` and retains a local path/device/inode comparison pin for this invocation.
It checks that pin before and after each claim observation and before returning,
using non-creating, query-only SQLite reads. It never adds the ledger to the context,
provider fingerprint or durable failure authority. The gateway's original lifetime
ledger pin continues to govern the actual claim.

Contexts already bound to a failure ledger continue to require that exact object
and the original constructor pin, including when another `RSILedger` names the same
database. Dropping that binding cannot enter the legacy path. Adding or replacing
the context, binding or constructor pin during observation refuses. Python producer
configs still require their native context to carry the exact controller ledger;
this compatibility branch does not relax child admission.

Existing started claims keep the recovery refusal, and terminal claims keep read-only
replay. Neither path calls the fresh preclaim hook. A concurrent claim acquired after
validation is handled by the original atomic claim/replay protocol, without a second
provider execution. No child execution continuation, process launch, attestation
consumption or production CLI admission is added by this slice.

Focused validation covers ordering, refused hooks, drift, attempted observation-time
writes, concurrent started/terminal claims and existing replay/recovery compatibility.
All fixtures are local and inert; `production_admission=false` remains unchanged.
Additional inert compatibility tests cover the original unbound gateway hook,
exact ledger typing, foreign bound objects, context/constructor-pin drift, inode
replacement at both callback boundaries and database removal immediately before
SQLite open. Query-only reads may create SQLite WAL/shared-memory bookkeeping;
the tests verify the database identity/bytes and absence of native claim/result or
producer-directory mutation, not absence of SQLite auxiliary files.
