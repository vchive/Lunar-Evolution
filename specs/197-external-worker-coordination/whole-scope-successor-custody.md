# Whole-scope successor custody v4: original parent, arbitration and retirement

Status: **software implementation authored; prior mechanism regression passed;
strict native total-FD follow-on authored, awaiting its consolidated regression;
installed acceptance remains open** (2026-10-28).
See [validation.md](validation.md) for retained failed runs, the final 43-node
ownership supplement and the limits of the current software evidence.
This is the selected continuation for the S-death part
of WQ-07. It replaces the ownership graph only when explicitly selected. The
existing v1, v2 and v3 modes, wire formats, filenames, parentage and consumers
remain unchanged. In particular, [creator-FD v3](whole-scope-creator-fd-v3.md)
continues to report S death as unknown.

The new graph supplies an actual surviving original parent, not a pidfd-backed
claim of reaping. Q is a finite, non-storage coordinator and exact-child reaper.
It is not a daemon, remote scheduler, replacement controller or successor that
can be reconstructed after failure. Losing Q remains unknown.

## Explicit selection and installation

The lifecycle selector is `linux-whole-scope-successor-custody-v4`, default off.
The same live original native owner must select it before final launch/intent,
any child, channel or custody acquisition. There is no mode negotiation,
automatic fallback, profile promotion or retry. Partial selection permanently
reserves that attempt. A caller-supplied FD, profile string or saved reference
cannot construct a selected live owner.

The selected installed profile is the separate fixed
`/etc/lunar-evolution/whole-scope-successor-v4.profile`: root-owned, no writable
ancestor, no ACL, original no-follow chain and bytes pinned as for the current
installation. It uses a version-4 profile header and the explicit successor
flag; the existing version-1 profile must not parse as this profile. Its fixed
credentials, finite roots, namespaces, sealed bootstrap and supervisor image
digests retain the existing restrictions. Q/S/G/R execute only the original
sealed supervisor image; separate fixed v4 entry modes distinguish their roles.
B uses a separate v4 whole-scope bootstrap mode. No role uses a path re-exec,
shell, interpreter or a worker-selected image.

The create-only directory is `.whole-scope-successor-v4`, containing exactly
`scope-registration-v4.bin` and `scope-terminal-v4.bin`. Acquisition retains the
actual private root:root 0700 directory and no-follow ancestor descriptions;
existing names, a partial acquisition or another mount refuse. Neither directory
nor record is a candidate grant. V4 registration and terminal records are not
accepted by any v1/v2/v3 consumer.

## Original process graph and actual wait ownership

```text
C: original Python controller
|-- B: original sealed bootstrap, outside execution scope
|   `-- T: trusted pre-exec target, atomically in the original execution scope
|       `-- candidate descendants/threads, in the same closed scope
`-- Q: original finite coordinator/reaper, outside execution scope
    |-- S: original primary observer/stopper, outside scope
    |-- G: original independent emergency observer/stopper, outside scope
    `-- R: original storage-only receiver, outside scope
```

C exclusively owns its actual B and Q `Popen` children. Q is single-threaded,
has normal `SIGCHLD` semantics, and creates S, G and R directly with
`clone3(CLONE_PIDFD, exit_signal=SIGCHLD)`. Q exclusively retains each returned
child pidfd until its own successful, consuming
`waitid(P_PIDFD, original_fd, ..., WEXITED | WNOHANG)` obtains actual code/status.
There is no `WNOWAIT`, generic `waitpid(-1)`, `CLONE_PARENT`, `CLONE_THREAD`,
subreaper adoption or competing wait owner. `ECHILD` is unknown, not success.

Q owns S/G/R independently of C or S survival. S and G receive only observation
copies of selected original pidfds. They cannot wait/reap each other or R. The
copy of B's pidfd derives from C's exclusively wait-owned, unreaped original B;
it permits original exit observation and stop, not Q/S/G reaping B. B alone
owns its original T exact-child wait. The scope-empty observation does not prove
that every descendant zombie has been reaped.

Q cannot attest its own retirement. A live normal C consumer must still consume
the original Q result and perform C's actual exact Q wait, actual B wait and
original deadline checks. If C dies, Q may complete finite stop, storage and
its own S/G/R waits, but no persisted record supplies C's missing Q/B wait or a
surviving Python monitor owner. If Q dies, S/G may still stop, but no replacement
Q, G-to-R pidfd transfer, historical replay or external init reaping supplies
the lost original S/G/R wait owner.

## Scope authority, B gate and late-enrollment closure

Q creates the original root-owned cgroup-v2 leaf using the installed original
delegation. It opens separate original `cgroup.events` descriptions and kill
writers for Q, S and G; no two readers share an open-file-description offset.
All three retain the original scope/mount/namespace pins and use the reviewed
strict `cgroup.events` parse, recursive `populated=0` observation and existing
identity checks. Scope controls never reach R, T or a candidate worker.

Q owns the B enrollment endpoint and the B lifecycle endpoint. This profile has
no S-to-B endpoint: the old S role is not secretly impersonated on a v1 channel.
Q sends the original scope description and Q-lifeline reader once to B. B atomically clones T into
that original scope, closes its only scope description, consumes T's trusted
pre-exec ready exchange and returns T's original clone3 pidfd plus enrollment
context. T has closed the scope description and every non-allowlisted FD before
reporting ready. Q validates membership and the original binding, sends one
enrollment ACK and closes its enrollment transport endpoint. No later operation
can supply another enrollment copy.

The two original release conditions remain independent:

1. C is the sole writer of the host release pipe. Q/S/G/R/T hold no writer copy.
   C may write its one release byte and close only after all original grant,
   publication, reference/observer, monitor-arming and v4 creator-adoption checks.
   A live extra writer, wrong byte, missing EOF or partial failure refuses.
2. Q is the sole sender of the v4 native `RELEASE_PERMIT` to B, through the
   original Q-B lifecycle pair. B sends its native release request only after
   consuming the host byte plus EOF. Q requires C's distinct original v4
   release request, all original ready/adoption ACKs, target membership and
   revalidated objects before granting its one permit.

Before permitting this sequence Q also transfers observation-only copies of its
actual S/G/R clone3 pidfds to B on a separate fixed three-rights message, and
consumes B's fixed ACK. B retains them, never passes them to T, and never waits
on them. After consuming a queued Q permit and immediately before writing T's
gate, B rechecks original C/Q lifelines, S/G/R pidfd liveness, D and cutoff.
Failure closes the gate and enters original stop/unknown; an earlier queued
permit does not override a newly observed peer death. These before/after checks
are not an atomic OS guarantee against a death concurrent with the gate write;
any observed loss after the write requires emergency stop and an unknown result.

B alone holds T's private pre-exec release writer; T holds only its reader. B
releases exactly once after both conditions and closes that writer. Q never
holds this writer. C, S, G and R cannot write either B-owned T gate. Candidate
code executes only after T closes both private gate endpoints.

