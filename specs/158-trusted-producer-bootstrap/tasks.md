# Tasks

- [x] T158-01 Define canonical trusted-bootstrap descriptor, protocol version, launch record, and bounded handshake/evidence DTOs.
- [x] T158-02 Define exact-byte/bootstrap allowlisting and platform execution modes without papering over Feature 156 T156-11. A native artifact build/allowlist supporting slice is now implemented; production lifecycle integration remains deferred.
- [x] T158-03 Specify and implement the ready/block/release/target-start state machine in a trusted bootstrap runtime fixture.
- [ ] T158-04 Bind bootstrap and target identities to Feature 156 registration, cleanup, recovery, and one monotonic attempt.

  Native artifact increment (supporting slice): checked-in C source, private build/allowlist
  loader, bounded target handoff control record, exact-one-byte gate close, post-exec error pipe,
  and isolation-policy call are implemented and covered by provider-free subprocess tests. This
  does not close T158-04: the Feature 156 runner still owns registration-before-release, consumed
  attestation, shared deadline, cleanup, recovery, and scheduler integration.

  At `15b8113`, a real Darwin bootstrap-to-target subprocess test also verifies isolation is
  applied before exec: the target starts, writes its declared workspace, and receives OS denials
  for outside writes, controller-secret reads and network connections. C executes the verified
  `target_path`, independently of `argv[0]`. These are supporting tests; the formal Feature 156
  registration/deadline/cleanup/recovery and Feature 157 broker boundary are still unconnected.

  The current increment adds `build_trusted_bootstrap_launch`, an identity-only adapter from a
  verified Feature 154 intent/attestation. It binds all launch identities, target executable
  digest, bootstrap descriptor digest, and the single gate nonce. `fixture-only` and platform
  mismatches are rejected. This is an admission boundary only; the Feature 156 runner still
  needs a real platform-bound bootstrap, shared registration/cleanup/recovery receipts, and one
  monotonic deadline before T158-04 can close.
- [x] T158-05 Add controlled fixtures proving target-marker absence before release, receipt-fsync ordering, post-release start, duplicate-token and early-EOF rejection, and group retention.
- [x] T158-06 Add a hostile direct-producer negative fixture; do not accept cooperative gate behavior as proof for arbitrary executables.
- [x] T158-07 Defer Feature 154/156/157 integration, scheduler/default entry points, publication, and external campaign validation to a later feature.

The runtime fixture now propagates one absolute monotonic deadline through normal and exceptional
cleanup and bounds the final leader reap. This is supporting evidence for T158-04; it does not
bind the fixture to Feature 156 registration, recovery, or a production scheduler entry point.
The child now defers target path validation until after gate release; a fixture with an absent
target still emits `bootstrap_ready` and only reports `target_start_failed` after release.
Post-release target identity failures, including a hard-linked target, also emit the fixed
`target_start_failed` frame rather than falling through to an unclassified early EOF.

The following paragraphs retain earlier supporting checkpoints; the `15b8113` entry above is
the current native artifact status. T158-04 remains open at the lifecycle-integration level.
The provider-free
`TrustedBootstrapRegistration` DTO now covers the narrow identity boundary: it carries the
launch/journal/run/parent/task, intent, attestation, bootstrap descriptor, target identity, and
gate protocol from `TrustedBootstrapLaunch`, adds the registered bootstrap PID/PGID, and binds
`registration_sha256` to the strict canonical payload.  Parsing can require an exact launch
match, but the DTO does not read registration files, inspect processes, invoke a provider, or
wire the fixture into Feature 156 cleanup/recovery.
The fixture runtime now constructs and parses this DTO before durable registration publication,
and the release-order test verifies the persisted payload binds back to the exact launch. This is
fixture-level evidence only; Feature 156's production runner and recovery path remain separate.

The fixture now also has a read-only recovery observation: it holds the entire workspace-to-journal
directory chain with no-follow descriptors and reads both durable artifacts through one held
journal directory, rejecting symlinked or replaced ancestors and files. It requires canonical,
self-authenticating payloads and exact evidence launch and registration digests for the supplied
launch. It reports only `evidence_available` for passed/failed terminal evidence, or
`recovery_required` for missing or unknown evidence. It never relaunches, signals, cleans up, or
inspects a process. T158-04 remains open because the Feature 156 production runner still owns
post-interruption process authority, cleanup, and recovery integration.

