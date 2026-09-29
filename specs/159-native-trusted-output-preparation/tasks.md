# Tasks

- [x] T159-01 Add read-only preparation requiring a recovered successful native process terminal.
- [x] T159-02 Verify bounded stable envelope bytes, authority pins and declared request ceiling.
- [x] T159-03 Reuse explicit multi-file verification, draft projection and admission planning.
- [x] T159-04 Cover positive, incomplete process, duplicate key, over-budget, symlink, race and
  changed-source cases with provider-free tests.
- [ ] T159-05 Integrate contemporaneous output capture and durable receipt under the original
  native attempt deadline, then join host-observed request coverage before publication. The
  capture/receipt and broker-journal binding slices are implemented; full egress coverage and
  publication admission remain open.
- [x] T159-06 Persist and recover a create-only native preparation receipt binding successful
  terminal, same-attempt capture, complete brokered-request journal, explicit source groups,
  native drafts and admission-plan digest; reject evidence drift and retain
  `publication_eligible=false` until complete egress and publication/delivery gates exist.
- [x] T159-07 Add a restricted `offline_import` bridge that requires an explicit one-shot,
  token-bound authority and rechecks launch, attestation, terminal, capture, broker, preparation,
  source-group and admission-plan bindings before invoking Feature 153. Consume the authority
  only after a published or all-rejected terminal; transaction failure and replay remain fail-closed.
- [ ] T159-08 Complete production egress authority, cross-process unknown reconciliation, automatic
  parent delivery, and real OpenEvolve/Shinka launcher acceptance. The offline bridge does not
  satisfy these production requirements.
