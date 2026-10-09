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

The canonical binding bytes may be persisted once per producer batch as the
`python-producer-binding.json` sidecar. The sidecar is bounded to the same 2 MiB
maximum as the binding parser, is published as a regular `0600` single-link file,
and is never overwritten. The controller retains a separate `PythonProducerBindingSidecar`
pin containing `raw_sha256`, `raw_size`, `file_device`, `file_inode`, `file_mode`,
`file_nlink`, `file_mtime_ns`, and `file_ctime_ns`. The pin is caller-held evidence;
the sidecar cannot authenticate itself by carrying a pin read from its own bytes.

`persist_python_producer_binding` validates the binding before opening the workspace,
serializes through the existing recovery lock, publishes through an owned temporary file
and hard-link, and cleans up owned temporary or failed-publication files.
`read_python_producer_binding_sidecar` validates the retained pin before workspace I/O,
checks no-follow regular-file identity before/during/after the read, compares exact
canonical bytes and digest, and reparses the binding. A missing, replaced, touched,
linked, symlinked, mode-drifted, oversized, or mutated sidecar is not recoverable.

The terminal and runtime-observation DTO/parser contracts below are implemented as pure
validation. `recover_python_producer_terminal` composes native read-only process recovery
with the sidecar gate: it verifies the retained sidecar before native inspection and once
more afterwards, and never creates a recovery lock/marker, relaunches, publishes, evaluates,
or consumes another request budget. Terminal resume/reconcile still operates on retained
values without mutation. The existing result envelope remains unchanged. Controller
checkpoint binding, runtime capture, and production admission remain open.

## PythonProducerBindingSidecar

The sidecar filename is fixed to `python-producer-binding.json` inside the binding's
existing `evolution/producer-batches/<journal_id>` directory. Its bytes are exactly the
canonical `PythonProducerBinding` wire; there is no second self-describing sidecar schema.
Publication is create-only and is serialized with the existing recovery lock while the
batch is still not started. The final retained pin is captured only after the helper hard
link is removed, so `file_nlink` is exactly one. Recovery does not acquire that lock or
write a marker: it opens the held batch directory read-only and compares the file's
no-follow identity and exact bytes to the controller-retained pin.

The sidecar is allowed by the final native launch-input not-started check because it is
the binding being validated; the initial prepare/bind checks still treat its presence as
evidence that a binding attempt has started and refuse a second preparation.

## PythonProducerTerminal

The terminal record binds `binding_sha256`, process registration/owner identity,
admitted interpreter source identity, start/release/exit timestamps, status (`completed`,
`failed`, `cancelled`, `unknown`), exit/signal, cleanup status, request-journal
identity/digest, stdout/stderr bounded digests and `publication_eligible`. A
terminal with missing process or cleanup evidence is `unknown`; process-only
evidence is never publication eligible.

The terminal `executable_device` and `executable_inode` pins are the original
admitted interpreter source stat from the runtime manifest. They are not the
sealed memfd target stat and do not establish live-target loading. Actual sealed
target and owner observations remain in the existing native process receipt;
this pure DTO adds no live FD or runtime observation.

All known terminal states require registration, owner, interpreter byte/size/device/
inode, start/release/exit timestamps, verified cleanup, request-journal digest and
exit or signal evidence. Timestamps are ordered; completed exit precedes the
original deadline. Reconcile preserves every already retained identity, journal
and timestamp pin, stdout/stderr digest and any already known cleanup status,
and cannot refresh the deadline or journal request count. The mandatory stream
hashes have no absent/partial-evidence flag; replacing them requires a future
versioned evidence policy. Process receipt projection retains known exit and
cleanup evidence while remaining `unknown`. Its attestation `consumption_sha256`
is not a broker request journal, so `request_journal_sha256` remains absent until
an authentic broker observation supplies it.
Reused DTOs are revalidated against their retained digest. Missing/zero digest
placeholders and `publication_eligible=true` are refused because this pure record
has no evaluator/envelope/publication evidence. A process receipt alone remains
`unknown` when runtime timestamps, source identity pins or request-journal evidence
are unavailable.

## PythonRuntimeObservation

Observed fields include actual version tuple, cache tag, ABI/profile, argv and
orig_argv, selected flags, filesystem/stdio encoding and errors, `sys.path`,
startup module names/origins, broker transcript digest, pycache absence and
fixed computation result. The record carries `execution_performed=true` only
after the running process emitted these values. The current pure parser can only
validate this child declaration; it does not prove that a process emitted it.
The capture/binding path must establish that fact before real acceptance.
Protection claims remain false. Collection fields are bounded exact lists on
the wire and immutable exact tuples in DTOs; callback-bearing mappings or
iterables are rejected before conversion or serialization.

## ProducerResultEnvelope

Use the existing envelope/material schema. Every candidate file has an explicit
relative path, size and SHA-256, with bounded count and bytes. External score or
lineage is normalized to digest-only provenance. The local exact evaluator emits
the authoritative `EvaluationReport`; producer output cannot construct one.
