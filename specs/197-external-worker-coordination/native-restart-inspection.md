# Opt-in authenticated original context for read-only restart inspection

Status: software implemented; AST parsed only, shared focused regression pending.
This extends the trusted installed caller seam in `native-context-inspection.md`.
It does not change the old diagnostic pin, default observer, public channel or
controller assignment/unknown state. It does not install a native production
bridge, restore a live supervisor or prove any cleanup.

## Original writer and independent anchor

A trusted installed launcher may pass an exact `WorkerNativeRestartWriter` as the
explicit `restart_writer` parameter to the existing
`WorkerNativeLifecycleResolver.prepare_observer`. The default is None. The writer
must receive the installed `WorkerOriginKey` and exact installed profile digest;
its worker/host/key IDs and host boot must match the original worker intent and
current OS boot. Revoked, rotated, changed or mismatched keys refuse. No secret
key is serialized. The existing worker-origin receipt signature protocol is not
reused: this record has the separate HMAC domain
`lunar-worker-native-restart-v1\0`.

The hook executes only inside the original registered observer, after the existing
original context and native creator pins have been checked and the diagnostic
pin has been published, before returning to the original native gate. It receives
the original held episode/native chains and original worker intent,
registration/handoff creator-FD identities. A current stat is only comparison,
never a new original pin. Writer failure propagates to the original observer so
the native runner refuses the target gate. It never schedules a late completion.
The native runner retains its original deadline check before gate release.

The writer creates, fsyncs and exclusively publishes two private files under that
original episode directory:

1. `native-restart-packet.json`: original origin context (all eight fields), request,
   six explicit mapping IDs, full original launch intent and attestation, installed
   artifact/descriptor and paths, original worker intent/binding, original native
   registration/handoff/deadline/binding bytes, creator pins and held-chain numeric
   identities. The record is HMAC authenticated and every authority claim is false.
2. `native-restart-complete.json`: a separate HMAC record binding the exact final
   packet creator inode/hash/size/mtime/ctime. It is not a self-pin. Packet creation
   and complete publication keep the original write FD through file/directory
   durability and original no-follow name comparison.

Only after both files and the directory have fsynced does the writer expose a
`WorkerNativeRestartAnchor`. This immutable private DTO has repr-hidden bytes
with original packet **and completion** creator pins and original episode chain,
installed identity/profile and lookup digest. Neither record tries to include its
own final inode/ctime/hash. Creation is one-shot; duplicate, pending or failed
publication cannot be overwritten or retried through this writer.

The anchor is an **explicit trusted parameter from the original installed
caller**, retained separately from these files across restart. This slice has no
public JSON/from-disk/current-stat anchor loader and cannot reconstruct a missing
original anchor from a signed packet or completion. A caller that loses the
anchor before independently preserving it cannot restore this context. An
installed supervisor must durably preserve/deliver the original anchor before it
relies on crash recovery; that production integration remains open. The packet's
HMAC authenticates a shared-key holder, not pre-gate timing, immutable custody or
cleanup. The original writer seam/FD pins and independent anchor establish which
original data the reader may compare.

Full attestation/nonce and original intent argv remain private 0600 packet data,
never report/repr material. These are original trusted objects, not target
process/env/argv inspection. There is no gate FD, Popen, pidfd, mutable capability
graph or serialized key. The existing native nonce consumption ledger is still
required; restoring data never issues/consumes another attestation.

## Actual read-only restore and inspection

`inspect_native_restart(anchor, lookup, key=..., expected_context=...,
expected_mapping=..., expected_profile_sha256=...)` requires all original installed
parameters independently. The public selector supplies no path, artifact,
attestation, PID, cleanup option or authority. Strict canonical schemas, separate
HMACs, current boot and key revocation/rotation checks precede use of packet data.
All eight origin fields, all six mapping IDs, request/profile/intent/artifact
identities and exact worker IDs must match. Unknown/extra fields refuse.

The reader reopens every original directory component with the existing held
NOFOLLOW chain implementation and compares its numeric identity/mode/owner to the
original held-chain pins. It opens private records relative to the held episode
FD and compares original file creator identity and bytes before/after reading.
Same bytes in another inode are drift. It uses existing intent/attestation parsers
and verifier, descriptor validation, artifact revalidation and request parser.
There is no filesystem scan or trusted-pin capture from current files.

The reader restores a temporary original context in a new resolver **without**
calling `prepare_observer`, registration, attestation consumption or any writer.
It then actually invokes existing `recover_native_trusted_attempt(cleanup=False)`
and `audit_native_trusted_lifecycle` through the existing read-only resolver.
Original objects, native bytes, deadline/binding/inode, retained directory chains,
packet/completion pins, key and caller parameters are rechecked after observation.
Newly reopened FDs close on return; the original caller's FDs are not owned.

A valid previously written process terminal returns process_only; a valid complete
existing capture can return lifecycle_observed. Missing terminal stays
recovery_required. Existing recovery validates the original absolute deadline and
boot/binding without requiring it to be unexpired, so an expired attempt with a
valid existing terminal remains inspectable. Expiry never enables cleanup,
relaunch, deadline renewal or a new relative timeout. Drift, partial/missing files,
missing independent anchor, wrong/revoked key or boot change returns a bounded
context_unavailable/drift projection. Records are not repaired.

Every result keeps publication eligibility, native success, remote cleanup and
publication authority false. `restart_context_authenticated` means the original
packet and explicit trust parameters matched; it is not process/isolation or
cleanup authentication. Reports expose no private paths, attestation nonce, key,
raw child prose or PID. No subprocess, signal, sudo, SSH, target env/argv access,
remote evaluator, candidate launch or filesystem write occurs during restore.

## Validation and remaining boundary

`tests/test_external_worker_native_restart.py` exercises real local inert native
attempts, closes the original resolver/FDs and verifies actual recovery/audit,
including missing pre-gate terminal, process-only and existing capture. It covers
independent-anchor absence, packet/completion same-byte inode replacement,
truncation/missing records, all origin/mapping fields, profile/key/boot drift,
forced mid-publication/mid-observation key changes, every held chain's mode and
numeric owner drift after observation, bounded oversized selectors without payload
hashing, strict selector/anchor schemas, original
creator/completion pins, no write/signal/prepare effects, failed persistence before
gate release, one-shot behavior and unchanged default observer.

Active account isolation, the installed isolated runtime/production bridge,
independent durable anchor custody integration, real hard SSH loss and native
abnormal guardian cleanup evidence remain separate acceptance items. This local
software path is not blocked on remote privileges and does not claim those items
are complete. Root performs focused tests, Ruff, compileall and diff checks once
with the shared development batch; this author performed AST parsing only.