Before normal retirement, Q requires the original B `TARGET_DONE`, T's original
pidfd exit observation, the already-closed enrollment transport and its own new
original recursive empty read. The trusted fixed B is then waiting only for
Q's final result and has no scope FD or second-clone operation. Before abnormal
empty observation, Q/S/G close/refuse every enrollment and release operation,
send `SIGKILL` through B's original pidfd and observe B exit; only then can
scope kill followed by a fresh recursive empty read close the late-join race.
Signal submission, B EOF and the first empty read alone are insufficient.

## Fixed private channels and descriptor ownership

Q creates every child transport and lifeline before cloning any child. Each
child executes a fixed close-all-except allowlist before its first ready
packet. No ready or gate release is valid while any unintended writer/endpoint
could mask EOF. Each received right immediately enters an unconditional local
cleanup region before parsing, validation, allocation or wrapper construction.
All roles must have distinct FD numbers and distinct actual objects where the
role requires it; aliases with stdio, images, grants, sinks or other channels
refuse. Numeric descriptors in packets are never used as handles.

| Original object | Owner and intended recipients | Retirement/close boundary |
| --- | --- | --- |
| B/Q `Popen`, original B pidfd | C; B pidfd copies to Q then S/G | C excludes auto-reap/competing waits through transfer; C exact-waits B/Q. Q/S/G never claim B reaping. |
| S/G/R clone3 pidfds | Q exclusively wait-owns; S/G and B get only the peer/R observation copies they require | Q closes an original only after its exact wait or final unknown cleanup; no close on an observation packet. B's copies never reach T; copies close at their owner's retirement. |
| Installed profile, sealed images, actual original publication descriptions | Original acquisition; Q retains all original inputs, S receives its exact read-only observation set | Pin bytes/metadata before use and every gate/result boundary. No image, publication or custody record reaches T. Only bounded `pread` on shared publication descriptions. |
| Delegation and original scope directory | Q; distinct scope observation/stop copies to S/G; one enrollment-only copy to B | B/T close before ENROLLED. Q/S/G retain through their own empty/stop work. No scope control in R. No reopen from a pathname/PID after loss. |
| Q/S/G original event descriptions and kill writers | Q opens three separate sets before child launch | Each intended owner alone reads its event OFD. Each original remains held through that owner's finite stop/observation. No storage operation precedes required emergency stop. |
| C lifeline | C sole writer; B/Q/S/G readers | Every other inherited writer closes before readiness. C closure/death is abnormal until commitment. R receives no writer or C liveness authority. |
| Q lifeline | Q sole writer; B/S/G/R readers | C/B/children hold no writer. B checks its actual reader before releasing T. Q loss triggers S/G emergency stop; R abandons uncommitted work. It cannot cancel an already-started syscall. |
| S lifeline | S sole writer; Q/G readers | Q/G distinguish Q-authorized normal S exit from unexpected loss using their local state, not EOF alone. R/C/B hold no writer. |
| G lifeline | G sole writer; Q/S readers | Q/S distinguish Q-authorized retirement from unexpected loss. S remains a live stopper through Q's G exact wait. |
| C-Q control, Q-B enrollment, Q-B lifecycle | The two named peers only | C drops B-Q inherited copies after spawn; every S/G/R/T closes them. Enrollment closes after one enrollment ACK; lifecycle remains through final result. |
| Q-S and Q-G role control pairs | Q plus the named child only | Carry init/context, target-done, stop/normal-exit requests and source proposals; close only after original child retirement/unknown. No storage ACK is a stop prerequisite. |
| S-R and G-R proposal pairs | Exactly the named source and R | Q closes its temporary endpoints after the two children inherit/receive theirs; all other children close them before READY. Each source sends at most its one fixed proposal. R never sends release, stop or wait authority. |
| Q-R control/commit/ACK pair | Q and R only | Registration/creator delivery, Q-only proposal if required, one commit and full terminal ACK. R has no Q-S/Q-G/control endpoint. |
| R record creator descriptions | R creates/retains originals; actual duplicates R→Q→C only | Q/C use `pread`; no write, seek, truncate or `F_SETFL`. Q retains its actual received descriptions through final result; C retains same-OFD duplicates in the original custody child. |
| T ready/release pipes | B/T only, opposite fixed ends | All other writers close before native readiness. B closes release after its one permitted write; T closes ready/release before candidate exec. |

Q uses fixed bounded nonblocking poll loops and never performs R's record
creation, write, truncate, fsync or repair. Original scope/profile metadata
checks and kernel calls still are not advertised as hard real-time operations.
R cannot retain a scope FD, pidfd, image used to launch another helper, kill writer,
lifeline writer, host gate writer or B control endpoint. S/G never receive R's
creator descriptions or any terminal-write operation. R runs in the originally
verified sealed image inherited from Q; any initial image bootstrap FD closes
before R READY and cannot become an executable helper-launch capability.

## Acquisition and readiness order

Every step consumes the same original deadline. A failure at any step leaves
the candidate gated and enters cleanup of actually acquired objects; there is
no new graph or replacement child.

1. C acquires the original installed profile, sealed images, publisher/grants,
   finite private custody directory and absolute deadline D. It reserves the
   v4 lifecycle once. Its original B launch remains single-threaded/exclusive-
   wait through actual original B pidfd transfer. A Python event reader must
   not start before that transfer.
2. C launches the paused original B and Q with separate fixed v4 modes. C
   retains actual `Popen` ownership and sends Q its actual original B pidfd,
   original binding, installation inputs and private custody directory. Q
   validates before acquiring any scope. A C/Q loss or transfer failure here
   refuses both release conditions, even if no G exists yet.
3. Q creates the original scope, three independent event/kill sets and the
   complete finite channel/lifeline graph. Q clones S, then G, then R as direct
   children. Every child first closes inherited non-roles and remains paused
   in role initialization. Q retains each actual clone3 output in an owned
   slot before any subsequent clone/allocation can fail.
4. Through the original Q-child pairs Q transfers actual scope/event/kill
   descriptions and only the original pidfd observation copies required by each
   role. S receives original B/G/R observation pidfds, G receives B/S/R; R
   receives no pidfd. Target and publication descriptions are transferred to
   S only after enrollment/registration. Every transfer has a fixed role/count
   and ACK. Q lifeline remains armed before S/G can report role READY.
5. Q consumes distinct original `S_READY`, `G_READY`, `R_READY`. Each READY
   confirms actual role initialization and closed non-role descriptors; it does
   not claim the other child was reaped or the candidate is safe. Q requires
   all child pidfds still live before releasing any enrollment capability.
