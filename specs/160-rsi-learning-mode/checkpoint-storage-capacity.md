# Checkpoint storage capacity

## Scope and observed defect

The reserved BRS raw reader limits each complete SQL row to 128 KiB. Staging
previously budgeted compact UTF-8 state bytes while the checkpoint writer stored
JSON with extra spaces and ASCII escapes. It also omitted SQL row metadata.
A three-child mixed run naturally terminated with failure in finalization and refused
controller-journal revision 32 with the existing reserved capacity error. Its
temporary database was removed by the fixture; no exact overflow byte count is
claimed from that run.

## Contract

- New controller checkpoints use the same compact UTF-8 JSON as their existing
  semantic digest. Old spaced/escaped payloads retain their original bytes and
  remain readable through the existing decode and hash-chain validation.
- Reserved checkpoint and run-record writes measure the actual pending complete
  SQL row, including original identifiers, revision, parent, digest and timestamp,
  using the existing raw reader's meter before INSERT. An over-cap append raises
  `rsi_controller_checkpoint_capacity_exceeded` and leaves original rows and
  checkpoint heads unchanged.
- The complete row cap stays 128 KiB; aggregate bytes, row count and all fresh
  raw reads remain unchanged. Generic checkpoints keep their existing wider
  payload contract. No persisted row is rewritten or grandfathered past a cap.
- New reserved staging reservations deduct the metadata for a subsequent row:
  192 bytes plus the original UTF-8 run ID. Integer storage is always eight bytes
  in the existing meter; parent and checkpoint digests reserve 64 bytes each.
  Historical state validation keeps its original payload bound. These future
  reservations do not manufacture existing rows or observations.
- Before memory publication, finalization projects each known non-governed
  commit, committed and terminal checkpoint from the original scheduling results
  and memory rules. It also reserves terminal run metadata, including the bounded
  32-byte UTC timestamp. It starts from the fresh original revision/head and
  computes only prospective hashes; no memory or checkpoint is written.
- A governed admission outcome and its budget changes are not knowable in
  advance. The next deterministic candidate/pending-generation row is checked
  before candidate publication, and this preflight repeats after each actual
  settlement. Actual writes continue to apply the exact complete-row guard.
  The preflight cannot authorize an unknown admission outcome. It does not make
  unknown governed admission/budget side effects atomic with a later capacity
  refusal; that remains an explicit limitation of this bounded repair.

## Validation

Focused tests cover complete rows one byte below, at and above the cap; initial
and subsequent revisions; long IDs and multibyte UTF-8; compact-vs-default JSON
inflation; refusal before append with unchanged head and SQL rows; legacy raw
text/digest compatibility; and the generic wider payload contract. Deterministic
finalization tests prove known growth refuses before a memory callback, while
successful planning checks commit/committed/terminal rows without mutating state.

The original oversized raw-row refusal tests remain applicable. Centralized
regression must cover both checkpoint append paths, staging preflight, reserved
policy drift, ordinary finalization and governed finalization. The earlier mixed
failure is retained as failed evidence; it is not reclassified as a pass.
