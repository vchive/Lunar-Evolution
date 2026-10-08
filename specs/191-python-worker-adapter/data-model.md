# Data model — Python producer binding

All records use canonical UTF-8 JSON with sorted keys, compact separators, no
duplicate keys/NaN and lowercase SHA-256. Bounds and exact scalar types are
validated before hashing or filesystem effects. A digest is a pin supplied by
the caller or observed from a verified file; this feature never replaces a
missing digest with one computed from current bytes.

## PythonProducerBinding

Current Phase A wire fields:

```text
schema_version, protocol, fixture_case, runtime_manifest, runtime_tree, intent,
attestation, deadline_unix, request_budget, output_max_bytes,
wall_timeout_seconds, broker_policy, binding_sha256
```

The four nested values are the existing immutable DTO wires; they are reparsed
and compared before the binding is accepted. The binding does not create a second
runtime, launch or attestation schema. Convenience properties expose the derived
`run_id`, identities, target, interpreter digest/path, argv, output paths,
dependency/environment fingerprints, intent/attestation digests and the three
launch limits without serializing duplicate fields. The environment remains the
existing digest-only launch field; no credential or endpoint map is added here.
`request_budget`/`output_max_bytes`/`wall_timeout_seconds` must equal the intent,
and `deadline_unix` must equal the existing RSI planned deadline. The complete
durable RSI checkpoint remains owned by the controller and cannot be replenished
by parsing or rebuilding a binding.

The terminal, runtime observation and result-envelope records below are design
contracts only; Phase A does not construct or persist them.

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