6. Q performs the one B enrollment described above. It binds the original T
   pidfd, scope, target and all three actual publication descriptions. Q and S
   receive/validate their full immutable registration context; G receives that
   same fixed context through its original Q channel. Q transfers actual S/G/R
   observer pidfds to B and consumes B's ACK before registration can be ready.
   No old partial context
   may authorize a later proposal. All role ACKs are required.
7. Q sends registration to R. R creates both fixed files with original
   `O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC` descriptions, writes the exact
   registration, fsyncs registration, empty terminal and directory, then checks
   original pins/deadline and sends both actual creator OFDs to Q. Q validates,
   holds them immediately, and forwards those same descriptions to C. C's
   original receiver retains incoming rights through unconditional `finally`;
   its original custody child retains internal same-OFD duplicates once.
8. C completes original registration/observer/reference checks, adopts both
   creators and sends a distinct original `CREATORS_ADOPTED` ACK to Q. Q checks
   registration unchanged and terminal still empty using its own retained
   actual creators. Q sends `REGISTERED_READY` only after all role ACKs and
   original object checks. No queued creator packet is presumed consumed.
9. Only now may C arm its original diagnostic monitor, if selected, before
   either release condition. The monitor remains diagnostic unless WQ-06's
   independent enclosure/acceptance contract is separately implemented. C then
   completes its host release and sends its Q release request. Q rechecks C,
   S/G/R, original handles, scope membership, installation, grants/publications,
   creator pins, original D and cutoff before its one B permit.

Failure before complete registration cannot fabricate missing target or
publication context. R may leave empty/partial private files; no terminal is
valid for a pre-registration attempt. A subsequent run must not reuse them.

## Separate v4 protocol and evidence records

All transports are original anonymous `AF_UNIX/SOCK_SEQPACKET` pairs, nonblocking,
CLOEXEC, with strict count, `MSG_CMSG_CLOEXEC`, truncated-control rejection and
actual role validation. V4 uses a separate parser and wire version **4** for
every lifecycle/custody operation. No v1 release/complete, v2 ACK, v3 creator
packet or version negotiation is accepted by that parser.

The fixed common context contains the original launch/intent/target/image/
profile digests, D, fixed credentials/groups, scope identity, target and all
three publication pins. Its packed fields and pre-registration zero rules
follow the existing 925-byte context layout; version and operation handling
are separate. Role initialization carries a fixed role identifier and exact
rights schema; no variable capability map or caller-defined role is allowed.
The exact candidate operations/layout in Appendix A must be frozen in the
implementation review before the first C/Python ABI change. No existing ABI is
modified by this document.

The terminal envelope must retain these exact distinct objects, rather than
overload the old v3 facts:

| Object | Fixed fields and source |
| --- | --- |
| `SourceProposal` | Common full original registration context; source `S`, `G` or `Q`; one proposal sequence; observed trigger and independent stop/empty/B-exit/target-exit facts; original observation time. Source is authenticated by its distinct original channel, not the source integer. Unknown bits/fields refuse. |
| `TerminalCommit` | Common full context; decision sequence exactly 1; exact complete selected `SourceProposal` bytes; Q's decision `NORMAL` or `ABNORMAL`; Q's fixed reason and original commit time; Q's own fresh scope-empty/B-exit observations; separate `S_WAITED` and `G_WAITED` bits and their actual consuming `si_code`/`si_status` values. Absent wait bits require zero status fields. |
| `TerminalAck` | Exact complete `TerminalCommit` bytes, replacing only the outer operation with ACK; no detached digest or shortened acknowledgement. |
| `QResult` | Exact committed bytes and full ACK consumption, plus Q's actual R wait code/status and final original checks, on the original C-Q/B-Q channels. It never claims Q's own reaping or B reaping. |

Source proposals report source observations only. S/G never set Q's wait bits,
never claim their own retirement, and do not combine a source's empty read with
another source's trigger. Q validates the full source packet from its original
source channel and independently validates the facts it adds. R compares the
embedded proposal **byte for byte** with the one actually received through its
separate original S-R/G-R pair (or earlier original Q-R proposal for source Q).
A matching hash or same source label is insufficient. R never merges S and G
proposal fields into one invented observation.

Fixed reasons distinguish normal, C lost, execution cutoff/deadline, R fault,
protocol/original-object fault, S lost and G lost. A source's observed trigger
and Q's decision reason remain separate fields. In particular, a Q request to
G to stop because R died does not make G claim it directly observed R death.
Normal requires source S, a normal proposal, Q's own original empty observation,
actual Q waits of S and G with `CLD_EXITED/status=0`, all required current
objects/pins, a live C and B's original normal target-done state. Abnormal
records preserve each actual fact independently; no absent exact wait becomes
true from a pidfd exit or scope emptiness. R's own wait and Q's own wait cannot
be included as already-acquired facts in a record R is still writing.

The normal commit's `B_EXIT_OBSERVED` bit is necessarily false and any unused
B-status storage is zero: B is still waiting for Q's final result. Normal uses
the original B `TARGET_DONE`, original T pidfd exit and a fresh recursive empty
read; it must not wait for B exit before committing. Abnormal closure instead
requires B exit observation before claiming that the late-enrollment route and
scope have been stopped. Q never turns either B observation into a B wait fact.

## Normal finite state machine without a wait cycle

1. While S and G remain live independent stoppers, Q consumes original B
   `TARGET_DONE`, observes T exit and a fresh original empty scope, then sends
   the original B-done context to S. S independently observes that same original
   scope empty and validates its original target/publication context.
2. S constructs one normal `SourceProposal`, submits the exact same packet on
   S-R and S-Q, then remains live in `NORMAL_PROPOSED`. It continues to observe
   C/Q loss, original drift and D. Sending a proposal does not retire S and
   does not authorize R to write a terminal.
3. Q validates the original S proposal and its own new empty read, then sends S
   `PREPARE_NORMAL_EXIT`, bound to those exact proposal bytes. S ACKs entering
   `WAIT_NORMAL_EXIT`; it remains a stopper and tolerates only the subsequent
   Q-authorized G retirement. Unexpected faults still stop/refuse.
4. Q sends G `RETIRE_NORMAL`, bound to the full original context and S proposal.
   G performs its own original empty read, validates the request and exits 0.
   Q consumes G's actual exact wait. A proposal, EOF or pidfd readiness cannot
   replace that wait. Any nonzero G status cancels the uncommitted normal path.
5. Q sends S `EXIT_NORMAL` only after G's successful exact wait. S checks its
   prepared state, original context, own empty view and D, then exits 0. Q
   consumes S's actual exact wait. S abnormal exit, interruption or missing
   wait forbids normal commitment even if its normal proposal was complete.
6. Q makes a final original empty/object/publication/creator/deadline check and
   locks exactly one normal `TerminalCommit`. It sends that packet to R. R
   persists only after matching the original S proposal as specified below.
