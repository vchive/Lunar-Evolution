# Installed guardian original-reference custody

Status: implemented after independent static review; the seven-file affected
Linux regression passed 154 cases with zero failures, errors or skips in
176.654491586 seconds. Its 13 new sidecar cases all executed and passed.
The earlier, separate `44cdd73e` mixed acceptance failed at its original
600-second deadline (600.032415813 seconds, rc=-15, timed_out=true, no JUnit or
terminal module origins). It does not test this later sidecar integration;
the mixed failure and main-merge gate remain open.

## Existing gap and scope

The native attempt can explicitly start the independent receiver and pair its
original reference with actual pre-gate native registration/handoff creator
pins. Its original trusted registered observer receives the reference through
the original request. Previously, the installed wrapper/native bridge retained
only the old restart anchor, leaving independent guardian-reference persistence
to the caller.

This continuation closes that software composition gap with one explicit,
default-disabled bridge parameter and one create-only sidecar protocol in the
existing independently installed vault. It changes neither channel-v1 nor
NativeTrustedRegisteredContext, native restart packet/completion or native
vault V1 payload. The original native direct-guardian path remains the default.
There is no current-record reference discovery, implicit factory, account setup,
automatic attestation, generic registry or remote scheduler.

## Trusted composition and pre-gate order

The trusted installer supplies the already original NativeGuardianCustodyRequest
to WorkerInstalledNativeBridge. The request verifies the exact canonical worker
context digest, native launch and installed profile against its constructor
originals, rechecks its held private directory and original sealed receiver
owner, and exposes its original directory only for trusted separation checks.
The independent vault must be outside the episode/native/producer/artifact
stores and outside the guardian custody directory, including both nesting
directions. A public worker packet cannot configure these originals.

The bridge passes the original request explicitly into the native attempt.
The existing attempt therefore creates and validates the guardian/native
registration pair before invoking the original observer. That observer:

1. Keeps its existing original control/wall-expiry checks.
2. Uses the existing resolver/restart writer to persist the original native
   packet/completion and obtain their actual creator pins in its original anchor.
3. Keeps the existing independent native vault V1 anchor publication.
4. Reads that exact native V1 payload, derived byte-for-byte from the original
   anchor, assignment and key. Current file metadata is a read-stability check,
   never the source of original packet/completion creator pins.
5. Opens the exact original worker chain from the anchor and compares the
   original packet/completion creator pins. The packet's detached native context
   must equal the original callback context, and its actual native projection
   must equal the creator-delivered guardian pairing reference.
6. Creates guardian-<lookup-sha256>.json in the independent vault with its own
   protocol/HMAC domain. It contains original lookup/context/mapping/profile,
   worker/host/boot/key identity, original native anchor and V1 record digest,
   and the original guardian pairing reference. It contains no signing secret
   and cannot restore a live FD/Popen or signal target.
7. Retains the original creation FD through file write/fsync, exclusive
   pending/link publication, directory fsync and creator-inode/bytes readback.
   Every action checks the actual original native deadline and existing parent
   control. It rechecks both independent vault records, originals and pairing
   before returning. The native attempt then performs its existing post-observer
   freshness, original guardian pairing and gate checks.

The helper can observe a fixed private lookup only. It rejects missing keys,
wrong assignments/profile/boot, nested stores, changed originals, partial
records or inconsistent native anchors. The old native vault reader is not
extended to silently accept another wire shape.

## Failure, durability and authority

The two independent vault publications are not a transaction. If the native
anchor exists but the guardian sidecar is absent, the new combined lookup stays
unavailable; neither current receiver files nor the native packet can manufacture
a missing guardian original reference. A failure keeps its pending/final files
and refuses the gate. Replay does not repair, overwrite, retry or renew a deadline.

A sidecar durably written before a lost acknowledgement can remain readable.
That is an original-reference custody fact, not proof that the observer returned,
the gate opened or a target started. The new report uses status=custody_observed
only for those retained original facts and always execution_status=unknown.
Its nested native report retains its own existing conservative status.
Native success, production, publication and cleanup authority remain false.
Guardian D/exit0 and exit78 never establish whole-group termination.

The independently retained InstalledWorkerNativeVault reference, signing key,
same boot and trusted private installation protect the sidecar across restart,
exactly as for the existing original native anchor. This does not protect against
a compromised signing account/root or prove immutable build-input custody.
Blocking filesystem writes/fsync have no demonstrated hard completion bound;
post-call expiry refuses further publication actions but cannot bound the call.

## Read-only fresh process

inspect_installed_guardian_reference receives only the original installation,
key and expected assignment/profile plus its fixed bounded public lookup.
It authenticates its sidecar, checks the original native anchor and V1 payload,
opens only their pinned original packet/completion, and invokes the existing
read-only guardian/native inspectors. It rechecks both vault records, original
installation/assignment and guardian observation before returning.

The reader never starts an observer/receiver, launches, signals, repairs,
changes permissions, writes a receipt or refreshes an execution budget. Closing
the original controller handles does not prevent the independent read, and a
missing independent sidecar does not fall back to current-record discovery.

## Concentrated regression and remaining acceptance

The new 13 Linux fixture cases compile the real receiver and run the existing
real inert installed wrapper/native attempt. They cover custody while the
actual target remains gated; unchanged old payload fields; closed original
handles and fresh-process read-only inspection; failure before/within/after
sidecar publication; retained partial state and zero replay; missing independent
sidecar; original key/context/mapping/profile or pairing-inode drift; original
wire expiry after custody; and nested-store preflight refusal. The original
installed native vault, native registration/guardian and default worker suites
belong in the same affected selection. macOS skips these Linux cases and cannot
substitute for their evidence.

The concentrated Linux run used frozen index tree
`e6aa50a6238237c0a4374f679ad93be8c9c64c6d`, based on `44cdd73e`.
All 2,566 source files / 2,874 manifest entries matched before and after;
all 232 loaded Lunar product-module origins matched the frozen archive,
including the three changed product modules. The 13 actual JUnit nodes match
the new test file's frozen AST parameter expansion. The complete run contains
154 distinct passing nodes, no failure/error/skip nodes, one pytest invocation
and zero retries. The 11 top-level regular execution files were collected
read-only without recursing into fixture directories; all 10 result file
references matched their retained bytes and SHA256 values. The origin plugin
reports product modules; test-file coverage is separately checked against the
frozen source manifest and actual JUnit nodes. These are source-path/byte checks,
not proof of immutable consumed-bytecode custody.

Original evidence is retained under the primary checkout's ignored root
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/validation/parallel-batch-20261027/`:
`installed-guardian-sidecar-linux-c5efv6z6/remote-records/` holds the unmodified
execution records, with `evidence-verification.json` in its parent. The earlier
failed mixed records remain separately in
`final-mixed-44cdd73e-prepared/execution/remote-records/`; its parent retains
`mixed-outcome.json`. Neither result is relabeled as the other source's run.

This software does not close accepted receiver/guardian builds and immutable
input custody, isolated runtime/production CLI composition, actual root-installed
distinct candidate account/access denial, real SSH/wrapper/launcher failure or
blocked-storage/hard-disconnect acceptance. Guardian trigger/signal-result
diagnostics, documented whole-group termination proof and hard filesystem time
bounds remain separate design limits. No model, WebAgent or remote evaluator
execution is required for the regression.
