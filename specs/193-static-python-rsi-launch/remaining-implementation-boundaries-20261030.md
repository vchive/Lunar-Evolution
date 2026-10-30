# Remaining implementation boundaries (2026-10-30)

This note records the current Feature 193 integration boundary. It does not add a
new feature, runner, account manager, configuration DTO or admission mechanism.
The current code and `HANDOFF.md` remain the implementation record. The native
support-export successor is a build-input step; its export, hashes and fixture
results do not establish an accepted Python runtime or production RSI launch.

## Accepted runtime and first scheduler context

The missing integration is a fixed loader that acquires the **first**
`PythonRSISchedulerInputContext` from the actual accepted static image and its
original, still-live runtime owner, then connects that context to the CLI.
Existing staging, scheduler, gateway and recovery code should be reused:

| Existing module | Reusable implementation |
| --- | --- |
| `rsi_producer_launch.py` | `PythonProducerEpisodeStagingConfig` and `PythonProducerEpisodeStager`: durable preparing/ready state, original root proof, deterministic child identities, once-only permit, create-only inputs/sidecar, CAS and unknown handling |
| `rsi_python_episode_inputs.py` | `resolve_python_rsi_episode_input_context` and `resolve_reserved_python_rsi_episode_input_context` |
| `rsi_producer_gateway.py` | `PythonProducerRSIExecutionConfig`, `PythonProducerRSISolverGateway`, `resolve_python_producer_episode_gateway` and `resolve_reserved_python_producer_episode_gateway`; original root, approved memory and checkpoint bindings remain in force |
| `rsi_python_scheduler_inputs.py` | `PythonRSISchedulerInputContext`, `validate_python_rsi_scheduler_inputs` and `PythonRSISchedulerPlanFactory`; retained checkpoint plus sidecar, request-memory, runtime and tree readback |
| `rsi_native_scheduler.py` | `NativeRSISchedulerContext`, native claims, prepared publication and recovery; the fixed `python_handoff_after_native_execution` supplier boundary |
| `producer_python_runtime.py`, `producer_python_runtime_tree.py` | Independently pinned runtime manifest/tree and closed-tree, no-follow validation |
| `producer_python_runtime_material.py` | `materialize_sealed_python_runtime_material` and `verify_sealed_python_runtime_material`; original context-owned material/FD acquisition, without creating an accepted executable root |

The missing loader must consume the independently retained original evidence:
fixed producer profile; archive/configuration/build/ELF/startup pins and live
runtime material/owner; the same CLI/controller `RSILedger`; root sidecar and
independent `PythonProducerCheckpointBinding`; allowlisted
`NativeBootstrapArtifact`; original contract/groups/evaluator/environment
fingerprints; host-constructed `ProducerBrokerConfig`; original execution
control and absolute deadline; root intent/attestation and the fixed late native
handoff supplier. These join the existing
`NativeRSISchedulerContext → PythonRSISchedulerInputContext → PythonProducerRSIExecutionConfig`
chain. Controller/stager code continues to derive request, memory and child
identities. Resume must read the original run/checkpoint; an unknown result must
not create a new launch, nonce or budget.

The current CLI gate is deliberate: `cli.py::_rsi_run_payload` first calls
`require_fixture_rsi_cli`, then constructs `fixture_solver_gateway`.
`native-producer` is refused with
`rsi_python_producer_gateway_cli_accepted_runtime_required`. Removing that gate
before the accepted root exists would bypass the missing acquisition.
`static_python_installation.py`, `static_python_rsi_installation.py`,
`static_python_runtime_startup.py` and `static_python_runtime_handoff.py` retain
all-false admission claims and compare detached observations. Likewise,
`trusted_bootstrap_runtime.py::run_trusted_bootstrap_fixture` is fixture-only and
launches `sys.executable`. None supplies the missing production root.

Complete the configured CPython/freezer/static ELF, original custody, sealed
startup and live-owner acceptance before connecting this loader. A file with
`accepted: true`, a matching directory/hash, or a caller-selected
factory/module/callback/host interpreter cannot substitute for that acquisition.

## Original writer enclosure and quiescence

The existing monitor path already binds useful original objects:

- `producer_grant_anchors.py::HeldProducerGrantPlan` holds and validates the
  context-owned grant nodes; a detached manifest cannot recreate that owner.
- `static_python_pycache_grants.py::GrantBoundPycacheMonitor.arm_before_target`
  binds the live held owner, complete original writable-root set and root
  device/inode identities. `_check_original` and `_observe` revalidate them.
- `native_pycache_diagnostic.py::_NativePycacheDiagnosticScope` arms before the
  original target gate is released and closes after native cleanup. Callback
  delivery does not establish writer quiescence.
- `native_whole_scope.py::NativeWholeScopeOwner.finish` consumes the original
  native terminal/empty path and terminal registration check for the enrolled
  process tree. It does not exclude writers outside that tree or other users of
  the same credential.

The outstanding prerequisite is enclosure of the original fixed credential U
throughout the entire relevant interval: exclusive use, exclusion of foreign
credential issuance, and finite acquisition/exclusion of external writable FDs,
mappings, ACL grants and aliases. There is no root account reservation manager
in this repository; this note does not introduce one.

`static_python_pycache_monitor.py::FinitePycacheMonitor.finish` therefore still
records `original_quiescence_unavailable` and retires only its own reader.
Grant-bound diagnostics retain `writer_enclosure_verified=false`,
`original_quiescence_observed=false`, `coverage_complete=false`,
`strict_view_accepted=false` and `production_admission=false`. A lock, transient
`/proc` scan, target exit, EOF or matching DTO cannot prove interval-wide
exclusion or clear this missing evidence.

Real root/account/ACL/cgroup/ownership environment acceptance retains its
existing prerequisites. Skipped prerequisites and local diagnostic fixtures are
not successful acceptance, and `production_admission`/`online_publication`
remain false until the actual original acquisition and joins are complete.
