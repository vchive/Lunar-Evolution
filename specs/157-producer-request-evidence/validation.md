# Validation

The optional native broker path was checked on a local loopback HTTP fixture with a
compiled isolated target. It sent one request through inherited anonymous descriptors;
the controller attached a host-only credential, journaled admission and completion, and
returned the response. The target saw no credential. A duplicate JSON key was rejected
before provider I/O, and a second request over the registered budget produced no second
provider call. The existing native attempt suite remains green.
If the protected journal cannot initialize, the native release gate stays closed and
the target never starts.

The terminal receipt remains `process_only` and `publication_eligible=false`. These tests
do not establish a recovery-safe broker receipt, complete Feature 156 lifecycle, scheduler
integration, external producer acceptance, or real-provider performance.

## 2026-10-01 formal receipt handoff

When the native stream, envelope, broker, deadline, target-binding, and cleanup evidence all
verify, Feature 156's formal `execution-receipt.json` records the broker coverage summary. A
provider-free publication regression supplies its digest to Feature 153 and confirms that the
publication journal preserves it; missing or invalid receipts are rejected before any stage
write. The process-only terminal remains diagnostic, and this handoff does not close the
recovery-safe transport or complete-egress requirements in T157-05/T157-06.
