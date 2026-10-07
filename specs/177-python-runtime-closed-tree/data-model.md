# Data model

`PythonRuntimeTreeDirectory`: root_label, relative_path (`.` for root), device, inode, mode,
mtime_ns, ctime_ns and immutable sorted children. Directory membership is exact, including empties.

`PythonRuntimeTreeManifest`: original `PythonRuntimeManifest`, canonical immutable tuple of tree
directories and tree_sha256. Wire protocol `lunar-python-runtime-closed-tree-v1`, schema `1`, exact
scope and false capability fields. Its digest covers the complete original manifest and directories.
Graph validation requires exactly one root directory per original root, all directory parents,
exact declared-file/child membership and matching original directory pins where available.

`PythonRuntimeTreeObservation`: original target, declared_manifest_sha256, tree_sha256, file_count,
directory_count, entry_count, total_bytes and exact false capability fields. No authorization token,
runtime grant, candidate, score or execution receipt is produced.

Limits: 8192 total files/directories including roots, depth64 below each root, Feature171 file and
aggregate byte bounds, and 8MiB canonical tree JSON. Bounds fail closed rather than widening reads.
Exact tuple/count/nested-scalar validation precedes serialization. Embedded v1 root-directory pins
are bounded to 8320 per root and 10240 aggregate, allowing outside ancestors without widening the
explicit roots. Declared file/import relative depth also uses the 64-component closed-tree bound.
Path text has a 4096-character pre-parse cap and still requires at most 4096 UTF-8 bytes. Labels
have a 128-character cap and target/role enums their finite legal lengths. Tree child-edge count
is at most 8192 in aggregate before member validation. These bounds apply to forced DTO mutation
and embedded raw wire fields; expected target text is also checked before v1 verification.