7. Q consumes the exact full terminal ACK and actual R exact wait with exit 0,
   then checks original scope, registration and terminal creator bytes/pins
   again. Only then does Q send one final v4 result/COMPLETE to B and C and exit
   0. B finishes its original native sequence and exits. C must consume the
   original result, validate its actual creators, exact-wait B and Q, and check
   D before marking this live native operation complete.

Q never waits for a G that is waiting indefinitely for Q death, and never waits
for S exit before sending S's explicit normal-exit request. S/G retirement is
not storage-ACK dependent. Once both have retired, the original execution scope
is already empty, no candidate can fork, and B's late-enrollment capability is
closed. Q retains its independent original event/kill set through R's possibly
blocked storage and its own final checks.

## Abnormal S-death path and fallback source

S death is detected by G through its actual original S pidfd and S lifeline,
with no authorized normal-exit state. Q independently consumes S's actual child
wait. G first closes/refuses candidate release, stops B via its original pidfd,
observes B exit, attempts the original scope kill and makes its own fresh
recursive empty observation within D. G then constructs one abnormal proposal
containing only its actual trigger/facts, and submits the exact same packet on
G-R and G-Q. These are bounded nonblocking submissions **after** the emergency
stop attempt. R's blocked storage or full socket cannot hold up that stop.

G remains a stopper in `ABNORMAL_PROPOSED` until Q's explicit retirement request
or D/Q loss. Q validates the original G proposal, its own S exact wait and its
own original scope state. Q sends `RETIRE_ABNORMAL` after the required original
empty observation; G rechecks and exits with the fixed abnormal status. Q
consumes that exact G wait and records the actual code/status separately from
S's status. Only Q can then lock and send the abnormal commit selecting that
exact G proposal. S's earlier normal proposal, if any, is left unused.

If G dies or its proposal route is unavailable, Q still has its own independently
opened event/kill handles and original B pidfd. Q performs its own stop/empty
work and may construct source **Q**, sends that fixed proposal to R before its
commit, and records only Q's actual observations/waits. It cannot relabel its
packet as source G, reconstruct missing G observations, or claim it will reap
itself. An abnormal diagnostic may omit a not-yet-acquired S/G wait fact; Q
continues its actual child-retirement attempts within D, but the locked
historical record never updates itself to claim later facts. A live completed
S-death custody outcome requires both actual S/G waits, full R ACK and R exact
wait; any missing fact leaves that live outcome unknown.

If S dies before scope/handles/context/READY transfer completes, neither release
condition may pass. Q stops with whichever original handles it actually owns
and consumes only its actual child waits. A partially initialized G is not
presumed to have stop authority. Without full original registration, R leaves
only partial/prefix files and no valid terminal; there is no invented context,
retry, successor child or host fallback.

## One terminal writer, one decision and storage ACK

R is the sole file writer. Q is the sole decision source. S/G proposals are
in-memory pending observations at R and never authorize terminal writes.
There is one accepted proposal per source, with at most the fixed three-source
set; duplicates, conflicting packets, extra rights and out-of-phase messages
refuse rather than grow a queue. Q consumes a bounded set of control messages
and detects source/peer failure between each nonblocking attempt.

Q's local decision state is monotonic:

```text
UNDECIDED -> LOCKED_NORMAL | LOCKED_ABNORMAL -> SENT -> ACKED -> R_WAITED
                  \-----------------------------> UNKNOWN
```

Q locks the exact entire commit bytes before the first send attempt. It never
unlocks, changes source/reason/facts, sends a second distinct decision, retries
the attempt or gives another process commit authority. A later C death, R
failure, rejected/late ACK or lost deadline cannot rewrite a committed normal
record as abnormal. If a new fault occurs after locking but before successful
submission, Q abandons unsent work as unknown; it does not construct a second
commit. EAGAIN/EINTR may retry submission of the same one packet within the
original finite loop, before any successful submission, with current fault and
deadline checks. An uncertain send outcome remains unknown, not a second send.

R accepts one original Q commit after complete registration and a byte-exact
match to the selected source's actual original-channel proposal. It checks the
two original creators, full current registration pin and original empty terminal
pin before writing. R writes exactly the fixed commit bytes through its original
terminal creator, fsyncs terminal and original directory, then repeats full
metadata/name/mount/ACL/bytes/deadline checks. Only after those operations does
R send the full `TerminalAck` to Q and exit. There is no terminal rewrite,
append, truncate-based repair, alternate filename or late fsync allowance.

Q and C retain R's actual creator descriptions from R→Q→C delivery. The current
v3 protections are mandatory here too: strict flags/CLOEXEC/ACL, distinct
regular root:root 0600 objects, nlink 1, exact fixed names and mount, complete
before/after stat snapshots and bounded `pread` without changing shared OFD
offset/status. Registration's first full durable pin and terminal's original
empty full pin survive all transfers. Actual rights close on every partial
receipt/adoption/interruption. A path reopen cannot recreate creator provenance.

Lost ACK is unknown even if terminal bytes exist durably. R exit is not an ACK.
R's own record cannot attest R's actual exact wait. Q consumes full ACK and
exact-waits R as separate facts. Q death may occur **after** commit submission,
and R may already be inside a write/fsync; therefore Q death does not imply
that no terminal bytes can appear. Such bytes cannot reconstruct missing Q
ACK consumption, Q result, C wait or cleanup authority.

## One original deadline and the existing cleanup reserve

The original acquisition supplies one absolute monotonic D unchanged to C,
B, Q, S, G and R. `execution_cutoff = D - 250,000,000 ns`, preserving the
existing 250 ms reserve **inside** D. Initial acquisition must reject an already
exhausted cutoff. Setup, all role transfers/readiness, registration durability,
creator adoption, monitor arming and execution share that cutoff; release at
or after it refuses. The cutoff is not recomputed when a child starts.

When the running attempt reaches the cutoff, Q/S/G independently begin abnormal
stop/retirement/custody. Genuine normal empty completion observed before cutoff
may use only the original remainder through D for normal retirement/ACK. No
per-role timeout, receiver budget, new 250 ms window, process-start budget,
recovery allowance or retry budget is created. Nonblocking poll waits are capped
at 10 ms and the remaining original interval; source submission cannot suppress
lifeline/pidfd/deadline checks. Every positive read, transfer, exact wait, write,
fsync, ACK and final consumption requires before/after checks strictly before D.

At or after D, best-effort original stop/resource retirement may continue, but
no newly obtained positive empty/wait/ACK/completion fact becomes an accepted
result. A blocked regular-file syscall may finish late; `O_NONBLOCK` does not
bound it. If R remains uninterruptible or un-waited by D, Q cannot produce a
completed custody outcome. The finite reserve provides an opportunity for
cleanup, not a guarantee that the OS schedules or completes it within 250 ms.

## Failure matrix and release refusal

