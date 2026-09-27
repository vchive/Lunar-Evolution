# Controller-owned request transport boundary

`HostRequestLedger` is a provider-free accounting primitive for a future controller-owned
request broker. The controller creates it from the immutable Feature 156 launch intent.
At the broker's entry point, before any outbound I/O, the controller calls `admit` with a
bounded opaque request ID. The ledger reserves one of at most 16,384 request slots and
returns an identity-bearing admission and a controller-monotonic deadline. A controller
that actually performs the outbound I/O calls `finish` with its own terminal result, or
`expire` when its deadline fires. The producer cannot supply duration or terminal timing.

The resulting snapshot says `coverage=brokered_requests_only`. It must not be translated
into the cooperative `ProducerRequestEvidence` DTO, whose clock is explicitly the SDK
clock, or into a complete host-enforcement receipt. `within_broker_limits` is true only
when every admitted request has a terminal event and none is timed out; it says nothing
about requests that bypassed the broker. Ledger transitions are serialized per
instance; journal append and close are serialized separately so concurrent admissions
cannot reuse a sequence or interleave hash-chain records.

`HostRequestJournal` now persists each admission and terminal event to a new, bounded
append-only file. Each canonical JSON line carries an ordinal, previous-record digest,
and self-digest. It is fsynced before the ledger state advances. The first line binds the
exact launch/journal/run/parent/task tuple, intent digest, and request budgets. A failed
write poisons that journal handle. Read-only recovery validates every line and reports
unclosed admissions and timed-out records as uncertain, without resuming them. A deadline
record alone does not establish that provider I/O stopped. It rejects symlinked file and
ancestor paths. The controller must place this file in an OS-protected directory that the
producer cannot write; a hash chain alone does not authenticate bytes against a child
that can edit the journal with the controller's credentials.

`ControllerOwnedRequestBroker` now provides the provider-free transport boundary. It passes
the exact controller-issued admission and deadline to a controlled transport handle, and
sets `host_timeout_enforced=true` only after cancellation is acknowledged and the terminal
state is `cancelled`. An accepted
cancellation followed by `completed` or `failed` remains unconfirmed for timeout enforcement.
A transport that returns an invalid status or cannot confirm cancellation fails closed;
the admission remains active without a confirmed stop, even after the deadline.
The transport contract requires bounded `start`, `wait`, and cancellation operations and
synchronous cleanup after a partial startup failure. The broker cannot interrupt a blocking
transport that ignores those requirements, so these declarations are not production proof.
The broker never stores request payloads and does not expose a producer-side transport path.

`ControllerHttpTransport` is a concrete POSIX transport for brokered HTTP POST requests.
It starts one trusted, standard-library worker per admission, keeps request and response
bytes in bounded anonymous IPC, and applies the admission's absolute monotonic deadline
to parent-side IPC and worker HTTP I/O. Its handle returns a typed `TransportResponse`
only after an on-time completed exchange; `BrokerRequestResult.response` exposes that
value to the controller without writing it to the host journal. Failure and timeout
results carry no response. Cancellation reports success only after the exact worker has
received a kill signal and been reaped. A startup or IPC failure that cannot confirm
worker termination leaves the admission uncertain. If the worker exited before a cancellation
signal, its unparsed outcome cannot be upgraded to a confirmed timeout. Process creation and
OS scheduling are not hard-real-time bounded, so this is an exercised local I/O boundary rather than
proof of a production-wide request deadline.

## Required production integration

1. The controller must own the actual request transport. Only its broker can call the
   provider, and the producer runtime must have no alternative provider network or
   credential path. Pin and attest that runtime alongside the launch intent. Otherwise
   the host can prove only that *brokered* requests were observed.
2. The controller must apply each admission's deadline to all transport phases and
   cancel/close the underlying I/O at the deadline. The ledger records deadlines but
   does not interrupt a blocking transport. Wall-clock polling after a call returns is
   insufficient to claim per-request enforcement.
3. Integrate the bounded append-only host journal with the actual transport owner, and
   isolate its directory from the producer. Recovery already treats a missing terminal
   event as uncertain, but cannot infer whether a remote request continued after a crash.
   Timed-out records remain uncertain on replay because they do not encode an I/O-stop
   acknowledgement. No producer-written file can fill that gap.
4. Feature 156 can set `request_timeout_enforced` only after all three conditions above
   are tested against a fixture that bypasses the broker, one that hangs during I/O, and
   one that crashes the controller after admission. Until then, retain the existing
   declaration-only and process-wall-time semantics.

The current implementation completes bounded host accounting, a fixture-level durable
journal, and a real HTTP worker for requests explicitly routed through the broker. It does
not prove complete provider egress coverage, own a protected production journal directory,
or integrate with Feature 156, so T157-05 and T157-06 remain open.

## Native producer isolation boundary

The controller may attach a `ProducerIsolationPolicy` to a trusted bootstrap launch.  The
policy is canonical JSON containing a platform profile, exact canonical read paths, exact
write directories, and a self digest.  The native bootstrap applies it after the release gate
and before target `exec`; the target cannot select or broaden the policy.  On Darwin the profile
is deny-default SBPL and denies all network operations while granting only the pinned executable,
its declared work/output directories, and required read files.  On Linux the native boundary
requires Landlock and a no-new-privileges seccomp filter that denies network and process escape
syscalls.  Kernels without the required interfaces fail before target exec.

This boundary is evidence for the target process that actually passes through the trusted
bootstrap.  It does not isolate a process started outside that bootstrap, and it does not prove
that a controller owns every provider request until all provider egress is routed through the
controller broker.  The policy digest and native isolation result must be retained with the
bootstrap registration; a missing or failed result is unknown and cannot be upgraded by a
producer-written receipt.
