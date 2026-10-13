# Single-episode Python producer gateway

## Scope and existing authority

`PythonProducerRSISolverGateway` is an explicit experimental Python API for one
already staged OpenEvolve or Shinka episode. It composes the existing
`PythonRSISchedulerPlanFactory`, `NativeRSISchedulerProvider` and
`NativeRSISolverGateway`. It adds no process owner, claims, receipt schema,
controller checkpoint, admission row or unknown recovery policy.

The caller supplies `PythonProducerRSIExecutionConfig(producer_id, ledger,
inputs)`, where `inputs` is the existing `PythonRSISchedulerInputContext` with
the original sidecar/checkpoint and native launch context. The producer label
must match both the original binding and launch intent; it does not authenticate
the project or its source. Failure handling must use this exact controller ledger,
and an explicit post-execution Python handoff supplier is mandatory. There is no
host interpreter discovery, dynamic factory import, staging or launch in the
constructor or fingerprint path.

## Execution and recovery

Before claim acquisition, the original gateway checks the complete request and
memory, input files, runtime tree, binding proof, plan and ledger identity. The
facade additionally freezes the existing plan and scheduler fingerprint
projections, rejects changed wiring, and requires request solver identity to
match the original producer. `run(request, memory)` then uses the original native
durable claim and scheduler. The post-execution supplier, durable prepared
notification and DRS/BRS admission bridge stay at their existing late boundary.

Explicit `bind_python_admission_controller(controller)` requires this gateway,
ledger, original sidecar checkpoint and workspace. The scheduler keeps the
existing one-way controller binding and active owner-scope gate. Binding has no
execution effect. A fresh `run` inspects its original plan/claim and requires this
binding before acquiring any new claim, repeating the exact proof/workspace check.
Started-claim refusal and terminal replay remain available without a live controller.

Started claims continue to refuse relaunch. `validate_replay`, `inspect_failure`
and `restore_failure` retain their native signatures and read the original
retained evidence. Missing or conflicting observations cannot become success.
All production claims stay false; supplied inert evidence is mechanism validation,
not sealed CPython or real project acceptance.

## CLI selection

`rsi run` and `rsi resume` accept `--solver-execution fixture|native-producer`.
The default and explicit fixture path preserve existing results and fingerprints.
Native selection currently fails with the fixed
`rsi_python_producer_gateway_cli_accepted_runtime_required` error before contract,
home, ledger or fixture access. It cannot silently downgrade to a fixture. There
is no launch-config loader or callback/module selector in this CLI.

## Remaining SDD work

This facade binds one pre-staged request/memory/launch/batch. A later DRS/BRS
episode changes those inputs, so one context cannot drive a complete campaign.
Production CLI development still requires a separately specified per-episode
launch/staging boundary and durable original producer proof association. It must
not stage inside the pure plan factory, adopt a later checkpoint or reuse the
previous episode's attestation. Accepted source/toolchain/image/runtime evidence,
actual upstream project lifecycle/export, and Linux runtime acceptance remain
open. `production_admission=false` throughout this slice.

## Local validation

Focused inert tests exercise composition and controller binding, bidirectional
producer mismatch, original request/memory and wiring drift, original claims after
scheduler interruption, restarted refusal, completed retained replay, and CLI
pre-I/O refusal with unchanged fixture behavior. The scheduler launch boundary is
stubbed before process creation; no real solver, model or evaluator is called.