| Failure boundary | Independent action and permitted outcome |
| --- | --- |
| C loss before Q/child readiness, context transfer or creator adoption | No host release or native permit. Q stops using acquired original handles; S/G stop if actually armed. Partial files/context remain unknown. No assumed monitor owner or missing ACK. |
| C loss after readiness/release, before decision lock | Q and S/G observe original C lifeline; B enrollment/release closes, B/scope stop and fresh empty observation precede abnormal proposal/commit. Q may retain original creators and exact-wait S/G/R, but cannot claim C's B/Q waits. |
| C loss after decision lock or send | No second decision. Stop as necessary; any already-submitted terminal may persist. Live delivery/monitor/C wait remains unknown. |
| S loss before complete role/handle/registration transfer | Both release gates refuse. Q cleanup uses only acquired original authority. No valid terminal without complete registration; a not-ready G is not assumed capable. |
| S loss during execution or normal proposal/exit handshake | G stops independently; Q exact-waits S. Any uncommitted normal proposal is abandoned. Actual S nonzero/abnormal status forbids normal commit. G proposal plus Q's separate exact waits may produce abnormal custody. |
| G loss or malformed/missing G retirement | S/Q stop independently. No normal commit. Q's own actual fallback proposal may preserve diagnostic facts; no invented G event or G wait. |
| R loss before creator delivery/adoption | No release; partial store reserved. Q exact-waits its actual R child, S/G stop independently. No replacement R, reopened creators or registration retry. |
| R loss or blocked storage after release | Q/S/G stop without waiting on R storage. Q signals only its original R pidfd and consumes its own wait within D when possible. Missing ACK, failed/late wait or blocked R leaves custody unknown; no second writer/decision. |
| Q pause while C/S/R fails | S/G retain their own original B/scope handles, peer observations, C/Q lifelines and cutoff. Q cannot be assumed to arbitrate or reap while paused; unavailable result stays unknown. |
| Q loss before commit | S/G stop from original Q lifeline; R does not commit a source proposal. No reparenting-based authority, replacement reaper or accepted child-retirement claim. |
| Q loss after commit submission | S/G stop if still live; R may already persist but cannot supply Q's consumed ACK/result or C's exact Q wait. Historical bytes remain descriptive and live outcome unknown. |
| Scope/grant/publication/creator/namespace drift, unexpected endpoint or replay | Refuse release if pre-gate, otherwise original abnormal stop; no object reacquisition, record repair or authority from copied packets. |
| Original cutoff or D expiry at any boundary | Cutoff starts cleanup; D prohibits new positive completion/ACK. No renewed reserve or alternate attempt. |

All host, Q and T release writers have an explicit sole owner. A death or partial
transfer before either release boundary cannot be converted into an implicit
release by EOF, creator file existence, source proposal or current scope state.

## Historical inspection and the independent reference boundary

A live original owner may derive a v4 reference only from the complete original
registration and actually delivered creator descriptions. Its independently
retained original baseline must precede release if recovery is to rely on it.
Q's live retained baseline survives C/S loss until its own finite retirement;
durable external baseline retention is a separately authenticated acquisition,
not a reference R can self-certify by writing it next to its records. Existing
v3 reference-vault work does not automatically select or authenticate v4.
The explicit software composition is specified separately in
[v4 worker reference vault composition](whole-scope-successor-worker-vault.md);
it preserves the independent original baseline and the legacy v3 refusal.

Read-only inspection can compare that independently retained baseline with
registration/prefix/terminal bytes and report their recorded source, reason,
and distinct S/G wait fields. It cannot infer original full ACK consumption,
R wait, Q wait, original monitor completion or current scope cleanup. It starts
no process, scope, signal, fsync, repaired file, owner, deadline or retry.
Recorded facts do not become live authority through serialization.

This contract closes the previously unspecified S-death topology/arbitration
design. The explicit software implementation described below does not claim actual installation,
kernel-immutable custody, WQ-06 writer enclosure/accepting monitor, accepted
CPython build/input custody, real solver/model quality, online publication or
production admission. All existing admission/publication defaults remain false.

## Implementation slices and one consolidated validation selection

The new graph must land as one coherent software slice. No standalone accepting
DTO, parser or public constructor may be shipped ahead of the actual native
ownership mechanism. The authored implementation includes:

- A separate v4 protocol header/strict C and Python codecs, operation allocation,
  fixed packed-size assertions and role/count tables; v1/v2/v3 codecs untouched.
- New sealed Q/S/G/R entry paths and v4 bootstrap mode; actual child creation,
  finite initialization, event/kill ownership, direct source routes, state
  machines, original consuming waits and fail-closed cleanup.
- A noncopyable original Python v4 owner/custody child, original Q `Popen`
  ownership, actual creator receiver cleanup and gated selection in the native
  attempt; no worker packet or replay adoption path.
- Focused actual-process fixtures for selected mechanisms below, with
  installed-profile acceptance still pending and explicitly separate from
  fixture projections. Existing reference-vault/worker composition needs
  its own original v4 binding before it can consume this profile.

Freeze sources and review these boundaries before a single consolidated affected
regression. Do not run WebAgent, model calls, remote/company evaluators or real
solver campaigns. Do not modify the original benchmark tree, read secrets or
replace first failures/retry budgets. Linux same-UID fixtures may project
installation metadata explicitly; they must still use real processes, original
pidfds, consuming exact waits, separate OFDs, SCM_RIGHTS and actual file I/O.
Those mechanisms do not substitute for root/independent-account acceptance.

Required meaningful cases include:

1. Q is actual S/G/R parent; observation pidfd recipients get `ECHILD` on wait,
   Q obtains actual separate statuses, and C exact-waits original Q. S/G exits
   cannot be inferred from matching packets. Q-death after C death stays unknown.
2. Both orders of normal S/G shutdown, S normal proposal followed by killed/
   nonzero S, G premature/nonzero exit, lost normal-exit ACK and Q/S pause:
   no deadlock, fabricated normal commit or early gate.
3. C/S/R death before each init/rights/ready/context/creator transfer and after
   each release boundary, including partial acquisition/interruption cleanup.
   Actual uninherited gate writers/FDs must be checked rather than mocked EOF.
4. S death with live candidate grandchild, B pending enrollment, stopped S,
   concurrent candidate fork, source G direct R delivery, Q independent S/G
   exact waits and full terminal ACK/R wait. A stop attempt alone cannot pass.
5. S and G proposals arrive in both orders; a stale normal proposal precedes S
   failure; duplicate/conflicting/cross-source proposal or commit, Q-only
   fallback, truncated/extra/aliased rights and wrong original context refuse.
   R writes only the byte-exact selected original proposal and one Q decision.
6. R blocked in registration fsync prevents release; R blocked in terminal
   write/fsync cannot delay S/G/Q stop. R death, ACK loss, Q death before/after
   commit, a late completed fsync and exact-wait failure retain unknown without
   second terminal, writer or new allowance.
