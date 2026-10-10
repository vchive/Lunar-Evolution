# G1 source provenance comparator

`compare_source_provenance` compares a caller-retained canonical receipt with a
single detached `StaticPythonSourceTreeObservation`. It only proves that the
receipt and the complete original regular-file source-tree projection agree.
It does not acquire source, open a path, authenticate a release signature,
apply patches, build, launch, or grant runtime or production admission.

The caller supplies independent lowercase SHA-256 pins for the receipt,
extraction manifest, and source-tree wire. Cheap pin checks run before receipt
parsing or observation traversal. The receipt is bounded to 256 KiB, uses
exact keys and duplicate-free canonical UTF-8 JSON, and contains the complete
source-tree regular-file list. Unknown metadata, noncanonical bytes, digest or
file-list drift, and unknown status values are fixed refusals.

Only a fixed-profile observation is accepted: `profile_pin_verified` must be
true and `metadata_validation` must be exactly `validated`. Inert snapshots
(`skipped-inert-profile` or unknown status) are refused and can never be
upgraded by a receipt. `signature_verification` remains exactly
`not-performed`; this comparator does not claim signatures. The comparator
recomputes the source-tree canonical digest and total bytes from the frozen
observation DTO before comparing every receipt field.

The returned frozen DTO contains detached file dictionaries and canonical JSON.
Its `profile_pin_verified` field records the fixed-profile observation state; it
does not authorize a build, executable owner, runtime, evaluator, or production
admission. No filesystem, network, subprocess, compiler, or model operation is
performed.
