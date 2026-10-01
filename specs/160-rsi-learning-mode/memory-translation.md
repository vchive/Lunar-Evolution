# Explicit cross-solver memory translation

## Scope and contract

This opt-in local extension implements the narrow C1 translation boundary from the stage report.
It does not select a translator, infer solver compatibility, invoke a model, or update governance.

`SolverMemoryMapping` declares a mapping ID, source/target solver IDs and fingerprints,
source/target contract digests, and the exact target condition, action and applicability. The
source solver and contract must already occur in an approved, passing source MemoryItem.
The source and target solver IDs must differ. The mapping is explicit configuration supplied by
the caller, not evidence that the target solver implements these semantics.

`translate_memory(source_snapshot, source_memory_id, mapping, expected_source_receipt_sha256,
candidate_id)` freezes the actual source item, source snapshot digest, source verifier receipt,
episode, complete causal fields and mapping. The observed result remains an observation from the
source episode; no target success is invented. The resulting receipt carries a candidate projection
with only the declared target solver/contract, `active_eligible=false`, and required fresh
`verified` and `holdout` gates. Its `draft_memory_item()` is unresolved and cannot enter an approved
MemorySnapshot. Translation is not a verifier receipt for the target solver.

Canonical serialization retains all provenance and has a bounded size. `recover_translation`
rebuilds the projection from the supplied frozen source snapshot and mapping and requires exact
equality with the caller's retained `expected_receipt_sha256`. It is a read-only, no-callback replay.
Source receipt, snapshot, mapping,
candidate identity or target compatibility drift is rejected. Receipt hashes provide consistency,
not authenticity; the caller must obtain source provenance from its trusted ledger.

## Implementation and validation

Files: `rsi_memory_translation.py`, `test_rsi_memory_translation.py`.

- Happy path preserves causal observations and produces an unresolved target-only draft.
- Unknown solver/contract, failed/unresolved source, wrong receipt or same-solver mapping rejects.
- Legacy source wire fields remain intact while derived causal fields remain explicit.
- Frozen receipt replay is deterministic and causes no mutation or evaluator execution.
- Changed source/mapping, receipt tampering, extra fields, duplicate keys and noncanonical bytes
  fail closed; caller mutation of returned projections cannot change the receipt.

Run focused tests, Ruff, compileall and diff checks. No controller, automatic retrieval or
promotion path is altered. Real solver-specific translators still require explicit mappings and
independent target verification/holdout before governance activation.

## Local validation result

The implementation and 19 focused translation tests pass. Focused Ruff, compileall and
`git diff --check` pass. Tests exercise only immutable local fixtures and canonical receipt bytes.
