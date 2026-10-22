# Complete extracted toolchain tree observation

This G1 continuation compares a concrete extracted Zig directory with the
independently pinned complete extraction manifest. It extends the preceding
[`toolchain-observation.md`](toolchain-observation.md) slice; it does not replace
the archive observation, create another inventory format, execute a tool, or
authorize configure/build. The existing build-plan entry points remain exit 78.

## Contract

`observe_extracted_toolchain_tree(manifest, *, expected_manifest_sha256,
tree_directory, deadline, monotonic=time.monotonic)` accepts canonical bytes in
the existing `lunar-static-python-extraction-manifest-v1` format. The expected
manifest SHA-256 is a separately retained non-placeholder pin. Reuse the
existing validator and immutable manifest DTO; reject a foreign archive,
noncanonical bytes, duplicate keys, missing explicit parent directories, and
invalid or mismatching pins before opening the filesystem.

`tree_directory` is the absolute path of the directory corresponding to the
manifest root, rather than its parent. Its siblings are outside this observation.
The observer opens every path component through no-follow directory descriptors,
holds and rechecks the ancestor edges, and owns each descriptor immediately upon
acquisition. It does not follow a caller-provided symlink at any depth. It reuses
the staged-source observer's bounded scanning, stat comparison, relative-directory
reopening, and cleanup helpers where their semantics match; it must not fabricate
a CPython staging record to call the staging-specific root acquisition helper.

Every manifest directory must have exactly its expected children and permission
bits. Every regular file must have the expected permission bits, size, SHA-256,
and one link. Files are opened nonblocking and no-follow, so unexpected FIFOs,
devices and symlinks refuse without reading their contents. Internal directory
and file identities are captured from the actual descriptors, checked against
their names, and rechecked after hashing and in the final inventory/metadata
passes. These internal stat pins need no new serialized inventory schema.

One positive finite absolute monotonic deadline covers input validation,
acquisition, bounded enumeration, each read, final checks, serialization and
return. Exceptions or invalid values from the supplied clock refuse through
fixed error codes. Pure bounded validation/serialization is checked around the
operation; this is a synchronous observer, not an interruptible OS sandbox.
Every failure closes all descriptors acquired by this call and preserves the
primary failure. Returned errors and the small record do not expose the input
pathname or file contents.

## Evidence and limits

The result retains the complete original canonical manifest bytes and their
digest, plus a separately bounded canonical observation record and its digest.
The record identifies the observed root object, the archive/profile metadata,
the independent manifest pin, complete member counts and total file bytes.
Returned projections must be detached from the immutable retained bytes.

The schema is `lunar-static-python-toolchain-tree-observation-v1`, with status
`pinned-manifest-tree-observed`. The record retains `archive`, `root`,
`archive_sha256`, `manifest_sha256`, `tree_identity`, `member_count`, `file_count`,
`directory_count`, `total_file_bytes`, `observation_scope`,
`signature_verification`, and `claims`. `tree_identity` has seven fields:
device, inode, raw_mode, nlink, size, mtime_ns and ctime_ns. The scope is
`sequential-held-directory-tree-comparison` and signature verification is
`not-performed`. It does not retain the caller's absolute path.

The ten claims are all false: `archive_acquisition_observed`,
`archive_signature_verified`, `toolchain_execution_performed`,
`configure_performed`, `build_performed`, `runtime_execution_performed`,
`future_build_consumption_observed`, `immutable_custody_established`,
`production_admission`, and `online_publication`.

The observation checks an extracted tree sequentially while its original
directory descriptors are held. It is neither an atomic snapshot nor an
immutable custody token for a future build. It closes those descriptors before
return. The result cannot establish who extracted the files or that a later
compiler consumes these same bytes. Manifest metadata validation does not
observe the compressed archive or verify its signature. Preserve those limits
explicitly alongside false execution, build-consumption, production-admission
and publication claims. Do not promote a synthetic matching tree to real G1
acceptance.

## Validation and subsequent work

Use inert, independently assembled manifests and directories to cover complete
matching trees, empty and executable files, detached results, content/mode/size
drift, missing and extra children, symlinks at all depths, hardlinks, FIFOs,
root/ancestor/directory/file replacement, late content or inventory changes,
deadline/clock failures, and cleanup at partial acquisition boundaries. Check
strict wire bounds and pins before filesystem access. Run focused tests, Ruff,
compileall and diff checks, then obtain an independent review.

A real Linux replay must use the previously retained complete manifest pin
`b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90`,
retain the full manifest and raw record/logs, and independently verify transfer
hashes. An archive replay and tree replay are separate observations, even when
their independent manifest pins agree. Concrete compiler/wrapper/helper and
build-Python bindings, clean environment/private caches, fresh patched-source
custody, configure-only execution/output review, same-source freezer, static
link/ELF and sealed runtime acceptance remain open.
