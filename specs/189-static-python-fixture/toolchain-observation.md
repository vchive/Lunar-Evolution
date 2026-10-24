# Complete toolchain archive observation

This G1 continuation retains one independently pinned, complete Zig archive
inventory and a separate canonical observation record. It reuses
`lunar-static-python-extraction-manifest-v1`; it introduces no second file
inventory format and does not change the source-readiness wire, its bounded
unverified projection, or installation admission.

## Input and budget

`tools/static_python_fixture/toolchain_observation.py` provides
`observe_toolchain_archive(snapshot, *, expected_manifest_sha256, deadline,
monotonic=time.monotonic, require_profile=True)`. It accepts only a Zig
`StaticPythonArchiveSnapshot`. The complete manifest pin is a mandatory,
independently retained non-placeholder lowercase SHA-256. A caller must not
compute that expected value from the result being checked.

The implementation delegates actual compressed-byte, USTAR/XZ, member,
profile and manifest checks to the existing archive observer with one absolute
deadline callback. It also checks that deadline at entry, while projecting
counts, around canonicalization and hashing, and before returning. No pathname
is opened and no archive is extracted. Clock exceptions, bool/nonfinite results
and an expired deadline refuse with fixed error codes.

For real acquisition, callers must pass the same absolute deadline to
`snapshot_archive` and this operation. The snapshot does not retain the
acquisition deadline: the new record cannot retrospectively prove that the
caller used the same budget. Ordinary Python DTOs are not unforgeable custody
tokens. The existing observer revalidates their actual compressed bytes,
profile fields and acquisition-identity shape.

## Output

`StaticPythonToolchainObservation` retains the complete canonical manifest
bytes and their SHA-256 separately from canonical record bytes and their
SHA-256. A detached record projection must not mutate the retained bytes.
The dedicated record has a 16 KiB limit; the existing archive and complete
manifest budgets remain unchanged.
The record schema is
`lunar-static-python-toolchain-archive-observation-v1` and includes:

- archive, root, version, archive size/hash and immutable snapshot hash;
- the six acquisition identity fields (device, inode, size, mode, mtime_ns,
  ctime_ns), or null for a byte-only inert fixture;
- manifest hash, member/file/directory counts and total regular-file bytes;
- profile-pin and metadata-validation results;
- `signature_verification="not-performed"`;
- false claims for extracted-tree observation, toolchain execution, configure,
  build, runtime execution, production admission and online publication.

With the default real profile check, status is
`profile-pinned-archive-observed`. Explicit `require_profile=False` is an inert
test seam: status is `inert-archive-observed` and `profile_pin_verified` remains
false. A byte-only fixture cannot satisfy the real acquired-profile gate.
The complete manifest retains directory entries and all regular files,
including zero-byte files. The record does not invent a measured LLVM version,
selected libc/linker route, signature trust or compiler input consumption.

## Verification and next gate

Inert tests use independently assembled canonical manifests and pins. Cover
complete inventory/count/hash correspondence, detached output, foreign archive
refusal, malformed/wrong pins, snapshot field/byte/profile drift, clock and
deadline failures through final return, and absence of filesystem/network/tool
effects after snapshot creation. Run focused tests, Ruff, compileall and diff
checks before recording passing results.

The real Zig manifest pin already retained in
[`linux-input-observation-20261019.md`](linux-input-observation-20261019.md) is
`b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90`.
An independent replay must retain the full manifest and raw results. Neither
this API nor that replay observes the extracted tree. Held-directory/file
comparison of a concrete extracted toolchain, concrete wrappers/helpers,
build-Python, generated CRT/libc/compiler-support artifacts and configured
build input consumption remain later G1/G2 work. Both build-plan entry points
continue to exit 78.
