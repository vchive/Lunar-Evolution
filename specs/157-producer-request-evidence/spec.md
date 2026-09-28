# Feature 157: cooperative producer request evidence

**Created**: 2026-09-24

**Status**: host broker wired to optional isolated native attempt; durable lifecycle receipt integration deferred

## Problem

Feature 156 carries `request_timeout_seconds` and `max_requests`, but its parent process only
controls process wall time and reads a producer-declared request counter from the result envelope.
An arbitrary executable can claim a count or timing value, so the lifecycle must not describe that
declaration as host-enforced request evidence.

## Contract

`ProducerRequestEvidence` is an optional, bounded, provider-free payload emitted by a trusted
producer SDK. It binds to the exact launch/journal/run/parent/task tuple and the Feature 156 intent
digest and repeats the two request budgets. Every observed request has a sequence, opaque bounded
request ID, terminal status, and elapsed duration in milliseconds measured by the SDK's monotonic
clock. The payload declares `coverage=complete` only when the SDK contract says every request is
represented; `partial` evidence is retained for diagnostics and cannot establish budget compliance.

The payload is canonical JSON with an SHA-256 self-digest. Unknown fields, duplicate keys,
non-contiguous sequence numbers, duplicate request IDs, invalid durations, identity drift, and
budget drift fail closed. No prompt, provider response, credential, or arbitrary producer text is
stored. The parser bounds both the payload and number of events.

The parser's assessment is deliberately conservative:

* `within_declared_limits` means only that complete SDK-declared events fit the repeated count and
  duration ceilings;
* `declared_limit_exceeded` means the declaration reports a timeout, overlong request, or count
  over the repeated budget; and
* `insufficient_evidence` means coverage is partial.

All assessments carry `enforcement=cooperative_declaration`. The SDK clock is not comparable to
the controller clock. Parsing and assessing this payload therefore never claims that the parent
enforced a per-request timeout or that an arbitrary executable actually made the requests.

## Deferred lifecycle integration

Feature 156 may consume this DTO only after it defines a trusted SDK transport and a host-visible
receipt boundary. A future integration must choose one of:

1. a controller-owned framed evidence pipe whose reader records each event before process exit; or
2. a controlled producer runtime whose SDK is part of the pinned executable contract.

Reading a file written by an arbitrary child after it exits is still a declaration and must not
upgrade the receipt to `request_timeout_enforced`. The existing wall-clock deadline and output
capture remain the only host-enforced limits until that contract exists.

`HostRequestLedger` and `HostRequestJournal` provide bounded controller-side admission,
monotonic timing, fsynced append-only records, and read-only crash recovery for brokered
requests. The optional native attempt now passes only anonymous request/response pipes to
the isolated target. Its controller thread accepts bounded canonical JSON frames, sends
each accepted body to one host-configured endpoint through `ControllerOwnedRequestBroker`
and `ControllerHttpTransport`, and returns a bounded response over the pipe. The target
receives neither endpoint nor credential. The journal is created outside target write
directories before the release gate opens. Missing initialization closes the gate.

This path is still `brokered_requests_only`. The process-only native terminal receipt
does not bind a broker journal or authorize publication. A complete execution receipt,
recovery-safe broker handoff, and scheduler admission remain deferred. See
`transport-design.md` for the production transport and isolation requirements.

## Non-goals

This feature does not call a provider, inspect prompts or responses, enforce remote token/cost
limits, change `run_producer_process`, or connect the payload to scheduler defaults.
