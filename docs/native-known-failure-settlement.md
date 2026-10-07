# Known native failure registration

An explicitly wired native RSI provider can now register a verified nonzero exit as `failed`
or a formal accepted-start cancellation as `cancelled`. The result is process-only: it has no
candidate, score, successful execution or evaluation receipt, and cannot promote memory.
Exceptions, callback values, missing terminal evidence and cleaned unknown attempts remain
quarantined. The original absolute deadline and request allowance never restart.

## Explicit wiring

Use the same already-initialized ledger for the provider, gateway and controller:

```python
from dataclasses import replace
from lunar_evolution import (
    NativeRSIExecutionConfig, NativeRSISolverGateway, RSILearningController,
    make_native_rsi_scheduler_provider,
)

context = replace(prepared_context, failure_ledger=ledger)
provider = make_native_rsi_scheduler_provider(context)
gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, provider.plan, provider))
controller = RSILearningController(gateway, ledger=ledger)
```

Inputs, intent, one-shot attestation and native artifact must already be staged and bound as in
the existing native RSI API. The provider freezes the original ledger path/device/inode before
launch. Without explicit failure wiring, the existing success-only behavior remains in place.

The independent `native-rsi.failure-provenance.json` contains the original plan/input binding,
original started claim including created_at, original ledger identity, native terminal/cleanup/
deadline chain and the live broker's original byte/inode pins. Recovery reads those files again;
a sidecar self-hash or SQLite status alone is insufficient. The success sidecar keeps its schema.

## Crash recovery

Ordinary `gateway.run` never repeats a started launch. When the failure sidecar was persisted
before a crash but the immutable result was not, use `gateway.inspect_failure` for a read-only
check and `gateway.restore_failure` to register existing proof. Both require independently retained
original claim/provenance SHA values. They cannot overwrite an existing unknown or different result.
They do not invoke the launch provider, transport, evaluator, candidate publication or cleanup.

For an existing controller episode, use `controller.reconcile_native_failure` with original run/
episode IDs plus original checkpoint, episode-record, claim and provenance SHA values. It reads
historical memory, validates current component fingerprints and original CAS, and reserves one
unknown-reconciliation allowance. Identical retries across result, episode and checkpoint crashes
reuse that reservation. It returns the failure execution without driving more work. Dispatch may
have expired, but evidence registration does not extend it; later explicit resume retains all gates.

If terminal evidence was written but the first failure sidecar was never persisted and the live
broker pin was lost, this API cannot repair the gap. Preserve the attempt as unknown. A broker
stop observation with complete=false is accepted only after the original pinned journal is read
and all admitted requests are proven terminal; active/timed-out/uncertain requests refuse.

## Limits

This closes the known process-failure registration gap only. Full host filesystem/FD/egress
containment, supervision after bootstrap death/pause, sealed Python imports, real OpenEvolve/Shinka
campaigns, production RSI CLI solvers and P2 multi-host ownership remain separate work.
Validation uses local inert C/bootstrap fixtures and provider-free components only.
