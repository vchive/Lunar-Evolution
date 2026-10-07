# Plan

`producer_python_runtime_tree.py` owns frozen directory, tree manifest and observation DTOs, strict
canonical parser and read-only build/verify APIs. Embed the unchanged Feature171 manifest; use its
existing external-pin verifier without changing that module. Root integration owns public exports,
handoff and workflow changes separately.

Reject non-tuple and oversized tree/embedded-v1 collections before serialization. Validate nested
directory scalars before root canonical set/hash checks, then invoke the unchanged v1 validator.
Bound retained ancestor pins separately from scanned entries (8320 per root, 10240 aggregate).
This prevents forced frozen-DTO mutation from entering custom Sequence callbacks or constructing
an oversized intermediate JSON object; it adds no filesystem authority.

Keep explicit root directory chains held across a complete snapshot. Traverse child directories
using dir_fd/O_NOFOLLOW, stream only expected regular files, compare before/opened/after/named stats,
and record complete sorted child names. After all reads, revisit recorded directories through held
root FDs and verify membership and every child's metadata, then recheck roots/ancestors. Global
inode sets reject aliases; work limits bound entries, depth, file/total bytes and canonical JSON.
All owned FDs close on refusal and KeyboardInterrupt/SystemExit.

Two snapshots plus before/after Feature171 checks and a final metadata-only tree pass establish a
bounded preflight observation. The last pass checks membership after the final v1 file reads. They
do not seal a tree against later changes or prove an atomic filesystem view under an arbitrary
concurrent writer. Scope and capability flags preserve that limitation.
