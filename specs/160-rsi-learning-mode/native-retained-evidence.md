# Native retained candidate evidence

Feature 160 continuation, 2026-10-02. This is an opt-in local evidence reader, extending the
native lifecycle/publication contracts in Features 156/157. It does not implement a solver launch.

## Problem and scope

The native scheduler can already retain a formal producer execution receipt, strict output,
independently evaluated bundles and an exact published population transaction. RSI currently
has fixture native adapters but no typed interface to those retained materials.

The native launch intent does **not** pin an RSI episode, memory snapshot or complete
`SolverRequest`. Binding a supplied RSI request after execution cannot prove that the producer
used that request or memory. Therefore this slice returns candidate evidence, never a
`SolverResult`, and implements no `SolverGateway.run` method. Source admission and new RSI
launch attribution remain separate work.

## Interface and authority

`read_native_retained_candidate(workspace, *, candidate_id, expected_journal_sha256,
expected_producer_execution_receipt_sha256, ...existing native recovery pins...)` returns an
immutable `NativeRetainedCandidateEvidence` for exactly the caller-selected candidate.

- Require the original launch intent, one-shot attestation, bootstrap artifact, algorithm
  contract, bundle groups and evaluator/runner/dependency/environment pins. Use strict native
  recovery to validate retained execution, stream, broker, cleanup and output evidence.
- Require the exact terminal `journal.published.json` digest and its link to the expected formal
  producer execution receipt. Prepared, failed, unknown, partial and all-rejected records cannot
  yield evidence. Never select another candidate or infer the current best candidate.
- Reuse read-only publication recovery, read-only archive integrity validation and verified
  portable bundle material reads. The selected archive candidate must match the published
  candidate slot, lineage, bundle and receipt identities. Check retained publication again after
  collecting materials so evidence drift cannot be accepted as a partial success.
- Missing workspaces and evidence fail closed; the reader does not create directories,
  databases, lock files, receipts or publications. It never starts a process, opens transport,
  evaluates a candidate, consumes an attestation or changes a budget.

The authority is the trusted local retained evidence and existing native integrity contracts.
This is not remote worker authentication, a filesystem snapshot lease or historical rollback
protection. Concurrent evidence changes must cause rejection; existing immutable local evidence
is still assumed.

## Digest meanings

Keep these identities distinct in the DTO and documentation:

| Field | Original authority |
| --- | --- |
| `source_bundle_sha256` | Candidate bundle manifest digest |
| `entrypoint_source_sha256` | Raw entrypoint bytes digest |
| Native dependency digest | Original launch/publication dependency pin, not an Actor dependency manifest |
| Producer execution receipt | Formal native producer execution receipt digest |
| Candidate execution receipt | Producer-bundle execution receipt digest |
| Candidate completion digest | Candidate runtime completion digest |
| Candidate evaluation receipt | Producer-bundle evaluation receipt digest |
| Candidate evaluation digest | Independently retained candidate evaluation digest |
| Candidate publication receipt | Archive candidate receipt digest |

Portable materials retain verified path/bytes pairs in immutable tuples. Any report/metadata
projection is copied/canonicalized rather than exposing archive dictionaries by reference. Native
scores remain provenance; this DTO cannot approve RSI memory or bypass independent verification.

## Validation

Use only the existing local native bootstrap/C target/loopback broker fixture. Verify an actual
published candidate yields the original digest chain and complete portable bytes; repeated reads
leave all retained files and inodes unchanged, with launch/transport/evaluation/publication
functions blocked. Reject wrong expected digests, changed pins, absent/unpublished/partial
records, candidate substitution, symlinks and source/receipt/evaluation drift. Retain original
failures and run focused pytest, Ruff, compileall and branch diff checks.

This closes only the retained-evidence access slice. Real native-to-RSI launch binding, official
evaluator acceptance, external ownership and real OpenEvolve/Shinka campaigns remain open.

Focused validation: 38 tests passed, zero failed/errors/skips, 39.794 seconds, report
`/tmp/lunar-rsi-native-reader-final-20261002.xml`. Cases include real published/prepared/
all-rejected batches, hash-valid unknown refusal, original pin and artifact drift, no-op repeated
reads, candidate substitution, detached material corruption and an evaluator mutation after
material copy that the final recovery rejects. Focused Ruff, compileall and diff checks pass.
