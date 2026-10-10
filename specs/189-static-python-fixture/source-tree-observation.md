# G1 original source-tree observation

This slice records the complete original regular-file source tree represented by
one immutable `StaticPythonArchiveSnapshot`. It is a read-only provenance
observation. It does not acquire or authenticate an upstream release, extract or
stage files, apply patches, execute source, configure, compile, launch, or grant
production admission.

## API and independent pins

```python
observe_snapshot_source_tree(
    snapshot,
    *,
    expected_manifest_sha256,
    expected_source_tree_sha256,
    require_profile=True,
    deadline,
    monotonic=time.monotonic,
)
```

Both expected digests are required external lowercase SHA-256 pins. Neither is
inferred from the returned observation. Shape checks happen before decoding or
callbacks. The strict archive walker is invoked once on the immutable snapshot;
no archive pathname is reopened and no network, subprocess, staging, or runtime
route exists.

`require_profile=True` keeps the existing fixed CPython profile and source
identity checks. `require_profile=False` is an explicit inert-fixture mode. It
allows synthetic local USTAR/XZ bytes, but always reports
`profile_pin_verified=false`; it cannot upgrade a fixture into release evidence.
The existing extraction manifest validator remains the profile metadata layer.

## Source-tree wire

The independent `lunar-static-python-source-tree-v1` canonical UTF-8 JSON has
exact keys `schema`, `archive`, `root`, `version`, and `files`. `files` is a
complete, lexicographically sorted regular-file inventory. Each entry has exact
fields:

```json
{"path":"Python-3.13.12/Lib/example.py","mode":420,"size":12,
 "sha256":"<lowercase sha256 of original bytes>"}
```

Paths are the strict archive-rooted paths observed by the existing USTAR
walker. `mode` is the original archive mode (masked to `0777`); `size` and
`sha256` are the observed prepatch bytes. Directories are intentionally absent
from this wire and remain constrained by the complete extraction-manifest-v1
inventory. The digest of these exact canonical bytes is
`source_tree_sha256`. It is a distinct domain from the compressed archive
SHA-256, extraction-manifest SHA-256, Git tree/object IDs, and staged postimage
inventory. No patch or generated file is included.

The returned frozen DTO additionally retains archive/snapshot/manifest digests,
profile and metadata status, original snapshot source identity when acquired,
total regular-file bytes, detached canonical tree bytes, and an observation
canonical record/digest. `signature_verification` remains `not-performed`;
`profile_pin_verified` is true only for an acquired fixed-profile snapshot.
Every mutable view is detached on return.

## Bounds and refusal behavior

The existing compressed, XZ, tar member, per-file, aggregate-byte, path, and
USTAR grammar limits remain in force. Duplicate paths, links/devices, traversal,
unsupported modes, malformed snapshot fields, manifest drift, tree-pin drift,
invalid deadline/clock values, and deadline expiry are fixed refusals. The
original caller deadline covers decode, complete member walk, tree canonicalizing,
hashing, and the final return; it is never refreshed. Errors contain no caller
paths, archive bytes, or credentials.

This observer does not prove release signatures, upstream acquisition, configured
source closure, toolchain provenance, static linking, generated headers, ELF
properties, or runtime behavior. Those remain separate G1/G2/G3 gates.
