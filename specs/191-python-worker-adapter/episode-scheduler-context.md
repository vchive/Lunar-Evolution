# Read-only episode scheduler context

This slice composes the retained DRS child proof with the existing
`PythonRSISchedulerInputContext`. It neither stages nor dispatches a child. The
stager continues to reject ready dispatch, and every result has
`production_admission=false`.

The caller supplies the independently pinned root context, the exact RSI ledger,
the episode request and approved memory, and a mandatory controller checkpoint
SHA256. Pure existing context/request shape gates precede ledger or file reads.
The ledger resolver selects the ready child under that checkpoint. The resolver
keeps the root separately, checks the original root sidecar and runtime, and
requires the child to retain the root runtime, deadline, limits and launch
template except the existing episode/launch/input fields. It builds the child
context by replacing only native intent and attestation, then reuses the existing
Python/native input and plan validators.

All database reads use the non-creating observation scope. Before returning, the
same checkpoint and root/child proofs are reread; a newer checkpoint is a fixed
conflict, not authority to refresh this operation. Missing, preparing, unknown,
swapped request/memory, file pin drift or changed root context refuses. No claim,
attestation consumption, budget update, receipt, publication or recovery write is
performed. Execution hooks on the original native context are retained but never
called by this resolver.

Focused local inert tests cover canonical child selection, root preservation,
checkpoint/request/memory drift, original file pin drift and no execution/state
effects. Real runtime, gateway/provider child routing and complete DRS/BRS remain
separate work.
