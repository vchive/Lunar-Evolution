# Feature 158: trusted producer bootstrap gate

**Created**: 2026-09-24

**Status**: Provider-free trusted-bootstrap fixture and production launch identity adapter implemented; native formal receipt persistence and the optional Feature 153 publication-journal handoff are available, while Feature 156 lifecycle completion, recovery-safe broker integration, and scheduler integration remain deferred

## Problem

Feature 156 records a process registration before writing one byte to a gate descriptor, but it
currently starts the producer executable itself. An arbitrary executable may perform work, fork, or
escape its process group before reading that descriptor. A cooperative fixture can demonstrate the
intended order, but the parent cannot prove the property for a general producer.

Feature 158 defines the smallest trusted boundary that closes this gap. A Lunar-owned bootstrap,
whose exact executable identity is pinned, blocks before loading or starting producer code. The
parent releases the bootstrap only after Feature 156's registration receipt is durable. The
bootstrap then starts exactly one attested producer in the registered process group.

## Outcome

Specify a provider-free `trusted-bootstrap-v1` protocol and its evidence. The protocol binds a
bootstrap digest, launch/intent/attestation identities, target executable identity, and one gate
transition. It gives Feature 156 a verifiable statement:

```text
trusted bootstrap reached its gate
  -> Feature 156 registration receipt became durable
  -> parent released exactly one gate token
  -> bootstrap started the target producer
```

The checked-in fixture launches only a pinned local target and is not a producer scheduler entry
point. The feature does not enforce provider request limits, publish output, or integrate the
runtime into Feature 156's production launcher. It provides the controlled evidence required
before a later implementation can claim gate-before-producer-work.

## Scope and boundaries

Feature 154 supplies the immutable launch intent, reserved journal identity, authority projection,
target executable pin, paths, and budgets. It performs no process operation.

Feature 156 owns attestation consumption, PID/PGID registration, wall-clock execution, stream and
envelope evidence, cleanup, recovery, and the terminal execution receipt. Feature 158 changes only
the pre-work process boundary used by a future Feature 156 implementation: the registered process
is the trusted bootstrap until the target is handed off in the same process group.

The native trusted attempt must receive the same caller control boundary as the cooperative runner
when this handoff is integrated. An optional process-local `cancelled` callback is observed before
spawn, after registration, while waiting for bootstrap/target frames, and while waiting for the
leader. An optional caller-owned `parent_deadline` uses the same monotonic clock domain as the
intent deadline; the effective deadline is the earlier of the two and can never widen the intent
budget. A verified owner-checked cleanup may produce a `cancelled` process receipt, while callback
errors, invalid callback results, deadline expiry, or cleanup uncertainty remain
`unknown`/`recovery_required`. These controls are runtime inputs, not launch identities, and must
not be omitted from a later lifecycle audit or used to create a second attempt.

Feature 157 remains the optional cooperative SDK request-evidence contract. Bootstrap evidence
does not upgrade SDK declarations to host-enforced request timeouts. Features 150–153 and Feature
155 remain downstream output/admission/publication consumers; no plan or journal content is needed
to start the bootstrap.

No automatic solve default, scheduler, remote transport, provider, evaluator, campaign, or real
external producer is changed by this feature.

## Trusted bootstrap identity

The bootstrap is a Lunar-owned executable or platform-supported runtime entrypoint, never a path
selected by the producer. A `TrustedBootstrapDescriptor` contains:

* protocol and implementation version;
* exact bootstrap SHA-256, byte size, device/inode and timestamp identity;
* an allowlisted bootstrap identity selected by the local installation; and
* the platform execution mode used to bind those bytes to the started process.

The descriptor is checked before spawn and again by the process-registration handshake. A path
recheck alone is insufficient: Feature 156 task T156-11's executable replacement window remains
a release blocker. On platforms without descriptor-bound execution for the chosen binary format,
the implementation must use a controlled immutable runtime/copy protocol or remain fixture-only.

## Gate protocol

The parent creates a private gate channel and starts the trusted bootstrap with a sanitized,
bounded launch record. The bootstrap protocol is:

1. enter the fixed startup routine and validate only bounded protocol fields and descriptor
   digests;
2. emit one `bootstrap_ready` frame containing the launch and intent digests;
3. block on the gate channel. Before the one-byte release token is received, it must not import,
   execute, spawn, or open the target producer, and must not write producer output;
