# Implementation plan

## Phase A — contract and pure binding

Reuse the existing `PythonRuntimeTarget`, runtime manifest, closed-tree
observation, `ProducerLaunchIntent`/attestation, broker config and RSI durable
run records. Add no second source of truth for budgets or fingerprints. Define
one `PythonProducerBinding` DTO and canonical digest projection. Validate exact
types, ordering, bounds, unknown fields and fixed refusal codes before paths,
callbacks, filesystem reads or spawn.

The binding records interpreter/loader/stdlib/dependency/project/resource file
vectors, target ABI, runtime/tree digests, executable identity, argv and env
allowlist, config/result relative paths, producer/evaluator fingerprints,
request/output limits, parent task/run IDs, original deadline and fixture case.
Credentials, endpoint headers and raw child output remain host-only or bounded
evidence and never enter canonical intent/config bytes.

## Phase B — local inert Python fixture

Build a fixture process from an explicitly supplied runtime root. It receives no
host `PYTHONPATH`, user site, `.pth`, `sitecustomize`, bytecode-write permission,
network or arbitrary file grant. It runs one fixed entrypoint, computes a real
known result, performs one broker exchange through the existing endpoints and
writes one bounded producer envelope. It reports actual version/cache tag,
flags, startup module origins and FD/protocol observations.

The fixture includes readable decoy source, bytecode, extension and zip files.
Source/bytecode/extension/file finder/path finder/zip/unknown-codec routes must
return fixed import errors. The test must show decoy bytes were readable before
the refusal so Landlock/permissions are not the only explanation.

## Phase C — lifecycle and RSI integration

Use the existing native launch lifecycle and owner from Feature190. Persist the
binding before release, retain the original absolute deadline, map it once to
monotonic time, and reuse the current broker journal/request accounting. Wire
`run`, `resume`, `reconcile` and cancellation so unknown state is read-only and
idempotent. Preserve primary errors and cleanup-unknown evidence on every path.

The local exact evaluator remains the sole validity/score authority. A producer
result may become a seed or population candidate only after exact local
evaluation and existing atomic publication. OpenEvolve/Shinka provenance is
separate from evaluator and runtime identities.

## Phase D — acceptance and documentation

Run focused pure tests, fixture process tests, lifecycle/recovery tests and the
complete Linux matrix only after Features189/190 are accepted. Retain first
startup/compiler/linker failures, raw terminal/journal evidence and independent
descriptor/ELF/runtime audits. Do not use host Python, a remote evaluator,
WebAgent, a model, or a real external campaign for a provider-free acceptance.

P2 remote evaluator, external worker authentication, multi-host ownership,
service API and distributed scheduling remain explicitly out of this plan.
