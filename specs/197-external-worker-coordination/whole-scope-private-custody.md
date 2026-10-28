# Original whole-scope private receiver custody

## Explicit v2 continuation (software contract, 2026-10-28)

The separately selected `linux-whole-scope-private-custody-v2` keeps v1 as the
default and uses `.whole-scope-custody-v2`, `scope-registration-v2.bin` and
`scope-terminal-v2.bin`. Only the same original owner may select it before
intent/channel creation. S runs with the explicit `--supervisor-custody-v2`
mode; it does not negotiate a fallback. The original registration is unchanged:
925 bytes, version 1, operation 14, sequence 1.

The v2 terminal is exactly 941 bytes: the original 925-byte context with header
version 2, operation 19 (normal) or 20 (abnormal), sequence 2, zero rights and
reserved fields; followed by little-endian `uint32 reason`, `uint32 facts`,
`uint64 observed_monotonic_ns`. Reason values are 0 normal, 1 controller lost,
2 deadline, 3 receiver fault and 4 protocol fault. Facts are independent bits:
0 stop attempted, 1 original scope empty observed, 2 original B exit observed,
3 original G exact-child reaped. Normal requires exactly bits 1 and 3: B is
still waiting for the final S completion and has not yet exited. Abnormal
requires stop-attempted; other facts may only reflect actual original
observations. No unknown bits are permitted. Observation time must be strictly
positive and strictly before the original deadline; expiry cannot create a
new persistence allowance or valid late event.

R must compare the original context, shape and facts, create/write only its
original fixed files, complete file/directory durability, then send a separate
925-byte version-2/operation-21/sequence-2 ACK with the original context. An
event never self-certifies this ACK. The original surviving S stops the scope
before best-effort abnormal persistence. Storage and ACK loss cannot delay G's
independent stop or renew the deadline. R fault or exhausted budget may leave
only a registration prefix. S death remains unknown: the existing G/R topology
does not supply a replacement original reaper or durable G-to-R event route.

The live normal consumer still requires original native completion before
checking the record. Read-only inspection may expose the fixed recorded reason
and separate recorded facts, but all durable-ACK, cleanup, quiescence, admission
and publication authorities remain false. V1/v2 reads observe file identities;
they are not transferred R creator file descriptions. The explicit
[v3 continuation](whole-scope-creator-fd-v3.md) now implements actual R → S → C
creator-FD delivery, with all 34 C transport/adoption mechanism cases passing
in the concentrated Linux batch. Full S-death custody and actual
blocked-storage/root-profile acceptance remain open. Neither the v2 slice nor
the passing v3 software mechanism completes WQ-07 acceptance.

Planned concentrated validation covers unchanged default framing, real v2
receiver packets/files/ACK ordering, malformed/replayed/wrong-context packets,
all fixed reasons and independent facts, missing/partial/late events, replaced
files, lost ACK/receiver, and monitor pre-retention cleanup faults. No fixture
claims installed root/U/cgroup acceptance.

The Darwin fallback for this v2 slice has now executed once from frozen tree
`e7d959d2a4e3d1b5526116d71ec1635d7f3153f6`: 19 complete test files, 16 workers,
641 collected nodes, 391 passed, 250 skipped, and no failures or errors in 20.49
seconds. Source before/after manifests, worker collections, and module origins all
matched; the run used the selected CPython 3.13.12 environment with zero retries.
The skipped cases require Linux/root primitives, so this is a Darwin software
fallback only. It does not establish Linux acceptance, immutable custody, or
production admission. Evidence and an independent consistency record are retained
under `parallel-batch-20261027/custody-v2-monitor-probe-affected-darwin-20261028-r2/`.

The following sections describe the v1 implementation and its previously
completed consolidated software regression. V1 remains default-off, its native
binary ABI is unchanged, and neither version supplies complete WQ-07 deployment
acceptance.

## Selected original path

After `publish_original_grants`, and before final intent or channel creation,
the same `NativeWholeScopeOwner` may explicitly call `acquire_custody_owner()`.
The child reserves exactly `.whole-scope-custody` beneath that original attempt.
The directory is root:root `0700`, with no access/default ACL. It is never a
candidate grant or part of the B descriptor allowlist. It does not change the
original attempt/U permissions. Existing names and partial acquisition failures
remain reserved; a second acquisition cannot retry the directory.

