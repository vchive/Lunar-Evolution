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

The function returns the native `ProducerExecutionReceipt`. A process receipt alone
does not create a known Python terminal: runtime timestamps, source identity and an
independent broker request journal still need a runtime observation. It also does
not enable evaluator admission, publication, online publication or production mode.
Recovery remains read-only through `recover_python_producer_terminal` and
`recover_producer_process`; the adapter never retries or repairs an uncertain run.

Focused tests cover sidecar-before/after ordering, sidecar loss before launch and
native receipt identity drift. Real sealed CPython runtime and project lifecycle
acceptance remain separate Feature189/193 and P1 acceptance gates.
