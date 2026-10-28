# WQ-06: original monitor and finite writer enclosure gap

Status: design gap, not an implemented accepting path. WQ-06 remains open.
The current installed profile is `linux-cgroup2-original-scope-v1`. Its original
native empty-scope observation and fixed-U input ACL work do not establish the
separate finite writer premise. No new DTO, caller boolean or detached receipt
is introduced by this note.

## What the current code establishes

`NativeWholeScopeOwner.finish()` consumes the original native terminal exchange,
waits for its original supervisor and checks the original installation within
the same deadline. This concerns the enrolled target and its descendants.
`GrantBoundPycacheMonitor` separately binds an original inotify acquisition to
the still-live `HeldProducerGrantPlan`, requires the exact writable root set,
and retains the original directory descriptors and event stream. Its current
`finish()` deliberately records `original_quiescence_unavailable`; no accepted
cache-absence result exists.

The attempt launches B with `/dev/null` stdin and pipe stdout/stderr. B's two
descriptor-close phases, actual credential/capability drop, original grants and
Landlock/seccomp restrictions provide important parts of the capability review.
They are not a complete acquired finite-writer enclosure. In particular:

- `populated=0` excludes live tasks in the original execution cgroup. It says
  nothing about a process outside that cgroup holding a writable file/directory
  descriptor or mapping to a monitored object.
- The installed numeric U is fixed. The profile currently acquires no original
  exclusive-U reservation for the complete interval and does not establish that
  another process under U cannot already hold or acquire a relevant capability.
  A root-owned parent and U-owned `0700` leaf do not prove this absence.
- A finite root manifest and matching digest do not enumerate inherited or
  transferred writable descriptors, mappings, alias paths, relevant ACL/group
  access or service-mediated writers. The trusted creator's retained descriptors
  remain logical checked custody, not kernel-immutable file custody.
- Inotify is an event stream, not a writer census. An empty queue or final scan
  cannot retroactively establish those capability premises; writable-mapping
  effects are not comprehensively reported by inotify. Overflow, watch loss,
  topology changes and missing original coverage must continue to refuse.

Trusted administrators remain in the deployment TCB. The design must state their
noninterference obligation; software must not describe a private path or scope
as protection against an administrator who can write its underlying objects.

## Minimum accepting extension, if selected

Before adding an accepting consumer, select and review an explicit installation
contract that supplies both of these original acquisitions:

1. A fixed-U exclusion/reservation held from before candidate capabilities are
   issued until original completion. A root-controlled nonblocking lease can
   prevent cooperating Lunar owners from overlapping, but is not proof that no
   unrelated U process exists. The installation must reserve U from other
   services/logins, check the actual initial account/process condition, prevent
   independent untrusted launches under U throughout the interval and retain the
   original reservation. A current PID list or later scan alone is insufficient.
2. A complete finite writable-capability acquisition bound to the original
   attempt, held writable roots, original file/mount/name graph and grant set.
   It must account for actual inherited descriptors (including 0/1/2), writable
   mappings/aliases and every allowed descriptor/IPC/service transfer route.
   Non-filesystem protocol pipes must be distinguished by their real objects and
   roles. Unknown capabilities, supplementary access or a foreign writer refuse.
   A digest or self-declared empty `unknown_write_capabilities` list cannot supply
   this acquisition.

Only the same live native owner may consume its original complete stop/empty
observation and end the independently acquired original monitor interval. A
minimal ordering is:

1. Acquire the reviewed installation, U reservation, original publisher/grants
   and finite view; preserve their identities and original absolute deadline.
2. Start the original B/S relationship and transfer B's original pidfd while the
   controller is still single-threaded. Enroll the trusted paused pre-exec child.
3. Arm every original watch and complete the initial scan before either release
   token permits candidate code. The current monitor starts a reader thread, so
   arming it before `start_original()` would violate that method's deliberate
   single-thread/exclusive-wait prerequisite. Do not relax that gate to fit the
   monitor; place the monitor after original handle transfer and before release.
4. Recheck the original reservation, capability acquisition, grants, native
   binding and monitor at release. Keep monitoring through native completion.
5. After the same original native owner consumes complete empty/retirement
   evidence, drain the original stream, scan the original finite directories,
   drain again and retire the original reader. Recheck all acquisitions and the
   original deadline. Lost coverage, an unfinished reader or abnormal native
   completion remains unknown; cleanup grace does not extend positive coverage.

No public `quiescent=True`, `writer_enclosure_verified=True`, replayed terminal
record or copied owner may enter that accepting operation. The existing
diagnostic entries must preserve their refusal semantics.

## Changes that require a different explicit contract

The current profile pins the original user/PID/mount/cgroup namespaces and fixed
numeric credentials. The following are alternatives to review, not changes to
silently add under the existing profile:

- Per-attempt UID allocation changes the fixed-U credential/ACL and publisher
  contract and requires an installed allocator and lifecycle reservation.
- New user/PID/mount namespaces or private mount views change the pinned
  namespace and bootstrap ABI. A mount namespace alone does not exclude an
  outside writer to the same underlying inode.
- A private tmpfs/copy or alternate writer broker changes the original object,
  mount and grant relationships. A copied manifest cannot inherit the previous
  creator's identity or custody.
- A host-wide account/capability exclusion policy is a deployment premise that
  the current profile does not acquire. Adding an optional boolean cannot make
  it true; any accepting version must name and validate the selected premise.

Required future cases include an outside same-U writer, an already-held writable
FD/mapping, competing U reservation, extra inherited or transferred FD, original
root/namespace substitution, monitor loss/overflow, late directory creation,
deadline expiry and abnormal native completion. Same-UID fixtures may test
refusals and local mechanisms; they cannot replace actual installed exclusion
and distinct-account acceptance. No model, remote evaluator or benchmark run is
needed to establish this software/design boundary.
