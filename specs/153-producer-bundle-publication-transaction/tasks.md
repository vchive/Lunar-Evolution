# Tasks

- [x] T153-01 Define the canonical batch journal and receipt state machine.
- [x] T153-02 Add plan/archive-prefix/workspace preflight and deterministic candidate IDs.
- [x] T153-03 Implement staged all-or-nothing publication with a durable recovery marker.
- [x] T153-04 Implement exact-match resume and terminal unknown-publication rejection.
- [x] T153-05 Add provider-free focused regression and static validation.
- [ ] T153-06 Add non-publishing native draft execution/evaluation under journal-derived IDs and
      the shared deadline. Bind each retained run to its batch and keep it at the original native
      `bundle-attempts` path; do not allocate a sequential ID or write the final archive/state.
      Implemented: planned-ID draft execution, immutable prepared intent, exact retained-evidence
      retry and unchanged live archive/state before commit. Still open: shared transaction
      deadline enforcement and its recovery cases.
- [x] T153-06a Prepare native records/receipts for planned final source paths and extend staging
      to verify the complete retained run evidence without copying or rewriting path/inode
      bindings. Derive active state from frozen population state and adjudications.
      Bounded to an initialized iteration-zero running population with no offspring history,
      seed admission, or prior producer admission.
- [ ] T153-06b Validate the controlled two-file path, evidence tampering, mixed/all-rejected and
      unknown results, interruption and shared-deadline recovery, then archive-integrity,
      population-restoration and delivery read-back before offline regression.
      Covered: native two-file draft execution, retained-evidence tampering, offline Shinka SQLite
      import with mixed/all-rejected results, exact pre-stage retry and changed-intent rejection,
      archive/population read-back, population resume, and existing delivery API verification.
      Still open: full unknown/interruption recovery, shared-deadline cases and durable terminal
      journaling for all-rejected batches.
- [ ] T153-07 Connect launcher/scheduler and run separate real OpenEvolve and ShinkaEvolve
      campaigns after the draft-to-publication path and request boundary are accepted.
