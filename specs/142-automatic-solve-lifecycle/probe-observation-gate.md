# Snapshot probe observation gate

## Scope

Continue the existing snapshot-probe acceptance contract. A matching report and a
runner's successful result cannot establish a passed probe without the independent
exit and process-release observations. This change adds no provider call, campaign,
registration, runtime discovery or production admission.

## Successful evidence

The existing `AcceptanceSnapshotEvidence` wire stays unchanged. `passed=true` and
`cleanup=verified` require all of the following:

- the authoritative report projection matches the frozen expectation;
- exactly one source observation contains exact `bytes`, whose digest is retained;
- exactly one runner result has exact string status `succeeded`, exact integer exit
  zero and no failure reason;
- exactly one independent exit observation is an exact integer matching that exit;
- exactly one observed process and one release have the same identity. PID is an
  exact positive integer; PGID is either `None` or an exact positive integer.

Missing, repeated, malformed or conflicting result/source/exit observations return
the existing `process_failed` classification. Missing, repeated or inconsistent
process identities return `cleanup_unknown`. Neither case verifies cleanup.
Projection mismatch, cancellation, timeout and observed cleanup failures retain
their existing precedence and classifications.

Keep the first result and harness digest for inspection. Later callbacks cannot
overwrite failed evidence with success. Counts saturate at two, and identity/exit
collections retain at most two entries, sufficient to detect repetition without
unbounded callback accumulation. Type checks precede equality with foreign values.

## Validation

Detached callback fixtures exercise the complete positive chain, optional PGID,
missing/duplicate observations, boolean/float/string exits, contradictory exits,
invalid process identities, malformed source and callback-bearing foreign values.
They create no process or workspace. Existing local snapshot and holdout suites
verify ordinary callback compatibility. This regression does not create a new real
acceptance outcome or change historical campaign evidence.