7. Actual R→Q→C creator delivery, shared OFD offsets/status, full registration
   and original-empty-terminal pins, file/mount/name/ACL drift, write/truncate
   races, copied owner, closed original acquisition and partial incoming-rights
   cleanup preserve existing v3-strength refusal while leaving v3 bytes intact.
8. Original D/cutoff at each readiness, release, source, retirement, commit,
   fsync, ACK and C consumption boundary. Child start/pause never recomputes
   D or the 250 ms reserve; post-D cleanup never becomes positive evidence.
9. Real installed root/U/cgroup2 delegation, atomic T placement, distinct
   candidate credentials, denied foreign attachment/control/custody access and
   actual blocked-storage/independent-account faults in the selected Linux
   environment. Unsupported skips establish no deployment capability. Darwin
   may cover portable codecs/ownership refusals only, not these Linux premises.

The completion report must state separately: software implemented, exact
mechanism cases executed, actual installed-profile prerequisites executed or
unsupported, independently retained reference/worker composition, and admission
status. Passing one category cannot silently close the others.

## Appendix A: exact candidate ABI for the implementation review

This appendix allocates a separate v4 namespace; it is a review candidate, not
an implemented parser. All integers are unsigned little-endian, structures are
packed without native padding, reserved fields are zero and strings retain the
existing fixed NUL-terminated lowercase-hex digest representation. The packet
magic is **`0x3451574c`**, version **4**, rather than the v1/v2/v3 packet magic.
The installed profile magic is **`0x3450574c`**, version **4**, size **19506**,
with flags exactly **1** for this lifecycle. Its remaining packed field order is
the existing installed profile order; the old profile parser is not reused.

`Context` has the existing 925-byte field order: six u32 header fields
`magic/version/operation/sequence/fd_count/reserved`, 538-byte binding,
40-byte scope identity, u64 target PID and three 105-byte publication pins.
The binding still contains D, six 65-byte digests and fixed credentials/groups.
The exact selected v4 profile and lifecycle are included in the original
profile/launch/intent digests. Complete registration projection means all
binding, scope, target and publication bytes; outer operation/sequence/count
changes never change that projection.

| Packed form | Exact order after `Context` | Bytes |
| --- | --- | ---: |
| `Context` control/registration | None | 925 |
| `Command` | u32 reason, u32 reserved | 933 |
| `SourceProposal` | u32 source, u32 trigger, u32 source_facts, u32 reserved, u64 observed_ns | 949 |
| `TerminalCommit` | u32 decision, u32 reason, u32 decision_sequence, u32 q_facts, u64 committed_ns, u32 s_wait_code, u32 s_wait_status, u32 g_wait_code, u32 g_wait_status, exact 949-byte original `SourceProposal` | 1914 |
| `TerminalAck` | Exact `TerminalCommit`, replacing outer operation only | 1914 |
| `QResult` | Exact 1914-byte `TerminalCommit`, u32 result_facts, u32 r_wait_code, u32 r_wait_status, u32 reserved, u64 observed_ns | 2863 |

`QResult` is one independent 925-byte outer Context, followed by the complete
1914-byte commit and 24 result bytes: 925 + 1914 + 24 = 2863. `TerminalAck` is
the complete 1914-byte commit frame with its outer operation replaced by100;
it does **not** add another Context before that frame.

The largest packet is 2863 bytes; the v4 receive buffer is exactly that fixed
maximum and rejects short/long packets for the expected operation, `MSG_TRUNC`,
`MSG_CTRUNC`, unknown ancillary data or any unaccounted right. At most **4** rights
are accepted in a packet. At most **3** pending source proposals are retained.
The finite v4 process-role FD inventory is bounded at **96** actual descriptors
including temporary send/receive slots. This is a separate v4 bound, not an
increase to the old helper's allowlist. Exhaustion closes actual acquisitions
and refuses; a numeric bound does not replace the per-role allowlist.

### Strict native total-FD follow-on contract

The resource follow-on applies that bound to each selected native
publisher P, bootstrap B, coordinator Q and their S/G/R/T descendants, counting
all open descriptors, including open standard streams and every temporary
path-chain, directory scan, clone pidfd, duplicate and received right. It does
not impose a process-global limit on the embedding Python C process. C retains
its separately finite original scope inventory; unrelated application FDs in C
remain outside that inventory. The earlier phrase "process-role inventory"
must not be presented as evidence that Python C's entire host FD table is
bounded at 96. An all-process-global interpretation including C remains an
explicit open requirement, not something this native mechanism establishes.

P/Q enter a v4-only resource helper before their first protocol receive, profile
walk or other FD acquisition. B must first read, parse and close its existing
control pipe and parse the inherited broker numbers to identify every original
input; that prefix may inspect existing descriptions but acquires none. B then
enters the same helper before SCM_RIGHTS, profile/grant walks, private pipes or
clone3. Inputs are actual mutable FD fields, never names used to reacquire an
object. The helper validates unique valid input numbers greater than two,
counts actually open stdio, and closes all other inherited descriptions using
close_range without opening a directory. The bound starts at this closed
finite native entry inventory; it makes no retroactive claim about an embedding
launcher's unrelated descriptors before close-all-except.

The helper preserves each original OFD while moving ordinary retained inputs
into the low range starting at three. B's existing candidate sink ABI remains
FD198 and, when selected, FD197: those exact original sink OFDs are bound before
lowering the numeric limit. A fixed target occupied by another retained source,
including a swap cycle, refuses rather than silently overwriting an OFD. Every
normalization duplicate requires a spare actual slot: an inventory of 96 that
requires relocation refuses before duplicating; an unlisted close may free that
spare. The helper never temporarily holds a 97th descriptor.

After binding fixed high sinks, the helper sets both soft and hard
RLIMIT_NOFILE to `96 - fixed_high_sink_count`, then installs a narrow inherited
native x86-64 seccomp filter that refuses setrlimit and any prlimit64 operation
with a non-null new-limit pointer. Query-only prlimit64 remains available;
foreign architectures and x32 syscall numbers refuse. PR_SET_NO_NEW_PRIVS is
set to install this filter. The filter intersects the existing target isolation
filter and survives fork/clone/exec. A trusted external administrator changing
a process limit is outside this local helper boundary. All remaining retained
inputs are normalized below the low limit. Every subsequent kernel allocation
then fits in that finite low range; the only high descriptors are the zero,
one or two explicitly counted sinks. B's v4-only child clears those fixed
descriptors' CLOEXEC at handoff without a later high-number dup2. Legacy B/T
branches and their sink handoff remain unchanged.

