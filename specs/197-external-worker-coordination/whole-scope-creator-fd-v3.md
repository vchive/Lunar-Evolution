# Whole-scope creator-FD v3: implemented software contract

Status: **software implemented; focused Linux mechanism regression passed;
installed-profile acceptance remains open** (2026-10-28).
This continuation follows `whole-scope-private-custody.md` and the original
ownership graph in `whole-group-quiescence-backend.md`. It delivers R's actual
record-creating descriptions through the existing R → S → C path. It does not
close WQ-07, add a G → R route, change process parentage or establish production
acceptance. Parent review approved the explicit operations/framing and trusted
creator-FD route before implementation. The 34 actual C transport/adoption cases
and 73 Python creator-custody cases have passed in the concentrated Linux batch
recorded below. This closes this slice's software implementation and mechanism
regression, not the overall WQ-07 or deployment acceptance.

## Selection and unchanged paths

The same original live `NativeWholeScopeOwner` may explicitly select
`linux-whole-scope-private-custody-v3` before final intent/channel creation.
Its create-only directory is `.whole-scope-custody-v3`, containing exactly
`scope-registration-v3.bin` and `scope-terminal-v3.bin`. Repeated selection,
existing names, partial acquisition or unsupported v3 refuse without retry.
The selected S entry is `--supervisor-custody-v3`; no negotiation or fallback is
permitted. The installed image/profile hashes still identify the actual original
sealed supervisor and fixed native installation.

Default execution, custody v1 and explicitly selected custody v2 keep their
current modes, bytes, operations, file names and consumers. In particular, v2
registration remains version 1/operation 14 and its ACK remains unchanged. The
bootstrap, target allowlist, C/S execution control, scope acquisition, G stop
path and original G/R exact-child relationships do not change for this slice.

## Exact wire and record forms

All v3 custody packets use the existing packed 925-byte `wq_message_t` context:
little-endian magic `0x3151574c`, version **3**, operation, sequence, exact
`fd_count`, zero reserved, original binding, original scope identity, original
target PID and all three original publication descriptions. Numeric descriptor
values are never encoded in packet bodies. The following previously unused
operation numbers were approved in parent review for this explicit profile:

| Operation | Route and form | Sequence / rights | Required action |
| --- | --- | --- | --- |
| 22 `WQ_V3_STORE_REGISTER` | S → R, 925 bytes; also the exact registration file body | 1 / 0 | Validate original context, persist registration and original empty terminal identity. |
| 23 `WQ_V3_REGISTER_CREATORS` | R → S, 925 bytes | 1 / exactly 2 | Copy the registration context, replacing operation and count; attach registration then terminal original creator descriptions only after durability checks. |
| 24 `WQ_V3_CONTROLLER_CREATORS` | S → C, 925 bytes | 2 / exactly 2 | Copy that same original registration context, replacing operation/sequence/count; forward the actual received descriptions. Replaces only this profile's C-facing registration ACK. |
| 25 `WQ_V3_STORE_NORMAL` | S → R, 941 bytes; exact normal terminal file body | 2 / 0 | Original context plus the fixed 16-byte terminal extension below. |
| 26 `WQ_V3_STORE_ABNORMAL` | S → R, 941 bytes; exact abnormal terminal file body | 2 / 0 | Same extension, with actual abnormal observations only. |
| 27 `WQ_V3_TERMINAL_ACK` | R → S, 941 bytes | 2 / 0 | Exact accepted terminal bytes, replacing operation only; binds the extension as well as the 925-byte context. |

The 941-byte terminal/ACK extension is little-endian `uint32 reason`,
`uint32 facts`, `uint64 observed_monotonic_ns`. Reasons and facts retain the
v2 meaning: reasons 0 normal, 1 controller lost, 2 deadline, 3 receiver fault,
4 protocol; bits 0 stop attempted, 1 original scope empty observed, 2 original B
exit observed, 3 original G exact-child reaped. Normal requires reason 0 and
exactly facts 10; abnormal requires reason 1–4 and the stop-attempted bit.
Unknown bits or a timestamp outside `0 < observed < original deadline` refuse.
There is no new supervisor-death reason or self-reaping fact.

Every packet must match the original launch/intent/profile/image/deadline,
scope, target and publication bytes for this exact attempt. Transport checks
alone do not establish those bindings. Each expected operation is consumed once
at its fixed phase; replay, duplicate, conflicting or out-of-order packets
refuse. A v3 receiver is not a permissive extension of the v1/v2 parser.

Custody v3 uses the existing original anonymous S/R and C/S SOCK_SEQPACKET
channels. The C/S release and completion messages retain their existing v1
framing and sequences: only the v3 creator-delivery response above is added to
the selected original registration consumer. There is no public/path socket,
worker-selected descriptor route or new channel to G.

## Creator provenance and lifecycle

1. R validates the actual borrowed private directory and creates both fixed
   files with `O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`, mode 0600.
   R retains these actual creator descriptions throughout its finite operation.
   A later path open, same inode lookup or caller-provided FD cannot substitute.
