# Feature 191 — Python scheduler pre-staged inputs

## Bounded slice

This slice joins one already-retained Python producer binding to one already-prepared
native RSI request and memory snapshot. It is a read-only preflight and plan factory
for one episode. It does not launch a process, stage files, consume an attestation,
claim an episode, charge a budget, write a journal, or create a post-execution handoff.
`production_admission` remains false and only inert local fixtures are permitted.

The caller supplies a `NativeRSISchedulerContext`, the independently retained
`PythonProducerBindingSidecar`, and the independently retained
`PythonProducerCheckpointBinding`. The checkpoint is never reconstructed from the
current sidecar. The validator re-reads the native `.rsi-input` request/memory and
launch manifest through `validate_native_rsi_launch_inputs`, then reads the Python
sidecar through its pinned no-follow reader. Every run/journal/parent/task, contract,
evaluator, environment, deadline, intent, attestation, interpreter/runtime manifest,
tree and request identity must agree across the two domains. A Python binding cannot
be paired with a native request from another episode, and a native request cannot be
upgraded to a Python admission by a matching filename alone.

## Interfaces

`PythonRSISchedulerInputContext` is immutable and contains the native scheduler context,
Python sidecar, and retained checkpoint. `validate_python_rsi_scheduler_inputs(context,
request, memory, require_unexpired=False)` returns the existing
`NativeRSIInputDescriptor` after a complete cross-domain read-only check. The
`require_unexpired` switch is false for historical plan inspection and true only for a
future fresh dispatch gate; it never refreshes a deadline.

`PythonRSISchedulerPlanFactory(context)` is a pure callable that validates the retained
inputs and builds an existing `NativeRSIExecutionPlan`. Its fingerprint is stable for
the immutable binding, input manifest and plan selector and excludes current time,
mutable controller state, counters, caches and filesystem metadata not already pinned.
The gateway plan factory remains pure and read-only; claim/launch/provider calls stay
behind the existing native scheduler and controller gates.

The validator performs a second exact read of sidecar, native inputs and runtime before
returning. Replacement, mode/link/inode/symlink, missing-file, marker, request, memory,
runtime, intent, attestation, deadline, contract, evaluator or episode drift refuses
with a fixed code. The independently retained sidecar/runtime and the native request/memory
records also retain original timestamps, so their touch drift refuses. The existing native
manifest and launch record self-bind bytes/device/inode without an independent original
timestamp; a touch completed before observation remains accepted. This slice does not invent
that missing proof or change the native wire. Double observations are not an atomic snapshot
against a concurrent writer. It does not repair evidence or synchronize latest state. Legacy
non-Python native inputs retain their existing behavior and are not routed through this
module.

Exact DTO and plain-collection shape gates run before serializers or file readers. The
original checkpoint's caller-owned exact dict is copied into an internally owned immutable
pin; foreign mapping proxies cannot establish that plain-data property. Opaque strategy,
broker, cancellation and ledger objects are excluded from plan material and are never compared
or invoked. Changes to caller request/memory or retained context during reads refuse. The
fingerprint explicitly commits to the input join and its named parser/native-plan/runtime
observer dependencies; it does not claim general dependency discovery or remote authenticity.

## Non-goals and follow-up

This does not implement post-execution Python runtime observations, handoff publication,
full process interruption recovery, Feature 189/190 sealed runtime acceptance, CLI
production wiring, OpenEvolve/Shinka campaign execution, authentication, multi-host
ownership, service scheduling or remote evaluation. Those remain separate P0/P1/P2
features and cannot be claimed complete from this input join.
