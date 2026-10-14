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

Existing started claims keep the recovery refusal, and terminal claims keep read-only
replay. Neither path calls the fresh preclaim hook. A concurrent claim acquired after
validation is handled by the original atomic claim/replay protocol, without a second
provider execution. No child execution continuation, process launch, attestation
consumption or production CLI admission is added by this slice.

Focused validation covers ordering, refused hooks, drift, attempted observation-time
writes, concurrent started/terminal claims and existing replay/recovery compatibility.
All fixtures are local and inert; `production_admission=false` remains unchanged.