2. R validates the original registration packet and writes its exact 925 bytes.
   Before sending operation 23 it fsyncs the registration file, the still-empty
   terminal creator file and the original directory, then repeats the identity,
   name, ACL, size and original-deadline checks. Registration is 925 bytes;
   terminal is exactly zero. Both files must exist durably before delivery.
3. R attaches the original two creator descriptions using SCM_RIGHTS in the
   fixed registration/terminal order. S receives with MSG_CMSG_CLOEXEC, validates
   the actual descriptors and context, and holds them in its original cleanup
   region before doing any operation that can fail.
4. S forwards only those actual received descriptions in operation 24. It does
   not reopen the names or manufacture creator pins from a current record. Its
   transport copies may close after successful submission; queued rights are
   not evidence that C consumed the message.
5. C's socket receiver owns both actually received descriptors until its
   unconditional `finally` retirement, including failures before the child
   method can start. The same original live custody child retains internal
   `dup` copies of those exact received OFDs once; failure closes only its
   internal copies. This does not reopen names or change creator provenance.
   The child validates their creator-backed objects against its already-held
   directory chain and original registration, and retains them until that live
   owner's retirement. The transfer is an internal ownership handoff, not a
   public constructor from numeric FDs or a serialized reference.
6. C cannot send its existing release message until creator adoption,
   registration validation, terminal-empty checks and all existing original
   registration/observer checks succeed. S still requires both existing
   independent release gates. Partial delivery/adoption refuses the gate.
7. Normal terminal persistence still follows genuine original scope emptiness
   and S's exact G wait. Abnormal S persistence still follows the original stop
   attempt and G retirement path. R writes 941 bytes only through its retained
   terminal creator FD, fsyncs file and directory, rechecks all bindings and the
   original deadline, and only then sends operation 27. S must consume its exact
   original ACK and retain its existing exact R wait requirement.
8. C's normal completion reads through its retained creator descriptions and
   retains all existing original COMPLETE, B/S status and deadline gates.
   It never derives a lost ACK or native completion from file contents.

SCM_RIGHTS duplicates refer to the original open file descriptions; their offset
and file-status flags are shared. S/C use bounded `pread` exclusively, never
`read`, `lseek`, `F_SETFL`, write, truncate, chmod or xattr mutation on these
descriptions. Their only mutations are per-descriptor CLOEXEC and close.
O_RDWR therefore reaches only trusted R/S/C; this is a code/ownership boundary,
not a claim that S/C are kernel-denied writes. No descriptor is a candidate
grant or is inherited by B, T, G, a worker, shell or interpreter child.

## Original identity and deadline checks

The original root:root 0700 private directory, all no-follow ancestors and their
held/named device/inode/mount/mode/owner identities remain bound to the same
original parent acquisition, published attempt and absolute monotonic deadline.
Do not replace the ancestor chain with a current path or a serialized identity.

For both creator descriptions at every adoption/consumption boundary, and for
R before/after write and fsync, require:

- Actual regular root:root 0600 object, CLOEXEC, expected O_RDWR access and no
  unexpected status flags; no access/default ACL. Actual `fgetxattr` must return
  ENODATA for each ACL; mode alone is insufficient and ENOTSUP is not absence.
- One hardlink, same original directory device/mount, distinct registration and
  terminal objects, and exact fixed-name ↔ held-FD device/inode/type/mode/owner
  binding. Compare original pins before/after reads, including actual held size
  and named size; never use a name lookup to establish creator provenance.
- No alias/collision between either record and any image, publication, scope,
  grant, channel, stdio or other reserved descriptor role. The declared two
  roles and both acquired object identities must be distinct.
- Exactly the two fixed names. Registration remains the original 925 bytes
  unchanged. Terminal is zero before release and exactly 941 matching bytes
  after the selected terminal operation; partial, larger, replaced or unstable
  objects refuse. Terminal timestamps/size/mtime evolve only through R's one
  expected write; registration creator identity and bytes remain fixed.
- S retains its first actual empty-terminal stat pin through forwarding, and R
  retains the corresponding pin from creation until its one terminal write.
  Compare device/inode/mode/owner/link-count/size/mtime/ctime as well as the
  existing mount and ACL checks. A write followed by truncate back to zero or
  an unexpected timestamp change cannot establish an untouched empty terminal.
- R also retains the first full registration stat pin after its completed write
  and fsync; S retains its first full pin from the actual creator ACK adoption.
  Each compares that same pin across its remaining stages: R before/after
  creator delivery and terminal persistence, S before/after controller
  forwarding, and C across release/completion. Registration mtime/ctime may not
  drift after this observation even if a later write restores identical bytes.
  S still closes its transport copies after forwarding; R's retained original
  creators provide the later terminal-persistence checks without a name reopen.

Every allocation, send/receive, adoption, read, write, flush, revalidation,
release and retirement uses the same original remaining deadline before and
after the operation. No operation introduces a receiver/startup/cleanup budget
or retry grace. Regular-file reads/writes/fsync can block; byte bounds and
O_NONBLOCK do not establish a hard syscall completion bound. Late return grants
no ACK, gate release or positive terminal. R never holds scope, pidfd, gate or
lifeline-writer authority, so its storage cannot defer G's independent stop.

