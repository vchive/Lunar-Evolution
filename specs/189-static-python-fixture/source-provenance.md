# G1 source provenance comparator

`tools.static_python_fixture.source_provenance.compare_source_provenance`
continues the existing fixture preparation tools. It compares the original
`lunar-static-python-archive-receipt-v1` canonical receipt with a detached
`StaticPythonSourceTreeObservation`. It performs no filesystem, network,
subprocess, acquisition, signature verification, build or runtime operation.
It is not included in the runtime package and changes no existing runtime API.

The three mandatory external pins bind the archive receipt bytes, extraction
manifest and independent original source-tree wire. The existing receipt
validator enforces its fixed CPython profile, 16 KiB byte bound, exact fields,
duplicate-free canonical JSON and receipt pin. Its four signature dispositions
(`verified`, `not-performed`, `unavailable`, `failed`) remain caller declarations.
The output preserves that declaration separately from the observer's
`not-performed` disposition; `signature_verification_performed` stays false.

Before agreement, the comparator checks every observation DTO field against
its exact bounded canonical record and SHA-256. It reconstructs the source-tree
wire from sorted, bounded frozen regular-file DTOs, verifies exact tree bytes
and their independent hash, and checks total bytes, all observation identity and
status fields. Receipt archive/root/version/SHA must agree with the observation;
its advertised size must agree with the retained source identity size. A fixed
profile observation requires a retained source identity. It accepts only
`profile_pin_verified=true` and `metadata_validation=validated`; coherent inert
or unknown states refuse. Editing an inert DTO's status while retaining its
original canonical bytes refuses before any upgrade.

Results retain a tuple of frozen `StaticPythonSourceTreeFile` objects, canonical
bytes and detached JSON views. Runtime, execution, origin protection and
production admission flags remain false. Matching caller-supplied detached
records does not establish that the archive observer acquired them. Actual G1
acceptance still requires independently retained real archive and acquisition
proof; this comparator cannot manufacture that proof.

Provider-free tests use the original fixed archive receipt *metadata* plus real
inert archive observations and require refusal. They test stale DTO upgrades,
canonical/hash/field drift, signature declarations, exact types, independent
pins, deeply frozen output containers and absence of external effects. They do
not fabricate a successful fixed-profile acquisition or claim real G1 success.
