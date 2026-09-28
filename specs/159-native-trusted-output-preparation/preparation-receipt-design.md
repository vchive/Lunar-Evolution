# Native trusted preparation receipt

This slice persists the read-only handoff between Feature 159 output preparation and the future
Feature 153 publication transaction. It requires the same-attempt native process terminal, output
capture, and a complete controller-owned broker journal whose admitted count matches the producer
declaration. The receipt binds launch IDs, attestation, terminal/capture digests, explicit bundle
groups, native drafts, and the exact admission-plan digest.

The receipt is create-only, canonical, bounded, and reread with no-follow stable reads. A retry
must reproduce identical terminal, capture, source, broker, grouping, draft, and admission-plan
evidence. Recovery never launches a producer, consumes another attestation, executes an evaluator,
or publishes a candidate. Source, capture, broker, contract, launch, grouping, and receipt drift
fail closed.

`publication_eligible` remains `false`; the receipt records blockers
`complete_egress_authority`, `publication_transaction`, and `delivery_verification`. Brokered
request accounting is deliberately reported as `brokered_requests_only`; it is not upgraded to
complete host egress authority. Feature 153 integration may consume this immutable preparation
only after those independent authority gates are satisfied.

## API

`persist_native_trusted_preparation(...)` creates or exactly reuses
`evolution/producer-batches/<journal>/native-trusted-preparation.json`.

`recover_native_trusted_preparation(..., expected_receipt_sha256=...)` reopens and reconstructs the
same preparation using the original launch, attestation, executable artifact, contract, and
explicit groups. The expected receipt digest is mandatory and is never synthesized from current
files.

The provider-free tests cover broker incompleteness, changed source/capture/journal/contract,
receipt tampering, symlink replacement, exclusive-write interruption, exact retry, and the absence
of Feature 153 archive or candidate writes.
