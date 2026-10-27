# Independent native guardian receiving boundary

Status: narrow explicit software API and actual-process fixtures, awaiting the
batch owner's concentrated execution. This is not an accepted installed
production runtime, account transition or abnormal-disconnect acceptance.

## Current fact and scope

The existing native guardian receives the original group pidfd, controller
lifeline reader, finish reader, acknowledgement writer and absolute native
deadline. Its protocol is R, then exact F plus EOF, then D plus EOF. An abnormal
path attempts the original group signal and exits 78, without publishing the
signal's return or a group termination acknowledgement. Neither 78 nor D is
whole-group cleanup proof.

The new `native_guardian_receiver.c` is an independent native process, created
by the opt-in `start_durable_native_guardian` API. It directly forks and FD-execs
that original guardian, retains the exact child relationship and receives its
R/D stream. It does not start an interpreter or a background service. Existing
`start_native_guardian`, native C guardian and default trusted-attempt behavior
are unchanged. There is no implicit factory or accepted-runtime boolean.

The API requires two live original `LinuxSealedExecutable` owners: the explicitly
installed receiver and guardian images. The existing private owner verifier
checks their original bytes, descriptors and original seal contexts. ELF headers
are required. Missing, reconstructed or drifted owners refuse. There is no
pathname re-execution, shell, host Python fallback or automatic attestation.

## Original binding and receiving/ACK order

The trusted caller provides a held original private directory chain, the
original context/launch/profile digests and both original deadline forms. One
directory is exclusively reserved for one original attempt. The returned
`GuardianCustodyReference` records those originals, image hashes and directory
chain pins. An installation must retain that reference independently; reading
current receiver files is not a way to manufacture it.

The receiver validates its exact descriptor roles and sealed guardian image,
closes unrelated descriptors and creates two fixed, exclusive, no-follow 0600
files beneath the already-held 0700 directory. It never changes ownership,
provisions an account or opens a directory selected by a worker packet. Existing
names refuse; failed attempts retain their partial records and cannot be retried
as fresh attempts in the same directory.

It starts the original guardian in its own session, with the same original group
pidfd, lifeline/finish readers and absolute deadline. Its new private pipe replaces
only the guardian's acknowledgement writer. The guardian does not inherit the
directory, record files, caller acknowledgement writer or unrelated descriptors.
The receiver then drops its copy of the group pidfd and never signals a group.
Only the original native guardian retains group signaling authority. No PID or
PGID is persisted or reopened to reconstruct authority.

1. Receive exact native R.
2. Write a bounded custody-registration record, fsync its creating FD, recheck
   creator inode/name/directory, fsync the directory and recheck the original
   deadline and file binding.
3. Only then forward R to the original host acknowledgement reader. The Python
   API also independently reads and validates that original private registration
   before returning the live owner to its caller.
4. Receive the exact remaining D/EOF stream and use `waitpid` only for the exact
   freshly forked child. Persist an independent bounded watcher-exit record with
   its actual exit/signal status, original binding and creator inode.
5. Only exact D/EOF plus child exit 0, successfully persisted event and an
   unexpired original deadline permit forwarding D and receiver exit 0.
   All other paths remain failure/unknown. Reaping or forcibly killing only the
   receiver cannot establish nested guardian retirement; abnormal owner cleanup
   therefore returns false even after its original handles have been retired.

Registration durability is not proof that R reached the caller. A lost ACK
leaves its original durable prefix and startup unknown. The reader does not
repair files, create a replacement owner, refresh the deadline, launch or signal.

## Abnormal observations and deadline limit

If the controller exits while the original lifeline writer remains live until
that exit, the independent native guardian observes actual EOF and exits through
its abnormal path. Its independent receiver can still wait for that exact child
and commit the event before the original deadline. A later fresh process can
read the original private registration/event using the independently retained
reference. No dying controller thread performs the persistence.

The event records D observed and actual child exit kind/value. Exit 78 does not
identify which abnormal trigger occurred and does not expose the signal result.
`signal_result_known`, native success, publication, cleanup, whole-group cleanup,
isolation, immutable custody and production admission remain false. Cleanup is
always unknown. These records never substitute for native execution terminal,
solver receipt or restart-anchor authority.

Every poll, write, fsync and ACK checks the same original native deadline before
and after the action. No reception-time budget, retry, renewal or post-expiry
diagnostic interval is allocated. Deadline expiry does not start a new event
write. The original native guardian retains its own emergency stop behavior,
which does not wait for receiver storage.

Blocking filesystem calls, including fsync, do not provide a proven hard
completion bound. The receiver cannot promise to exit exactly at its deadline
while such a syscall is blocked. If it eventually returns after expiry, it issues
no ACK or new publication. This unresolved storage/provisioning limit remains
explicit; the implementation does not turn it into bounded production custody.

## Concentrated fixture validation and remaining integration

The new finite Linux fixture set compiles the real receiver and existing real
guardian, using the existing inert native process tree. It covers durable R,
normal F/D plus exact child retirement, original deadline with no post-expiry
event, existing-file refusal, partial/context/inode drift and read-only behavior.
The independent-process case exits the actual controller using `os._exit` with
its sole lifeline writer still open, then verifies a fresh process can read the
receiver's subsequently committed actual guardian exit 78. Diagnostic fixture
PID files are observed read-only and never used to recreate signal authority.
Non-Linux skips establish no native capability. No mocked root facts or deployed
account/runtime acceptance are used.

The custody registration is a new local receiver record, not the original native
execution registration. Existing native registration publication happens after
guardian readiness. Connecting its exact original creator pins/anchor and the
installed worker bridge to this explicit receiving API needs a separately
reviewed pre-gate observer integration; this slice does not claim it is done.
Accepted receiver/guardian builds and installation, separate candidate accounts,
real SSH/launcher/guardian failure and blocked-storage tests, authenticated
independent deployment custody and any documented group-termination primitive
remain required before production abnormal-disconnect acceptance.
