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

## Source-tree / staged-tree consistency check

Add `validate_source_staging_consistency` in this module as a separate pure
check; keep `compare_source_provenance`'s receipt-to-observation contract and
wire unchanged. The new check accepts one
`StaticPythonSourceTreeObservation` and one `StaticPythonSourceStaging`, plus
independent expected staging, manifest and source-tree SHA-256 pins. It validates
the exact object types, canonical JSON, self-digests and fixed schemas before
comparing their claims. It performs no path access, filesystem read, network,
subprocess, source execution or build.

The check binds archive, root, archive SHA-256, snapshot SHA-256 and manifest
SHA-256 between the observation and staging manifest. The fixed candidate version
is derived from `source_patch_manifest().source_version` and must agree with the
observation version and root; the staging DTO does not add a separate version
field. Reconstruct the canonical source-tree wire from the staging manifest root
and complete regular-file entries (`path`, original `archive_mode`, `size`, and
pre-patch `source_sha256`) using the fixed `SOURCE_TREE_SCHEMA`; its digest must
match both the independent expected source-tree pin and the observation. Do not
add a source-tree digest to the source-staging wire.

For every regular file, the sorted path set, original archive mode, pre-patch
size and pre-patch SHA-256 must match the observation. Staging entries must
contain exactly those regular files plus unique required directory ancestors.
An implicit directory is permitted only when it is a required ancestor; explicit
source directory entries (including empty directories) are allowed because the
source-tree observation intentionally records regular files only. Their paths,
root containment, archive-mode shape and stat fields are validated, but their
presence is covered only by the independent staging pin. Fixed patch paths must
use the exact `source_patch_manifest()` preimage and postimage sizes and digests
and patch-set digest. Every other file must preserve its source size and digest.
Entry kinds, implicit-directory markers, entry counts, path bounds and stat-wire
scalar types are checked before agreement.

Only two matching metadata dispositions are accepted: validated fixed-profile
claims on both records, or the explicit inert-fixture disposition on both.
Signature verification, release verification, source execution, build,
generated headers, runtime execution, load protection and production admission
must remain unperformed/false. The check validates detached evidence consistency
only: it does not establish that a staging directory still exists, that either
record was honestly produced, or that a later build consumed it. It returns no
admission authority and does not close the separate candidate-build source/patch
evidence task.
