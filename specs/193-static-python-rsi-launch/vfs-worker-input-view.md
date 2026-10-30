# Original initialized worker input inventories

Status: opt-in software implementation; no product execution or acceptance is
authorized by this document. It extends the finite VFS lifetime mechanism with
an original worker view comparison. It does not provide immutable protection.

## Scope and versions

Use the same original recipe-v4 loop, source-data projection, static-tool gate,
finite commands, output groups, deadline and cancellation. No new runner, CLI,
callback, caller-provided owner, process discovery or detached acceptance DTO.

| Surface | Explicit successor |
| --- | --- |
| Backend | `podman-snapshots-source-data-vfs-worker-input-view-v1` |
| Executor | `run_pinned_build_v4_vfs_worker_input_view` |
| Consumer | `run_dependency_checked_build_v4_vfs_worker_input_view_source_directories` |
| Execution report | `lunar-static-python-build-execution-report-v8` |
| Command observation | `lunar-podman-build-command-observation-v6` |
| Dependency report | `lunar-actual-build-dependency-consumer-v7` |
| Lifetime manifest | `lunar-podman-vfs-execution-lifetime-v2` |
| Input-view profile | `lunar-podman-worker-input-view-v1` |

Old entry points, defaults, report bytes and verifiers remain unchanged. New
readers reject old/mixed versions. This slice adds no installation candidate
reader or accepted runtime path.

## Original view and read reuse

Only original `PodmanCustody.run`, after its original init and root/OCI checks,
selects the new lifetime capture and binds the original recipe source/toolchain
and already completed prior-output inventories to the held owner. Before the
existing single start, the owner traverses its held `/source`, `/toolchain` and
`/work` directory FDs. Current `/out` is a different role and never authorizes a
prior input. The owner remains open and is rechecked before and after reading.

An expected trie derives all directories from the original finite regular-file
records. One bounded nofollow walk checks exact members, directory identity,
ordinary-file type, a single regular-file hard link, bytes, size and executable
bits. Stream hashes use bounded blocks; no whole-toolchain buffer or independent
second full-byte scan. Compare
opened and reopened names/objects to detect replacement during each read. Extra
files/directories, missing members, special objects, symbolic links, hard-linked
regular files or drift refuse before start. Source executable bits remain
original data with a noexec mount.

Only the immediately-before-command host snapshot arm moves to the held worker
view; original-root, stage, post-command, completed-group and final checks remain.
For prior snapshots the source-copy hash remains, and only the destination
second readback moves to original `/work`. Static ELF checks before any daemon
operation and initial source/toolchain snapshot copy verification remain. This
is limited read reuse, not comprehensive removal of repeated verification.
Metadata/trie construction and detached summary reconstruction also use the
original checkpoint. The existing 32,768 input-record cap exceeds the original
prior-output maximum of four stages with at most 1,024 outputs each; source and
toolchain retain the original 4 GiB per-input-file ceiling, while prior records
retain the original 128 MiB output-file ceiling. No new attempt allowance is
created. One bounded summary adds no per-file CAS copies or raw-record roles;
the existing 64 KiB manifest and 512 MiB shared CAS limits remain in force.

## Original evidence and consumer

The original lifetime-v2 manifest stores a strict input-view summary bound to
its original owner hash and each role root identity, expected inventory hash,
file/directory count and total bytes. Its before-start phase links the canonical
summary. Original custody observation-v6 binds that manifest and the fixed
profile; execution report-v8 and dependency-v7 preserve all existing checks.
The consumer reads original create-only files with the existing bounded
nofollow ledger, verifies the lifetime/raw/control history, and reconstructs
the strict summary from the original recipe/prior inventories and verified
original owner. It does not query historical `/proc` or recreate a live owner.

## Limits and verification

This proves finite observed view equality at the stated boundary. It does not
prove immutable input consumption, writable-FD/mapping/alias exclusion, complete
driver/configured closure, kernel input closure, complete descendant drainage,
output protection, fixed-U installation or runtime acceptance. Every authority
claim remains false. Current rootless read-only bind mounts restrict guest
writes, while host backing remains mutable; image IDs do not authenticate bind
input bytes. Genuine protection and original drain require separate mechanisms
and evidence and cannot be inferred from this slice.

Focused tests use real temporary role FDs with exact/missing/extra/link/type,
content/size/mode drift, replacement during read, deadline/close refusal and
strict successor wiring. Collect software regression once after the batch.
No model, solver, WebAgent or remote evaluator is involved. Product execution
requires a separately reviewed exact finite plan; existing attempts retain
their original source, budget, failures and evidence.