## Refusal and descriptor cleanup

Receive at most the exact expected frame plus one overflow byte, bounded
ancillary storage and the exact declared rights count. Reject short/oversized
frames, MSG_TRUNC, MSG_CTRUNC, unknown ancillary data, extra/repeated rights
headers, count mismatches, aliases, invalid identities, wrong context/phase and
unexpected EOF. Inventory every actually delivered SCM_RIGHTS descriptor before
raising any validation error, including rights later in the ancillary list.

On every error, close **all actually acquired rights in place** before returning
or propagating the original error. This includes partial receipt, later-invalid
ancillary entries, failed identity checks, partial wrapper construction and
failed C adoption. Ownership may move to the original cleanup region only once;
no numeric descriptor is both caller-owned and child-owned. Never close sender
numeric values from a packet. Retain partial files and the failed original
attempt; do not replace R, reopen creators, repair records or retry acquisition.

Loss before operation 24 consumption leaves registration/startup unknown. Lost
terminal ACK, R death/blockage, original deadline loss or S death remains
unknown. The existing G may still attempt stop after S death, but this slice
creates no G → R event or replacement original reaper.

## Reference and authority boundary

A new v3 reference may record identities and registration bytes derived from the
actual creator-delivered descriptions. Unlike the older ACK-bound observations,
those original pins have creator-delivery provenance within the live trusted
path. Serialized pins are not live descriptions or authority. Independent trusted
pre-gate retention/authentication remains a separate composition requirement;
returning a reference does not prove that requirement was met.

Read-only historical inspection may reopen fixed names only to compare the
independently retained original creator pins, bytes and chain. It cannot create
an original pin, prove a lost ACK, reconstruct a live owner, write, signal,
relaunch, renew the deadline or close a monitor interval. All existing
durable-ACK, cleanup, quiescence, admission, online-publication and production
authority projections stay false. This contract grants no build/input custody,
immutable-file, account-isolation or accepted-runtime claim.

## Implementation map

The implemented software and regression seams are:

- `native_whole_scope_protocol.h`: v3 operation constants and strictly
  separated registration/creator-ACK/terminal/terminal-ACK validation; retains
  existing v1/v2 validators and their exact accepted shapes.
- `native_whole_scope.c`: `--supervisor-custody-v3` selection, a storage-only
  `receiver_v3_main`, checked creator validation/delivery helpers, original S
  descriptor cleanup ownership, registration ACK forwarding in
  `run_supervisor`, and v3 persistence selection in the existing normal/abnormal
  paths. Preserves `start_guardian`/G parentage and stop authority.
- `native_whole_scope.py`: `acquire_custody_owner`/`start_original`
  explicit selection; an internal v3 creator-message receiver with complete
  rights cleanup; selected `bind_original_registration` and
  completion paths to transfer to the same original custody child.
- `native_whole_scope_custody.py`: the explicit profile/shape; internal
  one-shot creator adoption, held-description reads and provenance-bearing
  reference creation; exact `close` ownership. Historical v3
  inspection without creating a discovery/adoption constructor.
- Tests: actual C receiver and transport harnesses, v1/v2/v3 mode/FD
  bridge tests and original custody consumer/retirement faults. Cover original
  descriptors across actual SCM_RIGHTS hops; malformed/extra/aliased rights;
  partial adoption cleanup; shared offsets; identity/ACL/nlink/size drift;
  pre-gate failure; terminal binding/ACK loss and original deadline expiry.
  Same-UID/root-projection fixtures remain software fixtures, not deployment
  acceptance.

## Concentrated Linux mechanism regression

Evidence: `BASE/next-union-tmpfs-linux-20261028`, source-tree marker `e93c99f5`.
The first frozen 30-file Linux tmpfs batch completed in 48.535873 seconds:
1048 nodes, 1005 passed, 42 root-prerequisite skips and one CI JSON count
assertion failure. Product/source snapshots before and after the batch and all
259 original dependency origins matched. The CI metadata count correction and
its focused follow-up are tracked in `HANDOFF.md`; this record does not turn
that first aggregate result into an all-green batch.

Within that batch, all 34 C creator-transport/adoption cases, all 73 Python
creator-custody cases and all 34 recipe cases passed. C compilation, actual
SCM_RIGHTS on both R → S → C hops, original OFD offsets, real file/ACL/fsync
faults, full registration and initial-empty-terminal stat pins, malformed-rights
retirement, exact child waits and the original deadline were exercised.
The C harness projects root uid/gid metadata while using real kernel/file/FD
operations; Python cases use local same-UID fixtures. No real cgroup/root-profile
deployment, distinct-account enforcement, candidate case, remote evaluator or
production acceptance is established by these passing mechanism tests.

No new external service, account, evaluator, privileged installer, backend
selection or target descriptor is part of this proposal. G → R S-death
diagnostics, terminal-source arbitration and independently surviving exact
reaping require a separate reviewed contract before any implementation.
