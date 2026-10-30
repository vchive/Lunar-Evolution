# Explicit v4 worker reference vault composition

Status: SDD continuation selected for software implementation (2026-10-28).
The installed root/U/cgroup boundary and production admission remain unaccepted.
This composes the existing default-off v4 graph; it does not modify native C,
reopen its resource-bound implementation, or upgrade a legacy worker silently.

## Original selection and retained evidence

`WorkerInstalledNativeBridge` gains one trusted installation-only keyword,
`whole_scope_custody_profile`, defaulting to the existing v3 profile. Existing
calls and the v1 native anchor / v3 whole-scope vault wire stay unchanged. A v4
bridge requires the explicit `linux-whole-scope-successor-custody-v4` selection,
an actual original `NativeWholeScopeOwner`, its actual selected successor
session, and its original `NativeWholeScopeSuccessorCustodyOwner`. A string,
serialized reference, worker request or reconstructed child cannot supply those
owners. V4 selection without a scope, v3/v4 mismatches and guardian composition
with whole-scope all refuse. The lifecycle selection, session/child identity,
profile digest, launch/intent and original deadline remain pinned for the
bridge's single attempt.

The existing native runner already binds original whole-scope registration
before invoking its registered observer. For v4 that includes R-to-Q-to-C
creator delivery, same-OFD adoption, C's adoption ACK and Q's registration ACK.
The bridge keeps this sequence:

1. Revalidate the original assignment, native context and remaining deadline.
2. Run the original native registered observer / restart writer.
3. Durably retain its original native anchor in the existing independent vault.
4. Durably retain a separately authenticated v4 reference sidecar.
5. Freshly revalidate the native packet, original live v4 custody, assignment,
   installation, both retained records and the original deadline.
6. Return to the unchanged native runner, which checks its originals again
   before the independent scope and host release gates.

A partial native-anchor or sidecar write leaves the attempt consumed and the
candidate gated. No repair, overwrite, fallback to v3, inferred success or new
time allowance follows. Synchronous storage can block; the independent native
Q/S/G cutoff remains responsible for stopping and no hard syscall latency is
claimed.

## Separate v4 module, wire and public APIs

The new module is `external_worker_whole_scope_successor_vault.py`. Its APIs are
`retain_installed_whole_scope_successor_reference(...)` and
`inspect_installed_whole_scope_successor_reference(...)`, with the same explicit
original installation/context/mapping/profile/check arguments as the existing
v3 APIs. The retainer additionally requires the live original scope and native
restart anchor. The inspector accepts no live owner and acquires none.

The protocol and HMAC domain are the independent
`lunar-installed-worker-whole-scope-successor-v4-vault-v1`; its create-only name
is `whole-scope-successor-v4-<sha256(original lookup bytes)>.json`. The strict
bounded sidecar contains the existing native anchor/hash, original worker
context and mapping, worker/host/boot/key identities, native-context hash,
original absolute native deadline, separate worker-profile and whole-scope
profile digests, and the exact original v4 reference. Its kind is
`original-whole-scope-successor-reference-custody`. Existing v3 files, protocol,
domain and parser do not accept this record or reference.

The live writer checks the exact v4 op79/sequence1 registration against the
original scope binding, T PID and three actual retained publication OFDs.
Those publication pins must also match the native registered context and its
original deadline binding. T's PID is never equated to native registration's B
PID. The child must retain its actual original creator descriptions and stable
registration/empty-terminal pins; merely opening files at matching names or
validating a detached reference cannot authorize retention. The scope/session,
child/reference, native packet, anchor, key identities and installation are
freshly rechecked around storage and before returning to either gate.

Vault placement remains independent of candidate grants, workspace, producer,
artifact, worker/episode stores, native scope roots and the custody directory.
The original native anchor must already be present and byte-identical. Sidecar
creation uses the existing create-only, fsync, stable-read and original-chain
checks, without exporting key material or private paths in errors.

## Read-only historical semantics

The inspector requires the independent installation, authenticated native anchor
and authenticated original v4 sidecar. Missing originals return unknown and do
not discover a reference from current custody files. It validates both profile
digests, original assignment and native packet, then calls only the v4 custody
inspector. Exact prefix, normal terminal and abnormal terminal observations may
be returned, including recorded source/trigger/reason and separate S/G wait
fields. Those are recorded facts only. Historical reading cannot establish the
original full ACK, R/Q/B waits, original monitor join, current cleanup or native
success. `production_admission`, `native_success`, `publication_authority`,
`cleanup_authority` and `online_publication` remain false.

## Bounded implementation and consolidated validation

Product changes are limited to the new v4 module and explicit bridge dispatch.
The existing native runner, v3 vault, native anchor wire, resource headers and
native programs need no modification. Add independent tests in
`tests/test_external_worker_whole_scope_successor_vault.py`; retain existing v3
and v4/native tests in the single affected union after author freeze.

Required cases cover actual creator/publisher OFDs and a real inert target held
behind its original gate during both writes; partial writes/fsync faults and
late/drifting checks refuse release without repair; explicit v4 selection and
v3 defaults reject each other's owner/reference; profile/context/native anchor
and same-byte inode substitution refuse; forged/cross-domain records refuse;
missing original evidence is unknown; fresh-process prefix inspection and in-process normal/abnormal inspection
preserve every false authority flag and perform no process/write action. Same-UID fixtures may project root metadata narrowly and must label that
projection. They do not establish root installation, independent-account ACLs,
actual cgroup credentials, blocked-storage deployment, WQ-06 enclosure or full
installed WQ-07 acceptance. No model, solver, WebAgent or evaluator is needed.
