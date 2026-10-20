# Local Python process adapter

This slice connects the immutable `PythonProducerBinding` and its independently
retained sidecar to the existing Feature190 native producer lifecycle. The public
entry point is `run_python_producer_process(...)`.

The adapter performs these checks in order:

1. Reparse the binding and reject a mutated DTO before any process call.
2. Read the create-only sidecar with its original file identity and binding digest.
3. Delegate execution to `run_producer_process`, which remains responsible for
   executable byte binding, one-time attestation consumption, owner registration,
   private gate release, FD/stream bounds, cancellation, deadline, reap and the
   unchanged native receipt wire.
4. Re-read the sidecar after the native call and reparse the returned receipt.
5. Compare run, journal, launch, intent, attestation, interpreter, and limit pins.

If the native process path raises after the sidecar was accepted, the adapter re-reads the
same retained sidecar before projecting a lifecycle error. A replaced or otherwise drifted
sidecar wins over the native failure and returns `binding_sidecar_invalid`. Stable native
failures retain bounded meanings: cancellation maps to `process_cancelled`, a wall deadline
maps to `process_deadline`, and cleanup uncertainty maps to `process_cleanup_unknown`. The
cleanup-uncertainty note has precedence over cancellation/deadline labels, because a missing
reap or FD-cleanup proof must remain fail-closed.

The function returns the native `ProducerExecutionReceipt`. A process receipt alone
does not create a known Python terminal: runtime timestamps, source identity and an
independent broker request journal still need a runtime observation. It also does
not enable evaluator admission, publication, online publication or production mode.
Recovery remains read-only through `recover_python_producer_terminal` and
`recover_producer_process`; the adapter never retries or repairs an uncertain run.

Focused tests cover sidecar-before/after ordering, sidecar loss before launch, native receipt
identity drift, fixed failure projection and cleanup-note precedence. Real sealed CPython runtime and project lifecycle
acceptance remain separate Feature189/193 and P1 acceptance gates.
