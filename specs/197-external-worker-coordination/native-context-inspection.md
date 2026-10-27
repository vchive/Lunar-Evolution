# Original worker/native binding and worker-local lifecycle inspection

Status: implemented and focused-tested in the 828-node concentrated batch;
the three affected style-repair files passed147 overlapping nodes. Linux mixed
and full CI remain open. It continues `native-lifecycle-followup.md` without
closing deployed isolation, actual hard-disconnect, guardian abnormal cleanup
or restart recovery acceptance.

## Original trusted inputs

`WorkerNativeLifecycleResolver.prepare_observer` is an unconnected trusted-only
installed-launcher seam. It retains the original `WorkerOriginContext`,
`SolverRequest`, profile digest, `ProducerLaunchIntent`, full original
`ProducerLaunchAttestation` and installed `NativeBootstrapArtifact`, plus original
workspace and producer-root paths. Full objects stay in private memory and are
never accepted by the public selector or written into the diagnostic pin.

`WorkerNativeTaskMapping` is explicit trusted-launcher input. Its controller
run/task/episode triple must match the retained assignment. Its native
run/parent-task/child-task triple must match the original launch intent and
registered observer context. There is no inferred parent/child relationship from
an episode ID or a current receipt. Original request contract/evaluator/environment
fingerprints must match the original native intent. Serialized baselines detect
changes to the original objects, including otherwise-forced dataclass mutation.

The installed caller must provide the original held worker episode
`DirectoryChain`, exact already-published worker intent bytes and its original
creation-FD identity. A current stat or reread is not a creator pin. The optional
`external_worker_wrapper._publish(..., capture_identity=True)` keeps its actual
write FD through write/fsync, exclusive link/unlink and directory fsync, then
compares the original inode with the published no-follow name. The tuple binds
exact original bytes, size, device, inode, mtime and final ctime. Defaults retain
historical worker bytes, close-before-publication ordering, return None and
channel-v1 behavior. The wrapper production execution path does not opt in.

## Pre-gate pin and resolver

The returned callback belongs only in the original trusted native
`registered_observer`. It validates original mappings, launch identity, descriptor,
artifact and original filesystem pins, then exclusively publishes
`native-context.json` under the original worker episode intent before returning.
The native runner rechecks its own original context and deadline before target
gate release. The callback cannot release or renew the gate/deadline itself.

The private diagnostic record contains original assignment/request/profile
references, explicit mapping, private native paths, original registration and
handoff creator pins, deadline bytes/binding and recovery-lock identity, with
all authority fields false. It contains no full attestation/nonce, signing key,
gate FD, Popen or new process identity. In-memory resolution retains the original
objects; the durable record is a diagnostic binding, not a restart authority.

Open directory chains retain the native workspace, batch, original producer root
and installed-artifact parent. Before and after observation, compare original
worker intent and binding bytes/inodes; exact path/held-directory association and
descriptor-relative entry metadata before/after reads; original registration/handoff bytes and
creator identities; exact deadline via `verify_native_deadline_binding`; original
recovery-lock inode; installed artifact; and original objects. A same-byte inode
replacement is drift. Neither file reopening nor late terminal creation rebases
an original pin. Existing durable pins are exclusive and never replaced on replay.

The resolver owns only its native chains. Its trusted caller retains ownership of
the original episode chain and must keep it open through inspection; closure or
replacement makes the context unusable. `close()` releases native chains and
forgets originals. A new resolver after restart returns `context_unavailable`,
even when the private pin remains. Restoring original trusted runtime objects
through an authenticated durable installation is a separate, unfinished design;
this candidate must not be reported as a completed restart durable resolver.

## Explicit local read-only lookup

`native_lifecycle_lookup` builds a bounded canonical selector containing only
schema/protocol, complete original origin context, request digest and profile
digest. Strict parsing rejects extra fields, paths, artifact, attestation, PID,
cleanup option or action. It is a worker-local API, not a new channel-v1 command.

`inspect` resolves only already-retained originals, revalidates them, calls
`recover_native_trusted_attempt(..., cleanup=False)` and
`audit_native_trusted_lifecycle(...)`, then revalidates again. It never calls the
audit persistence helper, signals, spawns, writes a terminal, issues an
attestation, extends a deadline, consumes reconcile, retries, takes over or
reassigns. A drift detected after a read discards any observed terminal projection.
It returns fixed distinctions: original context unavailable, context drift,
recovery required/native terminal missing, process-only and existing lifecycle
observed. Its bounded projection excludes native paths, PID and raw child prose.
A complete existing lifecycle remains diagnostic.

All reports and the private pin retain `publication_eligible=false`,
`native_success=false`, `remote_cleanup_verified=false` and
`publication_authority=false`. An HMAC, process terminal, lifecycle audit or
successful inspect cannot raise any of those values. Existing channel-v1
`receipt|unknown|missing` and controller assignment/claim state remain unchanged.

## Validation to run after integration

Candidate tests use real local compiled native fixtures to bind before target
release, observe missing terminal while the original gate is blocked, then read
process-only or existing capture lifecycle. They cover explicit mapping and
request-fingerprint mismatches; equal intent bytes in a different private
directory supplied as the original chain; strict public selectors; missing originals after
restart; replay; original object drift; same-byte worker/native/deadline/binding
inode replacement, including during recovery and before pre-gate publication;
no native authority; byte-for-byte/no-write snapshots; no signal/publish during
inspection; and original write-FD lifetime through publication. Source syntax was
AST parsed without importing or executing product/upstream code. No pytest,
Ruff, compileall, SSH, model, evaluator, build or source-closure execution was
performed while preparing the candidate.

## Remaining acceptance

There is no actual installed wrapper/native bridge, distinct-account transition
or accepted isolated runtime in this candidate. Production remains disabled.
The fixed inert SSH receipt test remains insufficient for candidate isolation or
hard-disconnect lifecycle proof. The account and guardian follow-up document
records what must precede a production bridge; neither unsupported 5090gpu
privileges nor absent KVM block the bounded software work above.
