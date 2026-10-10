# Snapshot-bound create-only source staging

This G1 follow-up stages the complete CPython source inventory from one immutable
archive snapshot, replacing exactly the three installation-owned patch inputs
with their already verified postimages. It closes filesystem staging only. It
does not acquire or authenticate a release/toolchain, execute source, configure,
freeze headers, compile, launch a runtime, or grant production admission.

## API and byte chain

`stage_archive_sources(snapshot, destination, *, expected_manifest_sha256,
require_profile=True, deadline, monotonic=time.monotonic)` accepts the existing
exact snapshot DTO, an exact absolute canonical destination string, an external
retained manifest SHA-256 and the caller's original positive finite absolute
monotonic deadline. All scalar validation and complete archive/source validation
precede any destination creation. No caller-defined patch, selected path, source
mapping, tar reader, extraction callback or observed-inventory DTO is accepted.

Use one decode and the existing strict bounded USTAR walker. Its private staging
projection retains all actual regular-file payloads under the existing stream,
member/file/aggregate caps; public three-source preparation still returns only
three files. The same walker observes the complete canonical inventory. Compare
its actual digest with the external pin in profile and explicit inert modes.
Run the existing three-source preimage/policy/postimage checks against those same
payloads. Stage unchanged files with original bytes and the three fixed sources
with verified postimages. Never reopen an archive pathname or use tar extraction.

## Filesystem contract

All destination ancestors must already exist. Walk the absolute parent chain
with held `O_DIRECTORY|O_NOFOLLOW` descriptors and verify path-to-descriptor
device/inode identity before work and before returning. Create the destination
exactly once with mode0700; any existing entry refuses, including empty trees.
Directories inside the destination are mode0700; regular files are mode0600,
single-link, created with `O_EXCL|O_NOFOLLOW` relative to verified directory FDs.
Archive executable/mode bits remain metadata and never enable execution.

`mkdir` does not return an inode handle. The created directory identity is first
observed by stat/open immediately after mkdir, then compared on every reopen;
this does not prove an atomic mkdir-to-first-observation identity against an
adversarial process that can replace a directory within that window. Do not
promote this trusted local preparation gate into adversarial authentication.

Missing explicit directory entries may be materialized as implicit directories,
but every path must come from a verified member or its ancestors. Existing
archive collision/duplicate/link/device/traversal checks remain mandatory. Never
follow a symlink, adopt another inode, overwrite a file, rename a temporary tree,
or repair/delete an uncertain write. Directory reopen operations must compare
the identity retained at original creation. Close every owned FD on all exits.

Write/read/hash work uses bounded chunks and the original deadline throughout.
Check progress on short writes, fsync files and directories, read back each file
through its original descriptor, and compare stat before/after reads plus its
parent entry. At final verification require the exact complete directory-entry
inventory (no added entries), original directory/file identities, mode/link/
size/timestamps and actual content digest. Recheck the held parent chain and
original deadline immediately before returning.

After manifest hashing and the last caller clock invocation, repeat complete
stat and directory inventory comparison without further caller callbacks. The
elapsed host `perf_counter` duration of this bounded final gate is charged to
that last observation of the same original deadline; it does not create a new
deadline or replenish the budget. Include the final caller callback and owned
descriptor cleanup in this elapsed charge before returning. Cleanup uncertainty
cannot replace an existing primary refusal; without a primary refusal it must
refuse success with a fixed descriptor-close reason. Cap materialized entries at131072 and path
depth at64 before any filesystem effect, including implicit directories.

Failure after destination creation may leave a partial or orphan tree. Return
only a fixed refusal code and no success DTO. Preserve uncertain files; do not
delete, retry, reconstruct pins from an existing tree, or claim zero filesystem
effects. This slice has no resume/replay/adoption path. The caller may inspect
failed staging outside this API, but inspection does not establish acceptance.

## Result and claims

Return an immutable detached record with canonical JSON and SHA-256 binding the
archive/snapshot/complete original inventory/projection/policy digests, root,
profile and signature statuses, original ancestor and created-tree identities,
and each final path/kind/source digest/staged digest/size/mode/stat identity.
Implicit directories must be labelled. Mutable manifest views are detached.
`extraction_performed=True` and `fixed_patches_staged=True` describe real local
operations; release/signature/build/runtime/production claims remain unperformed
or false. Inert processing remains explicitly `skipped-inert-profile`; there is
no fallback from failed profile acceptance. A DTO is trusted local retained
evidence, not filesystem immutability, external authentication or authorization.

## Validation and tasks

- [x] Implement shared single-decode byte projection without widening public APIs.
- [x] Implement create-only FD-relative staging, readback and final inventory gate.
- [x] Test inert complete byte chain; wrong manifest/preimage/profile before I/O;
  existing destinations; ancestor/file/directory substitution; symlinks/hardlinks;
  partial/short/failed writes and fsync/readback failures; extra entries; original
  deadline expiry at parse/write/final return; immutable detached result and FD
  cleanup. Preserve partial trees and original failure materials.
- [x] Run focused archive/projection/staging checks, Ruff, compileall and diff check.
- [ ] Require final-source three-version Linux CI and independent raw/source/tree
  audit before main merge. Keep G1 acquisition/signatures, G2 build closure and
  G3 actual runtime gates open.
