# Build failure retention

## Scope and defect

This continuation changes only the pinned execution backend's failure evidence.
It does not complete the CPython/static-runtime acceptance gates or add a
controller sink, retry, budget extension or execution authority.

Currently any `workspace.mkdir()` `OSError` becomes `workspace_not_fresh`, even
when the filesystem reported `ENOSPC` or `EDQUOT`. Also a terminal `report.json`
write failure replaces an earlier command, deadline or I/O failure with
`report_write_failed`. Both lose the cause of the failed attempt.

## Contract

1. Only an existing workspace (`FileExistsError`) is `workspace_not_fresh`.
   Other workspace-creation `OSError`s become `workspace_io_failure`, carry a
   detached partial in-memory report, and never write into the unclaimed path.
2. Workspace, attempt and native-command I/O failures preserve a bounded
   `failure_detail`: the active stage (or null before stages), command index
   (or null), finite operation name and numeric `errno` (or null when absent).
   Exception messages, filesystem paths and ambient environment are excluded.
   The original fixed reason codes for attempt/command failures are retained.
3. `BuildExecutionReport` gains optional `failure_detail` and
   `persistence_error` fields. Their nested values are immutable and detached.
   A failed report wire includes `failure_detail` only when one exists; the
   successful report wire, API arguments and all acceptance flags are unchanged.
4. A failed terminal write preserves the original reason and failure detail,
   completed stages and partial command evidence. Its own `report.write`
   operation and `errno` are separately carried in `persistence_error` on the
   in-memory report. When commands succeeded and persistence alone fails,
   `report_write_failed` and partial status retain the existing behavior.
   No second report write, alternative output path or implicit retry occurs.
5. Shared deadline, direct-child cleanup and `cleanup_unknown` semantics remain
   unchanged. Retaining an earlier I/O detail does not turn unknown cleanup into
   success. All installation, runtime and production-admission claims stay false.

## Validation

Add local fault-injection tests for `ENOSPC` and `EDQUOT` workspace creation;
snapshot/attempt and command I/O with stage/operation/errno; command or deadline
failure combined with a terminal write failure; failure-only persistence; and
immutable detached error evidence. Existing fresh-workspace refusal, successful
report shape, cancellation, shared deadline and unknown-cleanup tests remain
required. No real CPython, model, solver, evaluator or external service is run.

Implementation is followed by one static check batch. Focused tests are deferred
to the root's combined P0–P2 regression rather than run per edit.
