# P2 frozen-memory transfer comparison

The existing transfer receipt describes one frozen solve. It does not measure whether memory
improved an outcome, and a solver score alone is not authoritative. This bounded local slice adds
an explicit paired task panel above the native gateway/independent verifier.

## Scope and interface

`NativeTransferTask` binds one host-owned `NativeEvaluationProfile`, a task identifier, a score
direction, the same budget for both arms, and an immutable task charter. The panel contains at
most 16 tasks. `FrozenMemoryTransferBenchmark` receives a host-owned candidate factory
`factory(request, ReadOnlyMemorySnapshot)` and an explicit actor profile fingerprint. It passes
an empty snapshot to the baseline and the approved frozen snapshot to the memory arm. The actual
snapshot contents are available through a read-only capability, not merely their digest.

The actor identity binds both the callable implementation and the explicit host-supplied profile.
The host must include model/tool/closure configuration in that profile; source inspection cannot
authenticate hidden runtime settings. The benchmark accepts an already-approved snapshot from the
trusted controller. `MemorySnapshot` checks the approval fields and canonical structure, but this
adapter does not reopen its originating practice ledger. Constructing an item with `pass` is not
proof that an independent practice verifier approved it. The host remains responsible for supplying
the controller's validated snapshot and declaring its solver/contract portability.

This is a local measurement adapter, not an autonomous model curriculum or a statistical proof
of generalization. Panel task IDs are declared by the host; the adapter does not prove that a
human-selected task was held out during training. No network requests or model calls are part of
its implementation or regression.

## Fixed comparison and evidence

Before any process runs, persist the exact panel, snapshot bytes, actor profile, gateway/verifier
root binding and request budget in an exclusive intent. Both arms have identical task charter,
contract, evaluator, environment, actor and execution budget. Their episode IDs and memory pins
are distinct. Curriculum and memory writes are disabled in both requests.

Each arm executes through `NativePopulationGateway` and `NativeIndependentVerifier`; the
comparison reads scores only after retained native evidence and the independent rerun pass.
Comparisons expose per-task score deltas oriented by the declared objective, success counts, and
`improved|unchanged|regressed|mixed|unresolved`. Missing evidence, unknown execution and unverified
scores yield unresolved comparison; invalid official candidates are explicitly rejected. No
negative or unresolved outcome can approve or modify memory.

The comparison receipt retains complete episode/request/result/verifier evidence and is
content-addressed. Intent is bounded to 128 KiB and the aggregate panel receipt to 2 MiB. Exact
terminal retry is read-only and reopens each original and verifier
receipt through `validate_retained`; request/profile/root/snapshot drift is rejected. An intent
without a complete comparison receipt is unknown and cannot implicitly repeat either arm. A
later explicit recovery feature may settle that boundary.

`status=completed` means the measurement has settled, including invalid or unresolved arms. Only
the separate `effect` and verified-arm counts describe observed benefit. Non-completed solver arms
retain and reopen their native result/intent but never become verified or contribute a score delta.

## Validation

Real local subprocess fixtures verify improvement attributable to the supplied read-only memory,
unchanged/regressed/mixed scores, invalid/unresolved arms, equal budgets/charters, denied memory
writes, terminal replay without process invocation, profile/panel/snapshot drift, changed original
and clean-room evidence, incomplete intent, and canonical receipt tampering. Fixture improvements
prove the measurement path, not a benefit from a production LLM or external campaign.

The focused transfer suite contains 21 passing cases, including two independently pinned task
contracts in the same panel. Shared budgets and task charters are copied from the persisted intent
for each request. Negative, malformed or unresolved evidence cannot approve memory.
