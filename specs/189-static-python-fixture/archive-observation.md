# Gate A: local archive observation

Feature189 Gate A records what is actually present in one local static-Python
archive. It does not download an archive, verify a release signature, extract
files, apply a source patch, build a runtime, execute a runtime, or publish a
staging image. Those operations remain separate gates.

## Immutable acquisition

`snapshot_archive(path, archive, ...)` opens the selected fixed-profile
archive once through `O_NOFOLLOW` directory and file descriptors. It checks the
regular-file kind, pinned size, named-file identity before and after reading,
exact EOF, and the pinned SHA-256. The returned frozen
`StaticPythonArchiveSnapshot` owns the compressed bytes and their digest. Every
subsequent operation consumes those bytes and never reopens the path. The
snapshot records `signature_verification="not-performed"`.

The acquisition path is bounded before traversal and rejects literal empty,
`.` and `..` segments. A supplied deadline is checked before the first open,
before each parent component, around each bounded read, and before/after
hashing and snapshot construction through the final return. Non-finite or
non-numeric clock results are refusals. Cleanup attempts every known owned
descriptor and preserves an existing primary refusal; an otherwise successful
read with an uncertain close fails with `cleanup_unknown`.

Only this fixed-profile path acquisition can set
`profile_pin_verified=True`. `snapshot_archive_bytes` is a byte-only seam and
`snapshot_inert_archive_bytes` is the explicit provider-free fixture seam;
inert snapshots retain `profile_pin_verified=False` and must be observed with
`require_profile=False`. An inert result is therefore not evidence that a
CPython or Zig release archive matches its production pin.

These DTO fields describe checks performed in this process. A frozen Python
DTO is not an unforgeable authentication token or a signature-verification
receipt. The production observer rechecks primitive field types, byte budgets,
fixed size and SHA, and source identity shape; it refuses a byte-only snapshot
with no acquired source identity.

## Bounded archive grammar

The observer first decodes XZ within the compressed, decoder-memory, and tar
stream budgets. It then accepts only USTAR headers with the `ustar\0` magic and
`00` version. PAX and GNU extensions, links, devices, FIFOs, sparse entries,
non-regular special types, and mode bits outside `0777` are refused. Paths
must be UTF-8, rooted under the pinned root directory, and contain no empty,
`.` or `..` segment, `//`, backslash, control character, colon, or absolute
prefix. The root directory is required, and duplicate paths and file-directory
ancestor collisions are refused.

The observer hashes and sizes each actual regular-file member, requires zero
size for directories, sorts members by canonical path, and emits the canonical
`lunar-static-python-extraction-manifest-v1` bytes and SHA-256. Member count,
single-file, total-file, compressed, decoder, and decompressed-stream budgets
are enforced before a result is returned. The tar stream must end with two or
more zero blocks, remain aligned to 512-byte blocks, and cannot contain
non-zero trailing bytes. Raw header type, magic, version, text termination and
octal numeric fields are checked before a library parser sees a member; GNU
base-256 numbers and hidden non-zero text after NUL terminators are refused.

## Metadata relationship

For a profile-verified snapshot, callers must provide the expected extraction
manifest digest. The observer invokes
`validate_static_python_extraction_manifest` as a second metadata layer and
reports `metadata_validation="validated"`; its source-preimage option is
passed through and reflected in `source_preimages_checked`. Inert observation
reports `metadata_validation="skipped-inert-profile"` and never upgrades an
unverified fixture into a production claim.

## Explicit non-goals

This gate does not perform signature verification, network access, staging or
atomic publication, source patch application, compilation, runtime loading,
acceptance testing, remote worker execution, or evaluator calls. A successful
observation is only a bounded, reproducible account of bytes in one immutable
local snapshot.

## Focused verification

The focused suite uses synthetic, inert USTAR/XZ bytes. The path and metadata
integration tests temporarily replace private profile pins with those fixture
digests; they do not claim to verify a real CPython or Zig release. The suite
checks immutable byte-only observation, actual member hashes, canonical
manifest digests, parser preflight refusals, all bounded reads and budgets,
symlink and FIFO refusal, inode drift, deadline checkpoints, and cleanup
failure semantics. Signature verification remains `not-performed` throughout.
