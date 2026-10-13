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

The bridge performs no claim, receipt, result, admission, publication, launch or
checkpoint write. `preparing`, `unknown`, BRS checkpoints, missing owner locks and
checkpoint/request/memory/root drift refuse. Ready dispatch remains refused by the
controller's existing stager; this bridge supplies evidence for a future explicit
dispatch slice and does not grant launch authority.

