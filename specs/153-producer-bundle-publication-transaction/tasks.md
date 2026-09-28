# Tasks

- [x] T153-01 Define the canonical batch journal and receipt state machine.
- [x] T153-02 Add plan/archive-prefix/workspace preflight and deterministic candidate IDs.
- [x] T153-03 Implement staged all-or-nothing publication with a durable recovery marker.
- [x] T153-04 Implement exact-match resume and terminal unknown-publication rejection.
- [x] T153-05 Add provider-free focused regression and static validation.
- [x] T153-06 Add non-publishing native draft execution/evaluation under journal-derived IDs and
      the shared deadline. Bind each retained run to its batch and keep it at the original native
      `bundle-attempts` path; do not allocate a sequential ID or write the final archive/state.
      Implemented: planned-ID draft execution, immutable prepared intent, exact retained-evidence
      retry and unchanged live archive/state before commit. Caller-owned active deadline,
      bounded lock waits, stage-boundary cancellation and actual policy pins are implemented.
      Added: same-boot durable deadline restoration and in-process polling of parent cancellation
      during candidate/evaluator execution, retaining stop and cleanup evidence without publication.
- [x] T153-06a Prepare native records/receipts for planned final source paths and extend staging
      to verify the complete retained run evidence without copying or rewriting path/inode
      bindings. Derive active state from frozen population state and adjudications.
      Bounded to an initialized iteration-zero running population with no offspring history,
      seed admission. Repeated producer admission is now supported in this same window with
      strict prior-event schema/provenance checks and fresh candidate/bundle identifiers.
- [ ] T153-06b Validate the controlled two-file path, evidence tampering, mixed/all-rejected and
      unknown results, interruption and shared-deadline recovery, then archive-integrity,
      population-restoration and delivery read-back before offline regression.
      Covered: native two-file draft execution, retained-evidence tampering, offline Shinka SQLite
      import with mixed/all-rejected results, exact pre-stage retry and changed-intent rejection,
      archive/population read-back, population resume, and existing delivery API verification.
      Added: durable all-rejected terminal receipts, exact no-evaluation retry, receipt/identity
      tampering rejection, budget downgrade rejection, deadline/cancellation before commit and
      successful completion after entering the commit critical region.
      Added: same-boot subprocess budget restoration and active-stop non-publication regression.
      Still open: full unknown/interruption reconciliation across process restart.
- [x] T153-06c Persist and independently inspect native all-rejected terminal batches without
      publishing candidates; rebuild portable receipts from retained original evidence.
- [x] T153-06d Compose caller-owned active execution controls with tighter parent controls,
      pin the actual policy, and preserve typed cancellation/timeout across publication locks.
- [x] T153-06e Persist and restore the original boot-scoped monotonic deadline; reject fresh-clock
      allowance resets, replaced injected clock objects and missing/changed retained clock records.
- [x] T153-06f Poll active candidate/evaluator subprocesses for cancellation/deadline, terminate
      the owned process group and retain interruption/cleanup evidence before propagating the stop.
- [x] T153-06g Append repeated producer batches to an iteration-zero running population;
      preserve prior archive bytes and candidate files, revalidate producer provenance, reject
      identifier collisions before execution, and append exactly one admission event. Validate
      bounded population/delivery read-back, all-rejected no-change, unknown no-replay and
      pre-stage retry with retained completed execution/evaluation evidence.
- [ ] T153-07 Connect launcher/scheduler and run separate real OpenEvolve and ShinkaEvolve
      campaigns after the draft-to-publication path and request boundary are accepted.
