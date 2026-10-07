# Plan

`producer_python_runtime.py` owns frozen target, directory, root, file, import-root, manifest
and observation DTOs; a declared-file builder, strict canonical parser and externally pinned
read-only verifier. It does not depend on native orchestration.

No-follow held directory chains protect every opened ancestor. Streaming hashes compare file
before/opened/after/named stats, rejecting hardlinks and special files before reading. Whole
snapshot repetition detects earlier-file mutation during observation. Descriptor cleanup also
runs on interrupts. Directory timestamps are not durable pins: this phase does not inventory
unlisted directory contents. Permission and device/inode changes remain drift.

Limits are 16 roots, 4096 declared files/import roots, 256MiB per file, 1GiB aggregate and 4MiB
canonical manifest. These limits are independent of the native isolation protocol's 64 read
paths because this module does not produce permissions.

The manifest embeds one exact declared launcher policy and a declared CPython 3.11/3.12/3.13,
linux/darwin, x86_64/aarch64 target. Five host-bound slot digests include complete file metadata;
the manifest digest covers roots, directory pins, policy, entrypoint and every slot.

Parallel implementation owns the new module and focused tests separately. Root owns SDD,
public exports, documentation and integration validation. Existing working changes are retained.