Failure is terminal for the selected helper attempt, including inability to
install the limit/filter or EMFILE during profile/tree validation, received
rights, channel setup or duplication. There is no limit restoration, broader
fallback, reduced validation, new deadline or retry. Partial received rights
and actually opened path/scan descriptions retain their existing unconditional
cleanup. Kernel refusal of a deep valid tree is a conservative resource refusal,
not acceptance with a skipped check. This contract requires focused real-kernel
mechanism coverage and later supported installed execution; a syntax build or
same-UID harness does not supply installed WQ-07 acceptance.

`source` is 1 S, 2 G or 3 Q. Source facts are bit 0 stop attempted, bit 1
original scope empty, bit 2 original B exit observed and bit 3 original T exit
observed; all other bits refuse. S normal facts are exactly **10** (empty and
T exit), trigger 0. An abnormal source requires stop-attempted. Its empty bit
requires its own B-exit observation; no source claims a wait or merges another
source's read. Triggers are 0 normal, 1 original C lost, 2 execution cutoff,
3 original R exit observed, 4 original object/protocol fault, 5 original S exit
observed, 6 original G exit observed, 7 original Q lost and 8 original Q stop
request. A Q-lost proposal cannot obtain a new Q commit.

`decision` is 1 normal or 2 abnormal, matching the commit operation.
`decision_sequence` is exactly 1. Reasons are 0 normal, 1 C lost, 2 cutoff/D,
3 R fault, 4 original object/protocol fault, 5 S lost, 6 G lost and 7 explicit
original C cancellation. Normal requires reason 0; abnormal requires 1–7.
The source trigger and Q reason are independently checked, not equated.

Q facts are bit 0 Q stop attempted, bit 1 Q original scope empty, bit 2 Q
original B exit observed, bit 3 Q consumed S wait, bit 4 Q consumed G wait and
bit 5 Q original T exit observed. Normal facts are exactly **58** (bits 1, 3,
4, 5), with S and G wait code `CLD_EXITED` (1) and status 0; Q stop and B exit
are false. A set S/G wait bit requires code `CLD_EXITED`, `CLD_KILLED` or
`CLD_DUMPED` and its actual status; an absent bit requires both fields zero.
Abnormal requires Q stop-attempted; a Q empty claim additionally requires its
own B-exit observation. No field represents Q reaping itself or Q reaping B.

Result facts are bit 0 full original terminal ACK consumed, bit 1 actual R wait
consumed and bit 2 final original object/record/deadline checks complete. A
complete result requires exactly **7**, R wait `CLD_EXITED/status=0`, and all
required waits for that outcome. `QResult` has no Q-wait or C-wait field.
Every nonzero observation/commit/result time is strictly before the same D;
nested source time is no later than commit time, no later than result time.
Reading a time field never establishes that the original operation occurred.

The exact operation/phase/count table follows. Sequence is local to the
explicit phase and route, not a free increment accepted by a generic parser.
Operations sharing a route remain accepted only in their named state.

| Op | Name; original route | Form / seq / rights | Phase and exact roles |
| ---: | --- | --- | --- |
| 64 | `C_Q_INIT`; C→Q | Context / 0 / 1 | Pre-scope; original B pidfd only. Profile/image/delegation/private-directory and endpoint inputs are Q's fixed inherited launch allowlist. Scope/target/publications zero. |
| 65 | `ROLE_SCOPE_A`; Q→S, Q→G | Context / 0 / 4 | Actual scope leaf, `cgroup.type`, `cgroup.subtree_control`, `cgroup.max.depth`, in that order. Target/publications zero; actual scope pin present. |
| 66 | `ROLE_SCOPE_B`; Q→S, Q→G | Context / 1 / 3 | `cgroup.max.descendants`, that role's independently opened `cgroup.events`, that role's original `cgroup.kill`, in that order. |
| 67 | `S_PEER_OBSERVERS`; Q→S | Context / 2 / 3 | Actual original B, G, R pidfd observation copies, in that order; never wait authority. |
| 68 | `G_PEER_OBSERVERS`; Q→G | Context / 2 / 3 | Actual original B, S, R pidfd observation copies, in that order. |
| 69 | `R_INIT`; Q→R | Context / 0 / 1 | Original private custody directory only; actual scope pin present but no scope right. Target/publications zero. |
| 70 | `ROLE_READY`; S/G/R→Q | Context / S,G:3; R:1 / 0 | Fixed expected source from distinct Q-role channel. Every role input validated; all non-roles closed. |
| 71 | `B_SCOPE`; Q→B | Context / 1 / 2 | Original one-shot scope description, Q-lifeline reader. No lifeline writer. |
| 72 | `B_ENROLLED`; B→Q | Context / 1 / 1 | T's actual original clone3 pidfd; target nonzero, publications zero. B/T have closed scope copies before submission. |
| 73 | `B_ENROLL_ACK`; Q→B | Context / 2 / 0 | Same original scope/target; close enrollment transport after one ACK. |
| 74 | `C_ENROLLED`; Q→C | Context / 1 / 0 | Original scope/target pinned; publications still zero. |
| 75 | `C_REGISTER`; C→Q | Context / 1 / 3 | Actual original registration, handoff, deadline publication descriptions in that order; full original registration projection. |
| 76 | `S_CONTEXT`; Q→S | Context / 5 / 4 | Full projection plus actual original T pidfd, then three original publication descriptions in their fixed order. |
| 77 | `G_CONTEXT`; Q→G | Context / 5 / 0 | Full original registration projection, no publication/creator right. |
| 78 | `ROLE_CONTEXT_ACK`; S/G→Q | Context / 5 / 0 | Full exact original projection and role validation before custody registration. |
| 79 | `R_REGISTER`; Q→R | Context / 1 / 0 | Full exact projection; exact 925-byte registration file body. |
| 80 | `R_CREATORS`; R→Q | Context / 1 / 2 | Registration then terminal actual creator descriptions, only after required durability. |
| 81 | `C_CREATORS`; Q→C | Context / 2 / 2 | Those same actual creator OFDs in fixed order. Q retains its original incoming copies. |
| 82 | `C_CREATORS_ADOPTED`; C→Q | Context / 2 / 0 | Actual original receiver/child adoption and original observer checks complete. |
| 83 | `C_REGISTERED_READY`; Q→C | Context / 2 / 0 | All role/B-peer ACKs, creator adoption, current original pins and deadline checked. |
| 84 | `B_PEER_OBSERVERS`; Q→B lifecycle | Context / 2 / 3 | Original S, G, R observation-only pidfds in that order, never inherited by T. Must precede op83. |
| 85 | `B_PEER_ACK`; B→Q lifecycle | Context / 2 / 0 | Actual peer roles validated and retained; full original projection. |
| 86 | `C_RELEASE`; C→Q | Context / 3 / 0 | Original host checks complete, before cutoff; one selected owner only. |
| 87 | `B_RELEASE`; B→Q lifecycle | Context / 3 / 0 | Host byte plus EOF consumed, peer/lifeline checks live; no T release yet. |
| 88 | `B_RELEASE_PERMIT`; Q→B lifecycle | Context / 3 / 0 | Both release conditions and every original prerequisite rechecked. B rechecks after receive before T gate. |
| 89 | `B_TARGET_DONE`; B→Q lifecycle | Context / 4 / 0 | Original B completed its actual T sequence; B stays alive waiting final result. |
| 90 | `S_TARGET_DONE`; Q→S | Context / 6 / 0 | Same original context; S must independently observe original T exit/empty. |
| 91 | `SOURCE_PROPOSAL`; S→Q/R, G→Q/R or Q→R | SourceProposal / 7 / 0 | One proposal per source; the two copies from S/G are byte-identical. Q-source is explicitly distinct. No terminal write authority. |
| 92 | `S_PREPARE_NORMAL_EXIT`; Q→S | SourceProposal / 8 / 0 | Original S proposal bytes, replacing outer op/seq only. S still a live stopper. |
| 93 | `S_PREPARED`; S→Q | SourceProposal / 8 / 0 | Exact request with outer op changed; permits only subsequent Q-authorized G retirement. |
| 94 | `G_RETIRE_NORMAL`; Q→G | SourceProposal / 8 / 0 | Same exact original S proposal/context; G new empty read then exit0. |
| 95 | `S_EXIT_NORMAL`; Q→S | SourceProposal / 9 / 0 | Only after Q's actual G wait0; S new empty check then exit0. |
| 96 | `G_STOP`; Q→G | Command / 6 / 0 | Fixed Q decision reason; G reports trigger Q-stop-request unless it independently observed the trigger. |
| 97 | `G_RETIRE_ABNORMAL`; Q→G | SourceProposal / 8 / 0 | Exact original G proposal with outer op/seq changed; G rechecks original empty then exits fixed abnormal status78. |
| 98 | `COMMIT_NORMAL`; Q→R | TerminalCommit / 2 / 0 | Decision1, original source S, normal required facts/waits, one locked decision. Exact 1914-byte terminal body. |
| 99 | `COMMIT_ABNORMAL`; Q→R | TerminalCommit / 2 / 0 | Decision2, selected original G or Q source, separate actual Q observations/waits. Same fixed terminal size. |
| 100 | `TERMINAL_ACK`; R→Q | TerminalAck / 2 / 0 | Exact full original op98/99 packet with outer op only changed to100, after durability and checks. |
| 101 | `NORMAL_RESULT`; Q→C/B lifecycle | QResult / 4 / 0 | Actual full ACK, R wait0 and final checks. B can now finish; C still must exact-wait B/Q. |
| 102 | `ABNORMAL_RESULT`; Q→C | QResult / 4 / 0 | Optional fully acquired abnormal custody diagnostic; never a candidate-success or production result. Q exits78. A missing required fact yields unknown, not this complete result. |
| 103 | `C_CANCEL`; C→Q | Command / 5 / 0 | Original explicit cancellation reason7; one post-registration cancellation, no new allowance. |
| 104 | `ROLE_CANCEL`; Q→S/G/R | Command / 10 / 0 | Pre-commit fixed refusal/cancellation only. S/G stop; R abandons uncommitted work. Never rewrites an already submitted commit. |
| 105 | `PUBLISH`; C→original v4 publisher | Context / 0 / 0 | Before Q launch, under the independently loaded v4 installed profile. Scope/target/publications zero. |
| 106 | `PUBLISHED`; original v4 publisher→C | Context / 1 / 3 | Actual original attempt, working and output directory descriptions, in that order; scope field binds the original attempt directory, target/publications zero. |

