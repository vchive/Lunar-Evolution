# Feature 197 — External worker origin and coordination

**Local A/B status:** origin authentication and durable assignment are implemented
and covered by the root's combined focused/static validation. The two reports
cover 366 distinct cases; after correcting two synthetic inventory test inputs,
the affected-only recheck passes and all latest outcomes are pass. No remote
deployment or distributed acceptance is established. See `validation.md`.

## Scope and authority

The default Lunar CLI remains local. A single authoritative controller owns its
SQLite ledger, original run/child/attempt claims, lifecycle journal and publication.
The database is not a shared NFS coordination service. Remote evaluation, a daemon,
service API, automatic remote launch and multiple authoritative controllers are
outside this feature's first slice.

Feature 169 already records local worker profiles, claim/heartbeat/terminal events
and quarantined unknown states. Its PID/PGID/start and inode observations belong to
one host. A source label, owner-token digest or local `flock` does not authenticate
a remote host or establish distributed ownership.

## Slice A: authenticated origin of exact receipt bytes

A trusted registry fixes one worker's `worker_id`, `host_id`, `host_boot_id`,
`key_id`, revocation state and an independently provisioned secret. Each worker
uses a distinct HMAC-SHA256 key of at least 32 bytes. The secret remains in the
trusted worker wrapper and controller; candidate programs must not receive it.
It never appears in the signed wire, object representations, error messages or
serialization. HMAC authenticates a holder of that shared secret. It is not
third-party non-repudiation, remote attestation, or proof of a machine's boot state.
The trusted registry supplies the host/boot binding.

The signer and stateless verifier use this exact canonical UTF-8 JSON object:

| Field | Contract |
| --- | --- |
| `schema_version` | `lunar-external-worker-origin-v1` |
| `algorithm` | `hmac-sha256` |
| `worker_id`, `host_id`, `host_boot_id`, `key_id` | Exact trusted registry identity |
| `controller_id`, `run_id`, `task_id`, `episode_id` | Original controller and execution identities |
| `context_kind` | `native-claim` or `launch-context` |
| `context_sha256` | Original native claim or complete launch-context digest |
| `controller_challenge` | Controller-generated 32 random bytes, encoded as 64 lowercase hex digits |
| `assignment_generation` | Positive integer, at most signed 64-bit maximum |
| `profile_sha256` | Exact original worker profile digest |
| `receipt_sha256` | SHA256 of the exact supplied receipt bytes |
| `mac_sha256` | HMAC-SHA256 as 64 lowercase hex digits |

The MAC covers a fixed domain prefix followed by canonical bytes of every field
except `mac_sha256`. Canonical encoding uses sorted keys, compact separators,
UTF-8 text and no non-finite numbers. Duplicate/extra/missing keys, non-canonical
bytes, unsupported versions/algorithms and malformed values refuse.

Verification requires independently retained expected context, expected profile
digest and actual receipt bytes. It compares all context fields and the registered
worker/key/host/boot identity before accepting a constant-time MAC comparison.
Unknown/revoked workers, key/host/context mismatch and receipt alteration refuse.
It performs no I/O, ledger writes, execution, signalling, cleanup or publication.

### Explicit replay boundary

The controller creates the challenge before assignment and retains it with the
original claim. Slice A checks its exact value but does not consume it. An exact
signed message can verify repeatedly in the same context. Atomic one-time
challenge consumption, assignment generations and stale-result fencing belong to
the subsequent authoritative ledger assignment slice. A successful verification
must not be treated as lease ownership, completion, evaluator acceptance or
permission to publish.

## Implemented local slice B boundary

The opt-in assignment API reuses the existing controller lock, started native
claim and callback journal, with a global episode namespace. It binds and consumes
the original challenge once; generation is fixed at 1, with no reassignment API.
Uncertain or disconnected work stays gated, including after reopening the ledger.
The registry also exposes a detached active public identity without its secret
for registration preflight. TTL expiry or a missing SSH connection cannot prove
remote process exit or cleanup. Multi-host delivery and deployment remain open.
The separate assignment contract and its trusted-caller ownership boundary are
in `assignment.md`.

## Acceptance

Slice A is accepted only after real HMAC signing/verification tests cover altered
MAC/receipt/context, unknown and revoked registry entries, host/boot/key mismatch,
strict wire parsing, secret redaction and same-context replay being explicitly
stateless. Provider-free tests must not imply remote process or distributed
acceptance. Existing Feature 169 and default CLI behavior remain unchanged.
