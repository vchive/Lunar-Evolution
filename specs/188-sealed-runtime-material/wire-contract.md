# Version 1 material frame

Implementation contract for Feature188. This file freezes the format; it does not
establish implementation or Linux acceptance. Code work still requires the final
Feature187 Linux gate in tasks.md.

## Frame and digest domains

The header is exactly 32 bytes, encoded with `struct.Struct(">16sQQ")`:

| Offset | Bytes | Meaning |
| --- | --- | --- |
| 0 | 16 | `b"LUNARPYMAT" + b"\x00" * 5 + b"\x01"` |
| 16 | 8 | Unsigned big-endian canonical-table byte length |
| 24 | 8 | Unsigned big-endian payload byte length |

The header is followed by the table, then contiguous payload bytes. No padding,
second frame or trailing data is permitted. Validate header lengths and their sum
against the retained limits and actual object size before allocating the table.

All digests use lowercase SHA-256 hexadecimal with these exact byte domains:

- `table_sha256`: canonical UTF-8 table bytes only.
- `payload_sha256`: all payload bytes in table file order, including zero-length
  files without adding separators or metadata.
- `frame_sha256`: the complete 32-byte header, table and payload.
- Each file `sha256`: that file's exact payload range.

The table's protocol/version and the frame magic bind their semantics. Original
declared-manifest/tree digests retain Feature171/177's original domains. Neither
is recalculated from current source observations as an admission replacement.

## Canonical logical table

The table is one JSON object. Encode UTF-8 with `ensure_ascii=False`, sorted keys,
comma/colon separators and no NaN. Refuse duplicate object keys, invalid UTF-8,
noncanonical encoding and fields outside this exact schema:

`schema_version`, `protocol`, `material_version`, `declared_manifest_sha256`,
`tree_sha256`, `target`, `roots`, `directories`, `files`.

`schema_version` is the string `"1"`; `protocol` is
`lunar-python-runtime-sealed-material-v1`. `material_version` is a nonempty
ASCII label of at most 128 characters using the existing root-label grammar.
`target` is the exact Feature171 target object and remains a declaration.

`roots` is the sorted list of declared root labels. It contains no host path.
Each directory has exactly `root_label`, `relative_path`, `children`; each file
has exactly `root_label`, `relative_path`, `role`, `size`, `offset`, `sha256`.
Directories and files are separately sorted by `(root_label, relative_path)`.
Directory children are sorted unique single-component names, including an empty
list for empty directories. Paths preserve the original admitted spelling and
use the existing canonical relative-path rules, with `.` only for root
directories; no Unicode normalization or alias resolution is performed.

Require exactly one root directory per label, every nonroot entry's parent,
disjoint file/directory keys and exact child membership. File roles use the
original Feature171 role set. Offsets begin at zero and equal the running sum
of prior file sizes; zero-length files may share that boundary. The final sum
equals the header payload length. No range gaps, overlap or arithmetic overflow
is accepted.

The retained limits are 16 roots, 4096 files, 8192 combined file/directory entries,
8192 aggregate membership edges, depth64, 256MiB per file, 1GiB payload, 8MiB
table, 4096-character/UTF-8-byte paths and 128-character labels. Guard exact
types and counts before per-member work, hashing, encoding or callbacks. JSON
input is byte-bounded before parsing; DTO tuples and strings are type/length
bounded again after parsing and before serialization.

The materializer must compare this table with the original externally pinned
Feature177 file/directory vector. The live verifier compares independently read
frame/table/payload bytes with that retained table and original external pins.
Detached parsing cannot assert kernel seals or create an ownership handle.

## Detached descriptor

Canonical descriptor JSON is independently bounded to 16KiB and has exactly:
`schema_version`, `protocol`, `scope`, `binding`, `material_version`, `target`,
`declared_manifest_sha256`, `tree_sha256`, `table_sha256`, `table_size`,
`payload_sha256`, `payload_size`, `frame_sha256`, `frame_size`, `root_count`,
`file_count`, `directory_count`, and the five false capability fields
`execution_performed`, `runtime_load_protection`, `production_admission`,
`archive_contents_complete`, `loader_dependencies_complete`.

Schema, protocol, version, target and digests follow the table rules. Scope is
`sealed-runtime-material-only`; binding is `linux-sealed-material-memfd-v1`.
All sizes/counts are exact integers, never booleans. Require
`frame_size == 32 + table_size + payload_size`, the individual frame bounds,
1..16 roots, 1..4096 files and 1..8192 directories, with files plus directories
at most 8192. The parser validates digest spelling and internal size/count
consistency. It cannot rehash table, payload or frame bytes that it has not
received. Only actual live verification compares those bytes and kernel seals.
No serialized immutable-material capability or live ownership field is added.

## Ownership and deadline

Create exactly one anonymous memfd object. A private factory owner retains its
original CLOEXEC anchor FD; the public live object exposes one deliberately
duplicated CLOEXEC borrowed FD plus the detached descriptor. This is one sealed
object with two process-local descriptors, not two material copies. Neither FD
is added to native control v2 or granted production inheritance.

The owner retains both original numbers, object identities, canonical table,
descriptor bytes, external pins and absolute monotonic deadline outside mutable
public handle/descriptor state. Handle/descriptor mutation cannot change those
retained values or produce a new owner. Public close/reuse refuses verification
while the private anchor retains the original object for safe cleanup; cleanup
must still leave any foreign replacement of the borrowed number open.

After pure shape/pin validation, missing host/API support, memfd creation failure
and unsupported F_GET_SEALS refuse before source observation. Later F_ADD_SEALS
and verification failures refuse before yield. Creation/GET_SEALS preflight does
not assert that a later seal will succeed, and introduces no extra probe object.

The verifier requires the original owner, exact object identity/size, all four
kernel seals, expected frame digest, material version, declared/tree pins and
target. It uses position-independent reads so verification does not depend on a
borrower's file offset. Every streaming chunk, directory membership step and
resource acquisition checks the original deadline; it is never renewed.

Source scans must also be deadline-aware. Calling Feature177's existing
unguarded multi-pass scanner with only pre/post time checks is insufficient.
Reuse its pure shape/identity rules and implement a bounded guarded source scan
for Feature188 without changing either historical wire format. Its ancestor
chain must guard every open/stat/fstat and membership step; wrapping the current
unguarded DirectoryChain constructor/check methods alone is insufficient.

Cleanup releases all still-owned descriptors, including after interrupt or
deadline expiry. Before closing an exposed number, compare the original object
identity. Foreign reuse is an explicit cleanup-unknown result and must not close
the foreign object. Preserve the primary exception while recording cleanup
uncertainty; do not let a cleanup error hide the original refusal or interrupt.

After sealing, live material verification is independent of source availability.
A separate source-tree verification may report drift while the immutable bundle
still contains the admitted bytes. Neither result authorizes Python execution,
runtime loading, native FD inheritance or publication.
