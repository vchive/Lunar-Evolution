# Read-only controller child-context bridge

This slice joins one controller-owned DRS staging checkpoint to the existing Python
producer input resolver and native scheduler plan. It is an observation boundary only:
the caller must already own the controller lock and provide the exact checkpoint head.

The bridge checks the controller, ledger, producer stager, gateway and retained root
context, then reads the current checkpoint and requires a `ready` staged child for the
requested episode. It reuses `resolve_python_rsi_episode_input_context` to select the
child proof and construct a child `PythonRSISchedulerInputContext`. A temporary
`PythonProducerRSISolverGateway` is built from that context solely to recompute the
native scheduler plan; the plan must equal the staged plan. The temporary gateway is
never returned or run.

Before returning a ready preview, the bridge invokes the native scheduler's
`validate_preclaim` gate with the exact controller ledger. The gate rereads sealed native inputs
with the original deadline required to remain unexpired, checks the complete plan/request
binding, samples cancellation once, and rejects any existing native claim (including started or
unknown recovery state). It then repeats the input/plan/ledger and scheduler-context fingerprint
observations after the callback, so a callback that changes intent, broker headers, strategy,
hooks, or deadline cannot turn a stale preview into a dispatch. The gate is read-only: it never
creates or settles a claim, consumes an attestation, launches a process, or invokes a producer.

The bridge performs no claim, receipt, result, admission, publication, launch or
checkpoint write. `preparing`, `unknown`, BRS checkpoints, missing owner locks and
checkpoint/request/memory/root drift refuse. Ready dispatch remains refused by the
controller's existing stager; this bridge supplies evidence for a future explicit
dispatch slice and does not grant launch authority. The returned preview is an
observation artifact, not a dispatch context. Host-only broker headers are copied into
the read-only child context and their digest is part of the context identity; mutation
of the original context after preview creation is rejected on the next observation.
Execution strategy, cancellation control, ledger and handoff hooks remain controller-owned
and are intentionally not cloned or treated as authority. A future dispatch slice must
revalidate those hooks and their configuration under the controller's lock before use.
