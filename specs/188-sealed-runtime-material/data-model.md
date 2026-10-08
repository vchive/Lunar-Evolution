# Data model

The following names and bounds define the proposed contract; no classes or APIs
are implemented by this SDD preparation.

## Detached image descriptor

`PythonRuntimeMaterialDescriptor` is immutable bounded evidence for one material
version. It contains exact schema/protocol/scope, explicit version, original
declared-manifest SHA, closed-tree SHA and target, canonical logical table SHA,
payload SHA/size, complete frame SHA/size and
`binding=linux-sealed-material-memfd-v1`.

The target is the original Feature171 declaration. Any installation recipe pin is
explicit external provenance, not an observed CPython/ABI/build/load fact.
An image descriptor here describes material bytes; it is not an executable image
or formal Python admission.

No absolute host source paths, PID, numeric FD, live owner token, grants, scores,
credentials or execution receipts are serialized. Parsing validates exact fields,
canonical bytes and digests without opening files or creating a live object.
A parsed self digest does not replace independent caller pins or kernel evidence.

## Single framed bundle

Wire protocol: `lunar-python-runtime-sealed-material-v1`, schema `1`.
The frame has a fixed magic/version header, bounded table and payload lengths,
one canonical UTF-8 table, then contiguous payload bytes in canonical file order.
Exact header byte widths and canonical digest domains must be frozen during
implementation review before the parser is published.

The table binds the original declared/tree/target/version pins and contains
sorted logical root labels, all directories including empty membership, and
every declared file's role, size, payload offset/length and SHA-256.
Root-directory relative path is `.`; all other names are canonical relative
paths. Refuse traversal, links, special entries, duplicate or aliased names,
unsupported path normalization, unknown fields, offset overflow, gaps, overlaps,
missing/extra entries and trailing bytes. Directories have no payload range.

Suggested retained bounds: 16 roots, 4096 files, 8192 files/directories, depth64,
256MiB per file, 1GiB total payload, 8MiB table, 4096-character/UTF-8-byte paths
and 128-character labels. Framed total is separately bounded by header + table
+ payload. Sum membership edges before per-member work. Cheap exact-type and
length/count guards precede callbacks, encoding, hashing, Path or enum validation.
Materialization and verification stream chunks and honor one original deadline.

The custom table establishes exact membership of this frame only. It does not
enumerate archive members or imports inside declared opaque file payloads.

## Live ownership

`SealedPythonRuntimeMaterial` is factory-created context state for one original
memfd. It holds original object identity, descriptor/pins, exact bounds/deadline
and private ownership state that detached parsing cannot recreate.

Success requires a regular memfd of exact expected size with all of
F_SEAL_WRITE, F_SEAL_GROW, F_SEAL_SHRINK and F_SEAL_SEAL. Partial seals, ordinary
unlinked files and F_SEAL_FUTURE_WRITE-only objects refuse. Numeric FD reuse or a
same-byte different object does not retain original ownership.

The context owns its original descriptor until exit. Reader duplication does
not transfer its cleanup authority. Borrowed FDs must not be manipulated by the
caller; unexpected replacement refuses without closing a foreign descriptor.
Interrupts and failures release all still-owned handles and preserve primary
exceptions. Anonymous material creates no durable path to repair or delete.

## Observations

`scope=sealed-runtime-material-only`.
Only successful live kernel/frame verification may set
`material_bytes_immutable=true`. It describes unchanged underlying material
bytes, not source-tree immutability or process-memory protection.

All observations retain:

- `execution_performed=false`
- `runtime_load_protection=false`
- `production_admission=false`
- `archive_contents_complete=false`
- `loader_dependencies_complete=false`

Detached observations cannot authorize launch, reconstruct a live FD or make
a claim about current live material existence. No durable replay grants new
execution, cleanup or publication authority.