The child holds the newly acquired private directory FD plus every original
no-follow ancestor. Each consumption compares held and named device/inode/mount,
mode and owner identities. Original profile, published attempt and deadline
remain bound to the same noncopyable live parent. A DTO, numeric FD, recovered
reference, copied owner or current directory cannot select this path. The parent
closes the child's private descriptors when retiring its original acquisition.

`start_original` passes only the original private directory FD to its original
S. Existing S starts storage-only R with that same directory. The existing
`--custody-dir-fd` route, binary frames, operations and S/G/R ordering remain
unchanged. Default execution still passes `-1`; this feature adds no process,
retry, installation privilege or independent deadline.

## Original consumers and diagnostic baseline

After the original S registration ACK, the parent reads the two fixed R records:

- `scope-registration-v1.bin`: exact 925-byte WQ_STORE_REGISTER/sequence 1;
- `scope-terminal-v1.bin`: initially empty, later exact 925-byte
  WQ_STORE_EVENT/sequence 2.

Each body must match the original native binding, kernel-scope identity, target
and all three original publication descriptions. Before releasing the original
gate, registration must remain unchanged and terminal empty. After original
COMPLETE, original S exit 0 and the original remaining-deadline checks, terminal
must match the expected body before the parent marks completion.

Reads require no-follow regular root:root `0600`, no ACL, one hardlink, the same
directory mount, and exact name/FD identity before and after bounded pread.
Only the two fixed names and zero or 925 bytes are admitted. Directory enumeration
stops after the first unexpected or third name. Partial, larger, replaced,
symlinked, aliased or unstable records refuse; no parser accepts arbitrary prose
or current filenames. Filesystem latency is not hard bounded by these work/byte
bounds or by O_NONBLOCK.

The original live child exposes `NativeWholeScopeCustodyReference` only after
the registration ACK and matching record observations. Its private canonical
bytes record the original directory chain, expected registration, and observed
file identities. Those v1/v2 file pins are **ACK-bound read observations**, not
R's actual creator descriptions: the v1/v2 ABIs do not transfer creator FDs.
The explicit [v3 software contract](whole-scope-creator-fd-v3.md) implements
creator-description delivery and has passed its 34 C mechanism cases; full
WQ-07 and installed-profile acceptance remain separate work.
The trusted installation must independently retain the reference before relying
on recovery; the implementation does not authenticate a caller-made reference or
automatically persist one inside the receiver store.

`inspect_native_whole_scope_custody` consumes that independently retained baseline
and performs bounded, repeated read-only comparisons on the same directory chain.
It can report a registration prefix or normal terminal record, including after
the original execution deadline or original owner closure. This is historical
inspection, not a new execution/cleanup allowance. It creates no owner, process,
scope, signal, gate release, write, fsync, repair, retry or deadline. Public output
contains fixed states/codes and booleans; it does not echo private paths, target
identities, record bytes or arbitrary exception messages.

## V1 abnormal boundary and remaining tasks

The v1 R receives registration and **normal** terminal only. Its C abnormal
path stops independently and retires exact owned children; it does not
create a separately versioned durable abnormal event. A retained registration
prefix can therefore be inspected after interruption, but cannot establish the
abnormal trigger, stop result, complete emptiness, R ACK or exact retirement.
Even a complete normal record cannot prove an ACK that its original owner lost.
All read-only recovery outputs retain cleanup unknown, durable-acknowledgement
verification false and all cleanup/admission/publication authorities false.

Missing/partial data, storage death, blocked fsync and expired original ACK remain
unknown. No cleanup wait or persistence grace is added. Full abnormal event/ACK
semantics, R creator-FD transfer if required, independently authenticated reference
retention, blocked-storage fault acceptance and installed root/U/cgroup deployment
remain explicit follow-up work requiring their own reviewed protocol boundary.
WQ-06 finite writer enclosure and original monitor completion are separate.

## Consolidated validation selection

`tests/test_native_whole_scope_custody.py` covers default refusal, constructor and
copy boundaries, actual private FD creation/retirement, normal/prefix consumers,
fixed names and byte limits, replacement, symlink/hardlink/permission drift,
partial/invalid terminal data, original binding/deadline/directory drift,
before/after read races, and post-expiry read-only behavior. Linux fixtures project
root/ancestor installation metadata at an explicit fixture boundary; files,
mount observations, original descriptors and inode links are real. These fixtures
do not prove installed credentials, R fsync/ACK, original cgroup completion, G1,
hard disconnect or production acceptance. macOS skips the Linux mechanism cases.
The tests were executed in the consolidated runs recorded below; installation
acceptance remains separate.

## Previous v1 consolidated execution and affected follow-up

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
