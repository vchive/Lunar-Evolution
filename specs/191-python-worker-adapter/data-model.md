# Data model — Python producer binding

All records use canonical UTF-8 JSON with sorted keys, compact separators, no
duplicate keys/NaN and lowercase SHA-256. Bounds and exact scalar types are
validated before hashing or filesystem effects. A digest is a pin supplied by
the caller or observed from a verified file; this feature never replaces a
missing digest with one computed from current bytes.

## PythonProducerBinding

Required fields:

```text
schema_version, protocol, run_id, parent_task_id, task_id, fixture_case,
contract_sha256, producer_id, producer_fingerprint, evaluator_kind,
evaluator_fingerprint, runtime_manifest_sha256, runtime_tree_sha256,
interpreter_sha256, interpreter_relative_path, target, argv, environment,
working_directory, output_directory, config_relative_path, result_relative_path,
request_budget, output_max_bytes, wall_timeout_seconds, deadline_unix,
intent_sha256, attestation_sha256, broker_policy, dependency_sha256,
environment_sha256
```

`argv` is an exact vector. `environment` is an ordered allowlist of non-secret
name/value pairs; provider credentials and arbitrary inherited host variables are
forbidden. Relative paths are portable, non-empty and contain no dot, dot-dot,
backslash or absolute component. `target` is the existing explicit platform,
architecture, Python version and ABI declaration. `request_budget` is shared
with the existing RSI durable budget and cannot be replenished on resume.

## PythonProducerTerminal

The terminal record binds `binding_sha256`, process registration/owner identity,
actual executable identity, start/release/exit timestamps, status (`completed`,
`failed`, `cancelled`, `unknown`), exit/signal, cleanup status, request-journal
identity/digest, stdout/stderr bounded digests and `publication_eligible`. A
terminal with missing process or cleanup evidence is `unknown`; process-only
evidence is never publication eligible.

## PythonRuntimeObservation

Observed fields include actual version tuple, cache tag, ABI/profile, argv and
orig_argv, selected flags, filesystem/stdio encoding and errors, `sys.path`,
startup module names/origins, broker transcript digest, pycache absence and
fixed computation result. The record carries `execution_performed=true` only
after the running process emitted these values. Protection claims remain false.

## ProducerResultEnvelope

Use the existing envelope/material schema. Every candidate file has an explicit
relative path, size and SHA-256, with bounded count and bytes. External score or
lineage is normalized to digest-only provenance. The local exact evaluator emits
the authoritative `EvaluationReport`; producer output cannot construct one.
