# Private BRS rejection C1/P/C2 composition adapter

This slice freezes the narrow composition boundary for an owner-side all-rejected
continuation. It does not enable native BRS or change the worker mutation refusal.
The adapter is provider-free and only composes already-held objects:

1. **C1** reads `RSIPublicationLineage.rejection_provenance_binding()` from the
   original owner continuation. It requires the exact BRS owner, matching run,
   episode, journal, ledger, gateway, workspace and captured checkpoint head.
2. **P** calls the existing create-only
   `persist_native_rsi_rejection_provenance()` and reads it back through the
   returned mode-0400 file pin. The adapter never discovers or replaces an
   existing file and does not accept a worker supplied path or pin.
3. **C2** calls the existing
   `RSIPublicationLineage.acknowledge_rejection_provenance()` and verifies the
   owner readback with `rejection_provenance_file_pin()`.

The adapter refuses a foreign owner or lineage continuation, a stale/changed
head, ledger or journal, a published head, a missing original C1, provenance
already attached to the evidence, and any policy that enables `online_publication`
or `production_admission`. It returns only detached evidence and the original
C1 binding; it does not settle an episode, publish a candidate, promote memory,
refresh a head, retry an unknown result, or select another ordinal.

The BRS owner still needs a native online transaction bridge that retains its own
C1 descriptor before this adapter can be called in production. Requiring an
explicit separately-held original lineage continuation is intentional: this
slice cannot reconstruct DRS authority from a BRS checkpoint, mailbox response,
latest ledger row or a worker callback. Public native BRS and production
admission remain disabled.
