# Feature 156: producer process lifecycle and execution evidence

**Created**: 2026-09-24

**Status**: provider-free local implementation in progress

## Problem

Feature 154 defines a read-only launch intent and a one-time registration attestation, but it
intentionally stops before creating a process. Feature 155 can project evidence only after a
producer attempt has been observed. Without a lifecycle contract, a launcher could replay an
attestation, start through a shell, lose process ownership, exceed the wall-clock budget, or
publish an output file whose bytes changed while it was being read.

## Outcome

Define one fail-closed local producer execution lifecycle. The lifecycle consumes an exact
attestation once, starts the pinned executable with `subprocess.Popen` and no shell in a new
process group, durably records the exact PID/PGID before releasing a producer work gate, captures
bounded stdout/stderr, enforces one monotonic deadline, verifies the output envelope by bytes and
no-follow file identity, and writes a durable execution receipt.

Every uncertain observation is terminal `unknown`/`recovery_required`. The launcher never silently
restarts a producer after timeout, missing evidence, liveness uncertainty, output-write
uncertainty, cleanup uncertainty, or a controller crash. This feature remains provider-free: the
producer is a local executable fixture selected by the launch intent; no model provider,
evaluator, scheduler campaign, or publication transaction is invoked here.

## Scope

This feature covers:

* exact-match, consume-once attestation registration;
* no-shell process creation with a new process session and exact PID/PGID ownership;
* a registration-before-work gate and durable launch receipt;
* monotonic wall-clock and request/output ceilings, with no budget reset;
* caller-owned cancellation observed during capture and process wait, with bounded cleanup;
* bounded, concurrent stdout/stderr capture;
* no-follow output-envelope reads with byte, size, inode, and digest rechecks;
* owner-checked SIGTERM/SIGKILL process-group cleanup using the existing primitives; and
* durable terminal execution evidence for the Feature 155 adapter.

It does not define provider calls, candidate scoring, Feature 150--153 admission/publication,
automatic solve defaults, remote transport, or an external campaign acceptance claim.

The native trusted path now has a create-only formal receipt boundary: once terminal, bounded
streams, stable envelope, host-broker, target-binding, deadline, and cleanup evidence all verify,
it persists `execution-receipt.json` and exposes its canonical digest. Feature 153 may consume
that digest before staging and record it in the publication journal. The handoff is deliberately
one-way: publication does not rewrite the receipt. A provider-free native trusted scheduler now
composes one attempt, receipt persistence, strict output projection, and optional publication, with
a read-only recovery projection that cannot relaunch or consume another attestation. This is a
supporting composition boundary only and does not close the trusted-bootstrap, production
controller transport, cross-process recovery, or real-campaign gaps listed below.

## Lifecycle state machine

```text
preflight_passed
  -> attestation_consumed
  -> launch_prepared
  -> process_registered
  -> running
  -> completed | failed | cancelled | unknown

unknown -> recovery_required (terminal)
failed/completed/cancelled -> execution_receipt_durable (terminal)
```

`process_registered` is reached only after the durable receipt contains the exact PID, PGID,
attestation digest, intent digest, executable identity, and owner identity. The child process is
held behind a private gate until that state is durable; releasing the gate transitions to
`running`. If the executable cannot participate in the gate protocol, the launcher must reject
the launch rather than claiming that registration preceded producer work.

The lifecycle has one attempt. A nonzero exit, malformed result, or observed output-limit breach
is a known `failed` outcome. A timeout, missing PID/PGID evidence, failed liveness probe,
controller interruption, uncertain signal delivery, uncertain output write, or uncertain cleanup
is `unknown` and requires explicit recovery. Recovery may inspect and clean the exact registered
process group, but it never starts a replacement process under the same intent or attestation.

## Exact attestation consumption

The caller supplies the `ProducerLaunchAttestation` from Feature 154 and the already validated
`ProducerLaunchIntent`. Before creating a child, the launcher compares every attestation field:

* launch, reserved journal, run, parent-task, and task identifiers;
* exact `intent_sha256`;
* executable SHA-256 and exact size, device, inode, `mtime_ns`, and `ctime_ns`; and
* attestation schema, protocol, nonce, and self-digest.

The nonce is claimed with an atomic create-only operation in the system-derived launch directory
(regular file, no-follow, bounded, and fsynced). The claim records the attestation and intent
digests, launch identity, and a consume operation identifier. A duplicate nonce, an existing
claim with any different bytes, or a crash that leaves the claim status uncertain rejects the
launch. Claiming is irreversible for this lifecycle, including when `Popen` later fails.

