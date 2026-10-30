# Original whole-scope reference custody in an installed worker

Status: software continuation under development, 2026-10-28. This is the
pre-gate reference/worker composition missing from creator-FD v3. It does not
change native wire operations, process parentage, the default worker channel or
the v1 native restart packet. S-death independent retirement and WQ-06 remain
separate work. No model, remote evaluator or real solver campaign is needed for
this software continuation.

## Original installation and selection

`WorkerInstalledNativeBridge` may explicitly receive the already acquired
`NativeWholeScopeOwner` and its independently supplied
`whole_scope_profile_sha256`. Both arguments are mandatory together and mutually
exclusive with the older `guardian_custody` selection. The original scope must
select private custody v3; v1/v2 cannot inherit creator-description provenance.
The bridge acquires no privileges, creates no replacement scope, issues no
attestation and installs no runtime. The installed worker profile and the native
whole-scope installation profile have separate digests; equality is not assumed.

Before execution the bridge checks the same live scope/custody objects, native
image/profile, original grants, journal and already-bound intent where present.
It retains the original object/path/profile tuple and deadline upper bound.
The native runner may shorten that deadline using its existing composition;
extending it, replacing the child or releasing the scope refuses. Constructor
and observer checks never release either candidate gate.

## Pre-gate ordering and original comparisons

The original native attempt first binds its original registration and adopts the
actual v3 record-creating descriptions. The synchronous registered observer then:

1. Runs the original lifecycle observer and writes its original restart packet
   and completion record through their actual creator descriptors.
2. Independently retains the unchanged native anchor in the installed vault.
3. Obtains the v3 custody reference from the **same live scope**, checks its
   original registration and untouched empty terminal through retained creators,
   and writes the separate whole-scope sidecar described below.
4. Revalidates the original worker/native assignment and all deadlines before
   returning to the existing native gate. Existing native release checks follow.

The retainer accepts the live scope, not a caller-supplied serialized reference.
It requires registered, not released, not finished state. The 925-byte original
registration must equal that scope's binding/scope/target context, and its six
original digests include the native launch, intent, target image, bootstrap,
supervisor and installation profile. Compare the target image with native
registration's `target_execution_snapshot_sha256`; the registered B PID and
scope T PID are different roles and must not be equated.

The three publication descriptions remain in registration/handoff/deadline
order. Compare all three actual original OFD pins with both the original v3 wire
and the native context's bytes and independent creation pins. The deadline pin
is compared against the original validated deadline-file binding; it is never
manufactured by statting a current path. The exact native nanosecond deadline
comes from the original live scope/wire. Reconstructing it by multiplying the
context's floating monotonic deadline is forbidden: native clock sampling is an
existing, separate conversion.

The native context must equal the original anchor-pinned restart packet in full.
The separate native vault record must equal the exact unchanged original V1
payload derived from that anchor, lookup and installed identity. The sidecar
cannot replace a missing native record or anchor.

## Separate create-only sidecar

`external_worker_whole_scope_vault.py` uses protocol
`lunar-installed-worker-whole-scope-vault-v1`, the same NUL-terminated HMAC
domain, and fixed name `whole-scope-<SHA256(original lookup)>.json` in the original
independent installed vault. Its strict schema carries:

- Original worker/host/boot/key identity, lookup/context/mapping and worker profile.
- Independently supplied whole-scope installation profile and exact original
  native nanosecond deadline.
- Original native anchor, digest of its exact native vault record and digest of
  its complete canonical native context.
- Original v3 custody reference, including original creator-backed record pins.
- Fixed false production, native success, cleanup, publication and online fields.

Publication reuses the existing pending/create-only/link/unlink/file+directory
fsync/readback mechanism while the actual new sidecar creator FD remains held.
The new protocol/domain/name leaves existing native and guardian records intact.
Every action checks the original control/wire expiry, scope deadline, live
pre-gate state, original v3 reference, three OFDs, complete native context,
installation bytes, key and assignment baseline. Final readback checks the
original native vault record and chain again. Any partial, conflicting, late or
failed operation refuses the original gate; retain files without repair/retry.

The vault must be separate from native workspace, producer, bootstrap, episode,
custody and installed scope/grant roots, including aliases, in both original
selection and live writer checks. It owns no scope/pidfd/lifeline descriptor.
Regular-file fsync/write can block; checkpoints refuse late return, not impose a
hard syscall bound. Independent native stopping must not wait for this storage.

## Read-only restart and authority

`inspect_installed_whole_scope_reference` accepts only the fixed original lookup
plus independently retained installation, key, context/mapping and **both**
expected profile digests. It loads only the fixed authenticated sidecar, checks
the original anchor/native record/context and matching original v3 reference,
then consumes existing bounded read-only prefix inspection. All inputs and
records are rechecked after observation. Missing sidecar or originals never
causes filesystem discovery, owner acquisition, write, launch, signal, repair,
deadline renewal or a new execution allowance.

The report may state `whole_scope_reference_custody_observed` and an observed
registration/normal/abnormal prefix. It retains unknown execution/cleanup and
false durable-ACK, whole-group cleanup, original quiescence, native success,
production and publication authority. Persisted terminal bytes do not establish
a lost ACK, successful candidate, original reaping or S-death completion.

## Validation plan

Freeze software first, then run one affected selection with existing installed
native/guardian vault, v3 custody and bridge tests. Add focused cases for the
actual pre-gate storage order and same-owner forwarding, original three-OFD
matching, independent profiles, duplicate/partial/fsync faults, expiry and
context/reference/key/pin drift. Exercise fresh-process read-only consumption
and verify no process/write actions or tree changes. Root/namespace metadata
projection and inert local targets are software fixtures, not installed Linux
cgroup, distinct-account, blocked-storage or real solver acceptance. Keep those
deployment tasks open until actually run under their selected installation.
