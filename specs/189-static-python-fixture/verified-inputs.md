# Pure archive receipt and extraction manifest contract

This slice continues Feature189 G1. It supplies bounded validation of two fixed
archive receipt shapes and supplied extraction member metadata. It performs no
network, filesystem, archive parsing/decompression, extraction, signature
verification, subprocess or build work. The existing driver remains plan-only;
passing these validators does not admit a toolchain, installation or runtime.

## Fixed advertised profiles

| Archive | Version and root | Advertised size | Advertised SHA-256 |
| --- | --- | --- | --- |
| CPython | `3.13.12`, `Python-3.13.12` | 22926488 | `2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593` |
| Zig | `0.16.0`, `zig-x86_64-linux-0.16.0` | 55478392 | `70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00` |

Use the fixed URLs and identity fields from `profile.py`. CPython's reviewed Git
commit/tag and Zig's target/LLVM/libc description are profile values; their
appearance in a receipt does not demonstrate the identity of downloaded bytes.
Reviewed Git fixture files are distinct from the actual python.org release
archive and its signature. This continuation acquires neither archive.

## Archive receipt

The pure APIs and frozen DTOs live in
`tools/static_python_fixture/verified_inputs.py`; refusals use
`StaticPythonVerifiedInputError`.

`validate_static_python_archive_receipt(raw: bytes, *, expected_sha256: str)` accepts exact built-in
`bytes` of at most 16 KiB and returns a frozen slots
`StaticPythonArchiveReceipt`. Require strict canonical JSON with no trailing LF,
duplicate keys, non-finite numbers or extra fields. The exact top-level fields
are `schema`, `archive`, `url`, `size`, `sha256`, `root`, `version`, `identity`
and `signature_verification`. The schema is
`lunar-static-python-archive-receipt-v1`; `archive` is `cpython` or `zig`.

All profile fields must equal the fixed advertised profile. CPython identity
contains only `commit` and `tag`; Zig identity contains only `target`,
`llvm_version` and `libc`. Reject malformed or substituted shapes, bools in
integer fields and a digest/size/root/URL/version/identity mismatch. The DTO
retains immutable identity pairs, canonical JSON bytes and `receipt_sha256`.
Require a separate exact lowercase, non-placeholder 64-hex `expected_sha256`;
the retained receipt bytes must match it. Validate shapes and bounds before
hashing the receipt. Even a newly canonical, otherwise valid receipt refuses
when it differs from this externally retained pin.
This last digest binds the receipt bytes, not independently acquired archive
bytes.

`signature_verification` records exactly one caller-supplied disposition:
`verified`, `not-performed`, `unavailable` or `failed`. Preserve it honestly;
do not rewrite missing or failed verification as success. Even `verified` is
an untrusted declaration in this pure API. The validator neither verifies a
signature nor authorizes build or production admission based on that value.
Future actual acquisition must retain original signature bytes, verifier/trust
inputs, machine result and first failure separately.

## Extraction member manifest

`validate_static_python_extraction_manifest(value, *, expected_sha256: str,
require_source_preimages=False)` accepts an exact built-in dict and returns a
frozen slots `StaticPythonExtractionManifest`. The exact top-level fields are
`schema`, `archive`, `root`, `archive_sha256` and `members`. The schema is
`lunar-static-python-extraction-manifest-v1`; archive/root/digest must match
one of the two fixed profiles. `members` is an exact list of exact dicts with
only `path`, `kind`, `size`, `mode` and `sha256`.

Each path includes the fixed archive root. The root itself must be a directory
member. Reject absolute paths, empty segments, `.` or `..` segments,
backslashes, colons, trailing slashes, C0/C1 control, DEL or surrogate characters,
paths outside the root, duplicates and a file
used as an ancestor of another member. Input order may vary; retained members
and canonical output are sorted by path. Only `file` and `directory` kinds are
accepted. Symlinks, hardlinks, devices, FIFOs and other archive member kinds are
not admitted by this metadata contract.

Sizes and modes require exact integers. A file size is 0 through 256 MiB and
its SHA-256 is a lowercase, nonzero 64-hex declaration. A directory has size
zero and `sha256=null`. Mode is 0 through `0777`, with no type or special bits.
Bounds are 65536 members, 1 GiB aggregate file bytes, 1024 UTF-8 bytes per path,
16 MiB aggregate path bytes and 32 MiB canonical manifest bytes.
Paths are also limited to 64 segments including the archive root. Reject hostile
subclasses, malformed collections and cheap shape errors before processing
caller-controlled content or invoking callbacks.

The immutable result retains `StaticPythonArchiveMember` DTOs, canonical JSON, `manifest_sha256`,
`total_bytes` and `source_preimages_checked`. The manifest digest binds declared
metadata. It is not a hash of an extracted tree, a tar parser result or proof
that every real archive member is listed.
Require the same exact digest form for the mandatory `expected_sha256`, which
must match the sorted canonical manifest bytes. A digest recomputed from altered
metadata cannot replace the original external pin. The external pin is still a
supplied input; the pure API does not establish its acquisition authority.

`require_source_preimages` must be an exact bool. If true, only the CPython
profile is accepted, and the three fixed patch-input paths from
`source_patch_manifest()` must have the reviewed file sizes and hashes.
Missing or drifting declarations refuse. A true `source_preimages_checked`
means these metadata declarations matched; it does not mean the validator read
the files. The existing source-preparation API must still verify exact bytes
when they are supplied, and actual release extraction requires separate evidence.

## Validation and remaining gates

Use inert bounded JSON and member manifests for canonical roundtrips, exact
profile binding, malformed types, callback refusal, bounds, member/path
collisions, signature dispositions and fixed source-preimage drift cases. Run
focused tests, Ruff, compileall and diff checks after changes. Preserve first
failures; do not invent collected counts or passing CI before execution.

No real archive was downloaded, read, decompressed or extracted by this slice.
Actual archive size/hash, signature results, safe complete extraction and the
compiler/sysroot/static input identities remain G1 work. Source application,
configuration/module closure, same-source frozen headers, direct compile/link,
ELF inspection and real sealed-target startup/lifecycle remain G2/G3 work.
Keep `runtime_load_protection`, `production_admission` and
`general_code_origin_protection` false. These DTOs are preparation metadata,
not runtime admission or machine execution receipts.