The claim and all identity checks occur again immediately before spawn. Path strings, a prior
preflight result, or a producer-supplied file cannot substitute for the attestation. No secret,
prompt, provider response, or arbitrary exception text is stored in the claim.

## Process creation and work gate

The launcher invokes `subprocess.Popen` with an argument list, `shell=False`, `start_new_session=True`,
`close_fds=True`, a derived working directory, and bounded pipes for stdout and stderr. It never
constructs a shell command or interpolates untrusted text. Standard input is closed. The executable
path and `argv[0]` must remain the exact pinned values from the intent; any drift aborts before
spawn.

The child receives a private, fixed gate descriptor through the launch protocol. The direct
launcher supports only a cooperating fixture contract: the target must block before producer work
until the parent releases that descriptor. Immediately after `Popen`, the parent verifies `pid`,
`pgid == pid` (or the exact recorded session group), executable identity, and owner predicate,
then atomically writes and fsyncs the launch receipt. Only a durable `process_registered` receipt
permits gate release. A child that exits before release is `failed` unless the parent cannot
determine the reason, which is `unknown`.

This observation does not prove that an arbitrary executable waited. A producer can write files,
fork, leave the process group, or use the network before reading the gate. External admission
therefore requires a Lunar-owned, attested bootstrap whose first action is the gate wait; the
bootstrap may start the pinned producer only after the parent registration is durable. Until that
protocol and its identity digest are part of the intent and receipt, arbitrary direct targets are
out of scope and the runner remains provider-free prototype behavior.

The executable bytes actually run must be bound to the attested bytes. Checking the source path
immediately before `Popen(executable=path)` is insufficient: a concurrent rename can replace the
path between the check and the kernel's open. On macOS, executing a shebang script through a held
`/dev/fd` descriptor fails, and Python exposes no `fexecve`/`execveat` fallback there. The Darwin
implementation stages verified bytes into a private `UF_IMMUTABLE` snapshot and binds its digest
and binding mode in the registration and terminal receipts. On Linux, the runner copies the
attested source into a sealed executable memfd, keeps its descriptor open through `Popen`, and
passes that descriptor to the child so a shebang interpreter reopens the sealed script through
`/proc/self/fd`. The registration and terminal receipts bind the sealed digest and binding mode;
replacement after the final source check therefore cannot change the executed bytes. If Linux
memfd sealing or `/proc/self/fd` is unavailable, launch fails before process creation. Other
platforms still use `pathname_unbound` prototype behavior and cannot satisfy external executable
admission.

The durable receipt is written with a bounded temporary file, `fsync`, and no-follow atomic rename;
the destination and every existing ancestor must be a regular directory without symlinks. The
receipt is never overwritten by a different launch, and each state transition binds the previous
receipt digest.

## Budgets and deadline

The intent's `request_timeout_seconds`, `max_requests`, `output_max_bytes`, and
`wall_timeout_seconds` remain independent ceilings. The launcher derives one monotonic deadline at
the launch gate and passes the remaining time to every wait, pipe-drain, cleanup, and output-read
operation. An optional caller-owned `parent_deadline` in the same monotonic clock domain is
composed by taking the earlier deadline; it cannot widen the intent allowance. No retry, signal
grace period, receipt write, or recovery inspection resets or widens that deadline. A request counter is observed from the bounded producer envelope; missing,
negative, contradictory, or over-limit counters produce `failed` when observed deterministically
and `unknown` when observation itself is incomplete.

Wall-clock expiry or an observed caller cancellation causes an owner-checked SIGTERM followed by bounded SIGKILL escalation through
`process_ownership.cleanup_registered_process`. The process group is probed after each step. If
ownership or liveness cannot be proven, the result is `unknown`/`recovery_required`; no signal is
sent to a reused PID or PGID and no replacement launch is attempted.

The optional `cancelled` callback is process-local authority supplied by the caller. It is checked
before launch, after durable registration, during nonblocking stdout/stderr capture, and while
waiting for the leader. A callback that raises or returns a non-boolean value fails closed. A
verified cleanup produces one durable `cancelled` receipt; uncertain cleanup remains `unknown`.

## Bounded output capture

