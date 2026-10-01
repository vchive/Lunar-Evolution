# Implementation plan

1. Define bounded journal, candidate receipt, and terminal-state DTOs with strict canonical JSON
   parsing and a journal digest.
2. Derive deterministic candidate identities from the Feature 152 plan without changing the
   existing `CandidateDraft` identity rules.
3. Add a read-only preflight that compares plan, run/task identity, full archive/state prefix,
   existing candidate source/record/receipt integrity, workspace, population configuration,
   island mapping, authority pins, and the effective budget profile before opening a publication
   transaction. Any failure must be zero-write.
4. Implement a private staging tree and one recovery marker for all candidate source trees,
   sidecars, archive lines, and state updates; publish only after every receipt is verified.
5. Add fail-closed resume and unknown-publication handling. Keep the legacy seed publisher and
   automatic solve entry points untouched.
6. Add focused provider-free transaction, tamper, crash-boundary, and no-provider tests, then run
   the normal static and regression gates.
7. Add a non-publishing native evaluation path for each Feature 152 draft using its
   journal-derived ID and frozen lineage. Keep final candidate trees and live archive/state
   unchanged while retaining each batch-bound execution run at its original
   `evolution/bundle-attempts/.bundle-run-<24-hex>` path. The current native evidence parser
   requires this path shape. Reuse native source materialization, runner, independent evaluator,
   and original monotonic deadline; do not call `next_id()` or destination archive `persist()`.
8. Inspect each original native run and prepare the final canonical record/receipt for its
   planned ID without publishing it. Extend staging and manifest verification to bind the full
   retained source, plan/admission, workspace/input, attempt/completion/cleanup and evaluation
   evidence. Keep the execution-time evidence tree in place; copying it and rewriting its
   path/inode/digest bindings would not preserve proof of the observed execution.
9. Derive the admitted subset and `state_after` from the frozen population state and every
   adjudication. Under the publication lock, verify the original prefix and complete evidence,
   then stage and commit. Reopen the committed archive for native integrity validation,
   population restoration, and delivery; a transaction marker alone is insufficient.
10. Validate in order: one controlled two-file execution with unchanged destination archive;
    evidence-complete staging with tamper/foreign-path negatives; offline two-candidate and
    mixed/all-rejected/unknown publication with read-back; interruption, shared-deadline,
    cancellation and commit-fault recovery; focused and full offline regressions. Only then
    connect OpenEvolve and ShinkaEvolve launcher output and run separately registered real-project
    acceptance. A local fixture remains supporting evidence, not real producer acceptance.
