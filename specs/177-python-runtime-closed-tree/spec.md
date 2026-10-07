# Feature 177 — Closed Python filesystem layout preflight

Status: local implementation and focused validation complete; root integration/CI pending.
This is the next local P1 prerequisite after Feature171.

Add separately named build/parse/verify APIs for a finite filesystem layout. Retain the exact
original declared manifest and require its caller-owned SHA and target. Walk only its explicit
roots through held no-follow directory descriptors. Every regular file must be declared, all
declared files must be present, and all directories including empty directories have exact child
membership and device/inode/mode/time observations. Refuse links, special objects, aliases,
overlap, unknown members, drift and independently bounded input/work/schema limits.

Before serializing or entering the unchanged v1 validator, recheck exact immutable collection
types, counts, exact nested DTO kinds and scalar fields. Caller-forced DTO mutation must not
trigger custom sequence length/index/iteration/hash callbacks. Relative file/import depth is
limited to 64 before serialization. Retained v1 directory pins have at most 8320 entries per root
and 10240 in aggregate: the closed-tree bound plus up to 128 outside ancestors for each of 16
explicit roots. Those ancestor pins are metadata evidence; they do not add scan roots or grants.
Exact-string character length is checked in O(1) before path parsing, encoding, regex or enum
hashing: paths at most 4096 characters, labels at most 128, and each enum at its maximum legal
length. The existing 4096-byte UTF-8 path limit remains enforced. Raw embedded v1 dictionaries
pass the same cheap scalar guards before v1 parsing, and external expected targets are guarded
before v1 verification. Cumulative child membership is at most 8192 before any member-validation
loop; repeated directory objects cannot multiply that work. String JSON input has a cheap
character cap before encoding and retains the final 8MiB UTF-8 byte cap.

Builder and verifier run two complete tree snapshots, including closing membership/stat checks,
and reverify the original declared-file pin before and after. A final metadata-only tree pass
closes directory membership after that last declared-file read. Parsing is canonical, exact and
effect-free; a parsed self digest is not independent filesystem authority. Recovery verification
requires original tree, declared-manifest and target pins; it never admits today's tree as expected.

Wire and observations say scope=closed-filesystem-layout, execution_performed=false,
runtime_load_protection=false, archive_contents_complete=false and
loader_dependencies_complete=false. This verifies filesystem names and declared file bytes only.
Archive members, CPython/ABI identity, transitive loaders, dynamic imports, immutable runtime
protection, read grants and launch/attestation delivery remain subsequent work. Do not alter v1
declared inventory or its intentional unlisted-file acceptance behavior.

Validation uses inert local blobs only. No Python producer, upstream project, model, evaluator,
package installer, environment file or credentials are executed/read.
