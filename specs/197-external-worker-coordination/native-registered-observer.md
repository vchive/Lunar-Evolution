# Original native registration observer seam

Status: implemented with focused regression; production/lifecycle acceptance remains pending.
This is a default-disabled trusted-installed launcher integration seam, not an
external-worker deployment, native cleanup proof or publication mechanism.

## Problem and scope

The worker wrapper currently has only a channel intent and optional signed
response. It cannot reconstruct the original native workspace, launch,
attestation or installed artifact from a receipt, episode ID or channel PID.
The real native attempt already owns those originals after registration and
before the private target gate is released. Expose one synchronous observation
at that exact point so a future installed launcher can publish an assignment
binding under its existing create-only worker episode intent.

`run_native_trusted_attempt` gains an optional keyword-only
`registered_observer: Callable[[NativeTrustedRegisteredContext], None] | None`.
Its default is None; no wire schema, wrapper argv, environment or candidate API
can select or provide this observer. Existing unsupported native admission
remains a refusal before the observer can run.

## Context and ordering contract

The fixed frozen/slotted carrier contains detached original run/parent/task,
launch/journal, workspace/producer/artifact paths, original identity digests,
registration/handoff/deadline/binding canonical bytes, recovery-lock identity and
original registration/handoff byte+inode pins. It contains no key, attestation
body, gate nonce, complete launch body, mutable DTO/dict, Popen, live FD or gate
control. Original attestation and runtime objects must remain with a separately
installed trusted resolver. The carrier alone cannot reconstruct that authority.
`publication_eligible` is always False.

Invoke only after the original bootstrap registration/handoff are durable and
its ready frame was accepted. Before and after the observer, reuse original
launch-input/grant/deadline checks, installed artifact verification, exact
registration/handoff rereads, no-follow file-identity checks and original lock
identity. Compare with an internal original carrier never handed to the
observer; the observer receives a detached copy and cannot replace its baseline.
The registration publisher must retain creation pins from the original write
FDs, held from writing/fsync through exclusive publication and directory fsync.
It compares each still-held original inode with the no-follow published name
before returning immutable byte/device/inode/time pins. The observer compares
current records with those pins; a same-byte replacement before the publisher
returns cannot establish a new origin. Missing creation pins refuse observation.
The default atomic writer still closes before publication and returns None;
existing two-field publication DTOs remain constructible and default attempts
without an observer do not request this opt-in identity capture.

Only after these checks and another original-deadline check may the existing
one-byte gate write occur. No new deadline, retries, resume, takeover or lease is
introduced. None is the only successful return value.

Ordinary observer exceptions and non-None returns become one fixed refusal;
the existing attempt exception/finally path keeps the gate closed and cleans up
its original registered process. BaseException propagates after the same
existing finally cleanup. Failed or interrupted durable observer publication
may leave a registered unknown attempt and an existing private pin; no target
start, cleanup success or terminal receipt is manufactured from that fact.

## Focused validation

Focused tests reuse the actual compiled native bootstrap/target fixture. They
check durable registration and a missing target marker while the observer runs,
an actual create-only pin before a real target launch, immutable detached
nonce-free context, observer exception/non-None return, BaseException cleanup,
same-byte registration/handoff inode replacement during the callback and before
the publisher returns, missing original creation pins, forced carrier mutation
and invalid-observer refusal before consumption/spawn. Direct real-file writer
cases cover its default None/close-before-publication and exclusive replay
behavior, the held creation pin, same-byte replacement during directory fsync,
and descriptor closure/temporary cleanup on write, fsync or stat failure.
The batch ran these with the existing native attempt/registration/deadline and
producer tests. Initial overstrong cleanup assertions were corrected without
changing production cleanup, and the final affected tests pass. The latest
15-file union is 756 distinct nodes: 754 pass and two existing macOS/Linux skips.
Ruff, compileall and staged diff checks pass. See the retained original results
in [batch acceptance](../../docs/parallel-batch-acceptance-20261027.md).
The final Linux mixed/full CI and production/guardian-death lifecycle acceptance
remain separate gates.

## Remaining boundary

The external wrapper is deliberately not wired to this parameter. A real
installed native worker launcher must independently map original
WorkerOriginContext, request/profile, run/parent/task identities and publish this
pin within the existing private create-only intent. Its candidate/account
isolation and installed runtime must be accepted before enabling that path.
The current fixed inert producer is insufficient. Worker-local diagnostic
lookup/recovery remains follow-up work and channel-v1 stays unchanged.

Guardian death/lifeline shutdown still lacks independent durable terminal and
cleanup records. This seam does not modify guardian C code, infer cleanup from
signals/exit 78, run numeric PID checks remotely, or solve hard disconnect and
account-isolation acceptance. No new controller, microservice or remote evaluator
is added.

The synchronous observer is installed trusted code. Deadline checks bracket its
call but cannot preempt a callback that never returns. Pre-gate refusal still
runs the original cleanup primitive; an exited bootstrap leader is not proof
that the whole group is clean. A non-success cleanup result retains
`cleanup_unknown`, its exact status/signals/alive_after and publication=false.
Tests observe the real cleanup result and check its durable record rather than
assuming a successful group cleanup from a reaped Popen child.