The v4 publisher entry is `--publish-successor-v4`, with the original five
argument pairs in order: profile FD, execution-root FD, controller FD, image FD
and original D (argc12). It uses only the v4 profile/parser and op105/106; it
never passes a v4 profile to the old `--publish-v1` path or rewrites the profile
header to obtain grants. Q entry is `--successor-coordinator-v4` (argc20), B
entry is `--whole-scope-successor-v4` (argc18). S/G/R are Q's direct-clone
internal entry functions, not public replacement-process constructors.

S/G scope-file readers are read-only; Q alone configures depth/descendant limits
to zero before opening/issuing those read descriptions. All event descriptions
are separately opened originals, not dup copies of one seekable reader. Scope
kill writers are write-only. The S/G seven-right initialization is split across
op65 and op66; partial receipt owns/closes only actual acquired rights and never
produces READY. Role initialization peer packets arrive only after Q has the
actual direct clone3 pidfds for all three children. Proposal endpoints and
lifeline ends are the fixed inherited child-entry allowlist, then Q closes its
temporary S-R/G-R endpoints after cloning; no dynamic source is admitted.

Header sequence normalization is permitted only for op92–95/97's explicit
proposal-bound commands/ACK. R's selected source comparison always uses the
original op91/sequence7 bytes, with no other normalization. A commit contains
those exact original bytes. Its ACK normalizes the outer operation only, never
the nested source, fields, facts, times or statuses. Python/C packed-size and
offset assertions must cover every form above before native integration.

### Initial native implementation boundaries

The separate native v4 parser, publisher, Q entry and Q-owned S/G/R graph are
implemented alongside the legacy paths. Q keeps the three standard descriptor
roles and closes every other inherited descriptor outside its fixed entry
allowlist. S/G/R close the standard roles too; actual incoming low descriptor
numbers and R's low creator acquisitions move with `F_DUPFD_CLOEXEC`, preserving
the acquired open file description rather than reopening an object by name.

The retained-role Q inventory remains a separate allowlist check. The v4
resource follow-on now closes unlisted native entry FDs, normalizes the original
OFDs, and installs the total kernel cap plus inherited resource-limit lock before
Q/P acquisition. This charges temporary profile-path chains, recursive publisher
directory scans, received rights and clone outputs to the same actual native
96-FD bound; it does not rely on counting retained roles after acquisition.
B's coordinated v4-only entry follows the fixed-high-sink contract above. That
follow-on is authored pending consolidated kernel-mechanism regression; neither
this source statement nor a mechanism pass establishes Python C's process-global
FD bound or installed execution. R separately retains its original INIT scope
identity and refuses a changed scope in REGISTER before creating either record.

Q and S may mark genuine empty normal completion observed before cutoff as
normal draining within the original D. G retains its independent cutoff check
until it has consumed and checked the normal retirement proposal. Therefore a
normal retirement racing that cutoff can conservatively refuse and stop,
leaving completion unknown. This initial implementation does not promise that
every normal tail can use the entire reserve, and never adds time or accepts a
post-cutoff launch. Installed full-graph WQ-07 and S-death qualification still
require actual supported Linux scope/credential execution; helper mechanism
tests alone cannot establish those acceptance outcomes.