4. after exactly one valid release token, verify the target descriptor again and start exactly one
   target producer without a shell, preserving the registered process group; and
5. emit one `target_started` or fixed `target_start_failed` frame. Duplicate tokens, malformed
   frames, EOF before release, or a second target start are terminal failures.

The `bootstrap_ready` frame is not authority by itself. It is evidence only when the bootstrap
bytes match the pinned trusted descriptor and the parent can show that the registration receipt
was fsynced before the release write. A fixture must include a pre-gate marker from the bootstrap
and a post-release marker from the target; the parent asserts that the target marker is absent at
the release boundary. A hostile direct producer fixture that writes before reading its gate must
be rejected from this protocol and must never produce a successful `trusted-bootstrap-v1` receipt.

The bootstrap may perform bounded setup needed to parse the launch record and establish the gate.
“Before work” means before any target producer code, target import, target child, output, or
request is started. The bootstrap itself remains a trusted Lunar component and is covered by its
own executable identity.

## Process and cleanup binding

Feature 156 registers the bootstrap PID/PGID, bootstrap descriptor, target descriptor, protocol,
and exact launch/intent/attestation digests before release. The target must remain in that process
group and may not create a new session. A target that escapes the group, starts before release, or
starts more than once is `unknown`/`recovery_required`; cleanup never signals an unverified PID or
PGID.

Durable bootstrap evidence retains the target-start frame's observed PID and PGID as well as the
SHA-256 of their canonical pair. A recorded start requires both values and a matching pair digest;
an unstarted attempt requires all three to be absent. Formal cross-record observation also requires
the target's start-time PGID to equal the registered bootstrap PGID. This checks the start frame,
not whether the target or its descendants later leave that group.

The bootstrap does not consume a second attestation. It receives the already consumed, exact
launch record and cannot widen budgets. Timeout, handshake uncertainty, target start uncertainty,
cancellation, or cleanup uncertainty retain Feature 156's terminal unknown semantics and never
trigger a retry. The native process-only receipt must bind the effective deadline outcome and
cleanup status without treating a callback or parent deadline as a substitute for formal request,
output, or publication evidence.

After the complete native evidence projection succeeds, Feature 156 persists the formal
`execution-receipt.json` create-only and exposes its digest. Feature 153 can pass that digest into
the publication transaction, which records it in the canonical publication journal only after
receipt identity, successful terminal, cleanup, and broker-coverage checks. This handoff does not
replace the bootstrap's registration/recovery obligations or make the fixture a scheduler entry
point.
The fixture's timeout is one absolute monotonic deadline measured from the attempt start. Both
owner-checked cleanup grace phases are clipped to that deadline; after expiry, a leader reap is
bounded and any remaining liveness is recorded as `unknown`/`recovery_required` rather than
extending the attempt with an unbounded wait.

## Proof limits

The protocol proves ordering only under the trusted-bootstrap threat model: the pinned bootstrap
bytes run as declared, the local owner and filesystem are not compromised, and the target handoff
uses the platform-supported exact-byte mechanism. It does not prove the absence of work by an
arbitrary direct executable, a malicious host, or a target whose bytes were replaced in the
T156-11 window. A passing cooperative fixture is necessary but not sufficient for external
campaign admission.

## Acceptance criteria

1. The bootstrap descriptor is canonical, bounded, exact-byte pinned, and rejects path, digest,
   identity, platform-mode, and protocol drift before spawn.
2. A trusted bootstrap emits `bootstrap_ready`, blocks, and cannot start target code before one
   valid release token. The parent persists and fsyncs Feature 156 registration before release.
3. The target starts exactly once after release, inherits the registered process group, and emits
   bounded target-start evidence. Duplicate/early/late/malformed handshakes fail closed.
4. A hostile direct producer that performs pre-gate work is not accepted as a trusted bootstrap
   execution, even if its eventual output is valid.
5. Registration, wall deadline, cleanup, unknown recovery, and output evidence remain Feature 156
   responsibilities; bootstrap evidence cannot claim request-level host enforcement from Feature
   157 declarations.
6. Provider-free controlled fixtures prove pre-gate target-marker absence, durable-receipt-before-
   release ordering, target post-release start, duplicate-token rejection, target group retention,
   and recovery without relaunch. No scheduler default or external campaign runs.
