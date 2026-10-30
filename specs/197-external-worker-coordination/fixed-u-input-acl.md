# Explicit frozen inputs for the original fixed-U owner

Status: software implementation frozen for consolidated regression; actual
installed Linux acceptance remain separate requirements. This slice grants no
production admission, online publication, build custody or quiescence authority.

## Contract and scope

`linux-fixed-u-input-acl-v1` is an explicit child of one original live
`linux-cgroup2-original-scope-v1` acquisition. It is created once through
`NativeWholeScopeOwner.acquire_fixed_u_input_owner()` after the original native
publisher has created this attempt and before the intent or channels are frozen.
No UID/GID argument, detached descriptor, dictionary, deserialization, current
path observation or expired diagnostic can create or substitute this owner.
Copies, pickle and an owner detached from its original parent refuse.

Existing input v1 defaults retain exact files `0400`, directories `0500` and
their exact old schema. Fixed-U preparation, binding and validation require the
same explicit `fixed_u_owner=` object. The new manifest has schema version `2`
and one additional `input_security` object; existing argv terminal marker and
manifest SHA remain unchanged. The launch binding still pins that exact SHA.
Omitting the live owner cannot downgrade or accept schema 2.

The security binding records the installed whole-scope profile SHA, fixed
candidate UID/GID/groups, original namespace identities, original execution and
attempt device/inode/mount/owner/mode identities, journal and original absolute
monotonic deadline. The batch must be exactly the installed execution root's
original `lunar-<nonce>` child and exactly the existing workspace batch layout.
Later effective deadline tightening is permitted; renewal is not.

## Creation and original custody

The trusted controller creates only `.producer-input/config.json` or
`.rsi-input/request.json` plus `memory.json` beneath the original held attempt
FD. It retains the actual creator file descriptions and input directory FD,
their original named-parent links, canonical bytes, full file metadata and
mount identities. These private creator FDs are never candidate grants or
inherited candidate descriptors. Trusted A can still write its private objects;
this is logical checked custody, not a kernel-immutable-file claim.

Data files are root:root `0440` with the exact Linux POSIX access ACL:

```text
user::r--
user:<installed U>:r--
group::---
mask::r--
other::---
```

The input directory is root:root `0550`, with the same exact five entries using
`r-x` for owner, named U and mask. No default ACL or additional entry is allowed.
The manifest remains root:root `0400`, without an access or default ACL. It is
controller-only and is never granted to the candidate.

Canonical data is written and final file mode/ACL established before final
size/hash/mtime/ctime pins enter the manifest. The manifest self-binding contains
only its original device/inode; its final bytes and timestamps remain in the
live owner, avoiding a self-hash/ctime cycle. The directory is frozen after all
entries exist and synced with its original parent. No later chmod, ACL repair,
metadata refresh or successful read can replace an original expected pin.
Partial creation is retained as failed and cannot be reused.

## Consumers and refusal behavior

Input validators preserve canonical request/memory/config, size, contract,
episode, attestation, executable and budget checks. Each fixed-U read rechecks
the original owner, named ancestry, exact ACL, mount and metadata before and
after bounded reads. Original grant extraction and protected-material checking
consume that same owner. Their ordinary path still enforces exact `0400`.

The whole-scope B entry alone may accept the exact data-file grant set beneath
this original attempt, in addition to independently installed readonly roots.
It checks the original graph/parent links, root:root `0440/0550`, exact ACLs,
mount, exclusive input marker and terminal manifest SHA before launch and
release. No entire attempt/input directory, manifest, registration, receipt or
launch sidecar receives a readonly grant. Installed/control ABI is unchanged.
The ordinary bootstrap entry and its defaults are unchanged.

Preparation, binding and gate validation require the original remaining
deadline. `require_unexpired=False` can inspect original pins after expiry only
while the same live owner still exists. This diagnostic cannot prepare, retry,
reconstruct ownership, dispatch or release a gate. Owner closure refuses even
diagnostics. Recovery from saved bytes does not recreate this profile.

## Validation plan and remaining work

One consolidated batch covers old input/grant tests and the new owner/profile
cases: explicit selection, copied/detached owners, strict default refusal,
creation/binding/validation, exact data-only grants, file/directory replacement,
ACL/default-ACL changes, extra entries, profile/namespace/mount drift, deadline
tightening/expiry/renewal and private FD cleanup. User-owned Linux ACL mechanism
fixtures may project installation metadata for contract coverage; they must be
labelled as fixtures and cannot count as installed root acceptance.

Actual root-owned installed profile -> original publisher -> fixed-U input
access -> B/S/G/R -> scope empty/exact-child wait remains an administrator Linux
acceptance task. macOS can cover ordinary contracts and refusal behavior but
cannot substitute for Linux ACL/cgroup/credential acceptance. WQ-06 finite writer
enclosure and original pycache-monitor closure, accepted CPython input/build
custody, complete runtime/solver/production CLI and independent deployment
acceptance remain separate open work.

## Consolidated execution and affected follow-up

The frozen `87f0ca9d` Linux batch executed 1215 nodes once: 1174 passed, four
fixture assertions failed, and 37 skipped in 45.459845 seconds. The first failures
remain retained. The successor frozen tree `2e60bd06` executed nine affected full
files once: 295/295 passed, no skips, in 16.849097 seconds. It contains the fixture
corrections and the shared-OFD `pread` fix with actual child/interruption coverage.
The exact combined domain is 1216 nodes: 1180 passed after the Darwin supplement,
36 root-prerequisite cases unexecuted. Results are deduplicated, not added.
The Darwin-only node passed separately on macOS; the 36 root-owned input
prerequisite cases remain unexecuted. These results do not establish deployed
account isolation, accepted build custody or production admission.