Stdout and stderr are drained concurrently while the process runs so a full pipe cannot deadlock
the lifecycle. Each stream has a fixed byte ceiling derived from the launch budget. Bytes beyond a
ceiling are not retained; the launcher records a fixed `output_limit_exceeded` observation and
terminates the owned group. A read, close, or capture-write failure whose final bytes cannot be
established is `unknown`. Receipts contain stream byte counts, truncation flags, and SHA-256
digests, never unbounded producer text.

## Output envelope evidence

After process termination and verified cleanup, the launcher looks only at the intent's derived
`producer-result.json`. It opens the file with no-follow semantics, checks every existing ancestor,
requires a regular single-link file, and rejects a size above `output_max_bytes`. It records device,
inode, size, `mtime_ns`, and `ctime_ns` before reading, reads exactly the bounded bytes, then
rechecks the same identity and size. A digest is calculated over the exact bytes. Any replacement,
symlink, truncation, append, parse failure, or read race is `failed` when conclusively observed and
`unknown` when the final state cannot be established.

The lifecycle records envelope evidence only. Feature 150/151/152 remains responsible for
validating `lunar-producer-result-v1`, explicit groups, candidate bundles, and authority; Feature
155 may project the successful execution receipt only after cleanup and envelope evidence are
verified.

## Cleanup and recovery

Before every SIGTERM or SIGKILL the launcher rechecks the exact PID/PGID and durable owner
predicate. It uses the existing process-ownership result, including `cleanup_unverified`, as
evidence rather than treating a missing leader PID as proof that the group exited. A cleanup
callback or OS error is retained as a fixed code. Any uncertain cleanup, output write, receipt
commit, or controller death is terminal `unknown`/`recovery_required`.

Recovery reads only the exact launch receipt and process registration. It may finish owner-checked
cleanup and write a terminal recovery receipt, but it cannot consume a second attestation, alter
the intent or budget, reinterpret producer output, or launch a replacement. A terminal receipt is
the only result exposed to downstream publication code.

## Acceptance

1. Exact attestation and executable identity are checked and consumed once; replay and every
   tuple, intent, byte, inode, nonce, or schema mismatch fail before spawn.
2. Process creation is no-shell, no-credential, no-follow, new-session `Popen`; a durable PID/PGID
   receipt exists before the work gate opens.
3. One monotonic deadline covers launch, gate, execution, capture, cleanup, and envelope
   observation; a retry cannot reset it.
4. Full-pipe stdout/stderr capture is bounded and concurrent; over-limit and read-uncertain cases
   are represented without unbounded text.
5. Output envelope bytes and no-follow identity are stable across the read and carry a canonical
   digest and bounded size evidence.
6. Owner-checked process-group cleanup never signals a reused identity; timeout, liveness,
   output-write, receipt-write, and cleanup uncertainty become terminal `unknown`/`recovery_required`.
7. Provider-free local fixtures cover success, replay, shell rejection, gate failure, timeout,
   output overflow, symlink/race tampering, cleanup uncertainty, controller interruption, and
   recovery. No real provider, external producer campaign, evaluator, or WebAgent is run.
8. A deterministic replacement between the final source check and process creation cannot run
   un-attested bytes while producing a successful execution receipt.
9. A hostile direct target that performs a side effect before reading the gate cannot produce a
   completed receipt; external admission uses only an attested Lunar-owned bootstrap.

## Implementation checkpoint (2026-10-01): lifecycle composition wrapper

The provider-free implementation now exposes `run_native_trusted_lifecycle` and
`recover_native_trusted_lifecycle` from `producer_lifecycle`. The run entry point delegates one
native trusted attempt to the scheduler, persists and verifies the formal execution receipt,
projects strict same-attempt output preparation, and invokes the existing publication transaction
only when a caller explicitly supplies its strategy. The recovery entry point is read-only: it
revalidates retained receipt and output evidence and cannot spawn, consume a second attestation,
widen a deadline, or publish.

The existing cooperative `run_producer_lifecycle` contract is unchanged. The projected DTO now
also exposes native run/recovery observations, broker coverage, request coverage, and publication
status so callers cannot mistake preparation for publication eligibility. Focused tests cover
projection, explicit publication, preparation-only mode, read-only recovery, and fixed scheduler
error mapping.

This is an orchestration boundary, not a claim that Feature 156 is complete. Full production
registration/cleanup and cross-process recovery, host-observed broker enforcement, real scheduler
campaign wiring, and external producer acceptance remain open. All validation in this checkpoint
uses local provider-free doubles and fixtures.