The provider-free formal-registration validator now checks a proposed Feature 156 registration
against one production-mode bootstrap descriptor and launch. It requires exact bootstrap and
target identities, the canonical registration self-digest, owner-start identity digest,
PID/PGID, recovery-lock device/inode, and platform-specific executable byte-binding metadata.
Adversarial tests rehash drifted fields to show these cross-record checks are independent of the
self-digest. The Feature 156 runner does not yet emit this extended payload or call the validator;
T158-04 remains open.

The fixture now uses `trusted-bootstrap-registration.json`, separate from Feature 156's formal
`process-registration.json`; read-only fixture recovery never reads the formal filename.
Fixture cleanup captures the OS start identity before registration and checks it before signals,
reusing Feature 156's bounded live-controller rule for an already reaped private group leader.
An identity mismatch or unreadable live identity cannot authorize TERM/KILL. This is fixture
hardening, not formal lifecycle integration.

The formal-attempt cross-record verifier now accepts an explicit verified intent/attestation,
trusted launch and descriptor, one Feature 156 consumption claim, one proposed formal process
registration, and optional terminal bootstrap evidence. It validates the claim's target stat-tuple
digest separately from the registration's bootstrap stat-tuple digest, then binds consumption,
registration, and evidence digests to the same launch. Missing or unknown evidence yields only
`recovery_required`; the verifier performs no filesystem or process operation. This closes a
protocol-checking gap but does not publish these records, prove executed bytes, or authorize
post-crash cleanup. T158-04 remains open.

The formal-attempt observer now reads the batch consumption claim, the matching nonce-ledger
claim, the formal process registration, and optional bootstrap evidence through bounded stable
no-follow reads while holding both directory chains. It requires byte-identical claims and
reuses the cross-record verifier; only missing or unknown terminal evidence produces
`recovery_required`. Missing or replaced claim, ledger, or registration fails closed. This is a
read-only observation and does not establish that registered bytes executed, authorize process
signals, or connect the production runner to trusted bootstrap. T158-04 remains open.

The evidence DTO now persists the target-start frame's PID/PGID and requires its group digest to
match that exact pair. The formal cross-record verifier and durable observer reject a rehashed
target PGID that differs from the registered bootstrap PGID. Parsing is strict: evidence written
before these fields were added is rejected rather than upgraded implicitly. This checks only the
reported start-time group, not subsequent group membership or the unimplemented production runner.
T158-04 remains open.

Fixture recovery now applies the same target-start PGID versus durable registration check for
both terminal and unknown evidence. The remaining production path requires a pinned executable
bootstrap artifact and independent target byte binding; hashing the current `python -m` fixture
source alone cannot satisfy T158-04.

Darwin snapshot preparation now has distinct immutable paths for the bootstrap and target in one
batch, while the ordinary producer keeps `.producer-snapshots/executable`. Formal Darwin
trusted-bootstrap registration requires `.producer-snapshots/bootstrap`. This only reserves the
two snapshot roles and narrows registration validation; native bootstrap artifact, target exec
handoff, and shared Feature 156 registration/cleanup/recovery and deadline path are absent.
T158-04 remains open.

The proposed formal registration now names the target execution binding separately from the
bootstrap's: mode, role-specific snapshot path, SHA-256, and byte size are required. The formal
validator rejects rehashed path/mode/digest drift; cross-record verification and durable
observation reject a rehashed size that differs from the verified target attestation. This still
does not prove the target snapshot or sealed FD was executed or connect a production runner.
T158-04 remains open.

An unexported pair-preparation context now binds the bootstrap and target under one absolute
deadline. Darwin returns distinct immutable snapshot paths; Linux returns two sealed memfd
handles held through the caller's bootstrap spawn. Existing Darwin role snapshots are rejected;
failed second preparation never yields a pair, and uncertain pre-spawn cleanup is reported.
An unreturned published role path is retained as cleanup-unknown; formal integration still
needs exclusive batch ownership to prevent concurrent substitution.
The shared Darwin publisher now rejects a role path created between preflight and publication
without replacing its bytes; provider-free fault injection covers producer, bootstrap, and target.
This does not validate an installed allowlist,
inherit the target FD into an actual bootstrap, publish registration, release the gate, or handle
terminal cleanup/recovery. The Python fixture remains non-production; T158-04 remains open.
