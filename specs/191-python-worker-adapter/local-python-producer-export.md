# Read-only local Python producer result composition

## Scope and inputs

`read_python_producer_adapter_export` reads an already completed local OpenEvolve
wrapper output or an immutable Shinka SQLite/source snapshot and returns the
existing `PythonProducerAdapterEnvelope`. It does not start either project,
discover a Python installation, call an evaluator, write an export directory,
publish a candidate, charge a budget, or grant production admission.

The caller explicitly supplies the fixed producer ID, original binding,
completed terminal, runtime observation and retained `ProducerResultEnvelope`.
Independent nonzero binding, terminal, observation and result SHA-256 pins are
mandatory, as are the installation descriptor, descriptor digest, installation
version and initialization-profile digest. The result pin is the existing
`ProducerResultEnvelope.envelope_sha256` canonical digest; there is no new solver
result DTO or wire. These pins must come from the caller's retained evidence,
not be adopted from the new source read.

Before path conversion or source I/O, compare all retained pins and the explicit
producer ID, build and verify the existing adapter using the original evidence,
and retain detached canonical snapshots. Missing evidence, an unknown terminal,
request-count drift, installation drift and unsupported capability claims refuse.

## Source reads

OpenEvolve uses the same confined, bounded result/candidate reader as
`admit_openevolve_result`, including strict wrapper JSON, UTF-8 and digest-only
external evaluation evidence. The new API stops before seed preparation and
local evaluation. Its material path remains relative to the supplied source root.
The small wrapper does not encode producer identity, budget or lineage; those
fields remain caller-owned retained evidence rather than facts authenticated by
the wrapper file. Candidate bytes/path and external-evaluation summary are the
independently reread source projection.

Shinka uses the same immutable read-only SQLite, schema, selection, lineage,
source-code equality and pre/post database-signature checks as
`export_shinka_result`. It creates no destination, staging tree or SQLite
sidecars. Its material paths are the actual `gen_N/main.ext` or verified `best`
source paths, rather than paths of copies in a destination. Explicit program IDs
preserve caller order; convenience top-k selection retains producer-score
provenance only. The original write/export API and its exported paths remain
unchanged.

Reconstruct only the existing `ProducerResultEnvelope`, using the original
binding identities and retained budget. Compare its complete canonical wire and
digest with the caller's retained result. This catches source, selection,
lineage and external-evidence drift. Run the existing full result-binding and
adapter build/verify again; reread the caller evidence wires to refuse mutation
during source I/O before returning the detached envelope.

## Failure and authority boundaries

Composition failures use fixed `python_producer_export_*` codes; existing source
reader failures retain the original fixed OpenEvolve/Shinka codes. Error messages
contain no source paths, raw source, provider output or credentials. Refusal has
no filesystem writes, launch, evaluation, publication or repair effects.

The reader observes bounded local snapshots, not authenticated solver identity
or process execution. Source paths can change after return; future consumers
must independently pin and reread bytes at their own boundary. This slice does
not close sealed CPython build/startup, live scheduler ownership, actual solver
campaign lifecycle or production CLI/Linux acceptance. `production_admission`
always remains false.

## Validation

Use local fixture files/SQLite only. Cover both successful compositions; matching
canonical adapter wires; all independent pin and producer mismatches before any
path access; missing/unknown terminal/runtime evidence; installation drift;
source/database/evidence/selection drift; caller mutation during I/O; read-only
source inventories and SQLite sidecar absence; and unchanged legacy OpenEvolve
admission/Shinka export behavior. Run focused tests, Ruff, compileall and
`git diff --check` with `PYTHONPATH=src` and an independent pytest base directory.
