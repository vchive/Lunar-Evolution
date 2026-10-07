# OpenEvolve trusted local strategy

Feature 170 adds an explicit `EvolutionContext.trusted_native_execution` API to the existing
`OpenEvolveStrategy`. It has actual local C producer/broker/evaluator regression coverage. It is
not yet a Python OpenEvolve runtime inventory or a real campaign integration. The RSI CLI still
selects fixture solvers; this API does not change those choices.

The execution chain is:

```text
frozen contract/config + original intent/attestation/bootstrap
→ create-only admission claim in .producer-runs/openevolve/
→ formal native lifecycle (host-only broker, original deadline, cleanup)
→ one generic candidate material
→ one independent local exact evaluator call
→ independent local admission checkpoint
→ existing atomic OpenEvolve seed commit
→ completion acknowledgement
```

To prepare a local integration, construct the ordinary OpenEvolve `EvolutionContext` with an
absolute native command and pinned local evaluator. Call `prepare_openevolve_native_inputs(context,
journal_id=...)` before building the launch intent. The intent argv must be exactly:

```python
(executable_relative, *context.config.command[1:],
 "../.producer-input/config.json", *inputs.argv_fragment)
```

Use producer ID `openevolve`, its fingerprint from the strategy, the same contract/evaluator,
`working_directory="work"`, `output_directory="output"`, and explicit native execution pins.
Configured context/strategy authority pins must agree with the intent. The C target reads the
config argument and writes `../output/candidate.py` plus `../output/producer-result.json`; material
and entrypoint names may differ but must describe exactly one file and one `BundleGroup`.

Build the attestation using an explicitly supplied one-time nonce, then bind the inputs:

```python
from dataclasses import replace
from lunar_evolution import (
    OpenEvolveNativeExecution, OpenEvolveStrategy, bind_producer_launch_inputs,
    openevolve_native_workspace,
)

runtime = openevolve_native_workspace(context.workspace)
bound = bind_producer_launch_inputs(
    runtime, intent=intent, attestation=attestation, artifact=artifact, inputs=inputs,
)
execution = OpenEvolveNativeExecution(
    producer_root=producer_root, intent=intent, attestation=attestation,
    artifact=artifact, broker_config=host_broker_config, groups=(single_file_group,),
    deadline_unix=original_absolute_deadline,
)
context = replace(context, trusted_native_execution=execution)
result = OpenEvolveStrategy(context).run()
```

The deadline is the original absolute wall-clock deadline for the entire operation, no later
than the configured allowance. It is conservatively mapped once to monotonic time. A tighter
parent `remaining_timeout` narrows the same control; cancellation and ownership loss stop active
native work. Cooperative evaluator objects receive the same remaining-time hook, restored after
admission. Ordinary in-process callbacks are checked before and after but cannot be preempted by
this wrapper; subprocess isolation remains the evaluator's responsibility.

The broker destination must have no userinfo, query or fragment. Authentication belongs in
host-only headers, which never enter the config, claim or target environment. Neutral config
staging is a generic API, not a credential scrubber; the strategy accepts only its exact generated
config. Python SDK support will require a separate runtime/source/resources inventory and broker
adapter. This C acceptance does not authorize direct networking or a Python campaign.

Keep the same injection, deadline, journal, nonce and retained files for `resume()`. A fully
acknowledged completed run replays with no launch, request, evaluator, publication, writes or
signals, even after its deadline expires. Native execution dependency/environment identities and
generic seed source-bundle/protocol identities remain separate in the admission checkpoint.

A started claim without complete acknowledgement returns `openevolve_native_recovery_required`.
This includes interrupted evaluation/publication and a commit with a lost final acknowledgement.
Do not delete its evidence, generate a new nonce or call the legacy launcher to retry it. This
slice deliberately provides no unknown-to-success settlement. Removing the injection while its
companion workspace remains also refuses a protocol downgrade. Existing legacy workspaces keep
their established behavior when no trusted evidence is present.
