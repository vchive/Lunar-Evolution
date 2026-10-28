# Owner-operation checkpoint projections

## Evidence and boundary

The retained a8a7003 mixed attempt timed out at 600 seconds. In its 40 main-thread
samples between 400 and 596 seconds, nine include the checkpoint-history walker;
27 include reserved-history observation. These samples identify repeated work,
not CPU percentages or proof that one optimization will finish the campaign.
Filesystem observations remain required and are outside this change.

The earlier admission-state projection removes one duplicate historical decode
inside one admission call. It does not remove the repeated complete reference
shape/canonical/context work across checkpoint reads in a single owner operation.

## Pure projection

Retain a bounded immutable per-row projection containing only the calculated
checkpoint digest and `(episode ID, canonical reference bytes)` pairs. Its key
includes run ID and all four freshly selected SQL columns: revision, parent,
complete payload text and stored checkpoint digest. Only exact native column
types admit reuse; equal lengths, Python numeric equality or a head alone are
insufficient. A miss uses the original reference parser and digest path.

Even a hit decodes the current payload with the original C-backed JSON decoder
for the returned mutable body. No cached dictionary, plan or journal DTO is
returned or retained. The optimization skips repeated *pure* historical shape,
canonical encoding and context construction for identical bytes and unchanged
helpers. It does not retain a successful live-validation result.

Every read still performs its SQL SELECT, checks each ordinal/parent/digest and
reference monotonicity, and performs the original final admission-row SELECT,
full row parse and complete reference/plan/journal binding. On a projection hit,
the final matcher reparses the fresh body's references without cached DTO
contexts. Every filesystem and ownership observation remains in place.

## Lifetime and fallback

Use ledger-local thread-local storage only inside one existing owner full-gate
operation or its bounded terminal join. Do not enter the scope for a complete
wave or generic service tick. Nested scopes share the outer cache; `finally`
discards it on success, error or cancellation. Later operations and other
threads start without those projections.

Bound entry count and conservative retained units, including complete raw keys,
canonical byte strings and container overhead. Oversized inputs use the old
path. Decoder, canonical, reference/DTO parser, projection helper and alias drift
disable reuse; owner policies also retain the new helper graph. No deadline,
retry, error code, durable wire or success-authority change is intended.

## Validation

Compare scoped and original results; observe original function calls without
replacing them to verify reduced historical pure work and fresh final parsing.
Exercise all four raw columns, exact column types, mapping rows, monotonic
references, changed/missing admission rows, helper drift, mutable returned-body
detachment, nested scopes, exception cleanup, other threads and retention
bounds. Existing history-reference, admission-observation, digest-cache and
owner-policy suites remain required. Defer pytest to one joined regression;
run static checks after implementation. No new mixed or remote evaluation is
authorized by this design alone.
