# P1 BRS child preflight (pure, non-authoritative)

Status: implemented as a pure preparation slice. This feature does not enable native
multi-child BRS, producer staging, publication, or a worker service. It is safe to
merge before the owner/worker call stack is wired because it cannot create execution
authority.

## Scope

`BRSNativeChildPreflight.from_wire` and `preflight_native_brs_child` validate an
in-memory projection of one fresh BRS wave. The projection must be built from the
controller's already durable state by a future owner integration. This module itself
does not know how to obtain that state and never reads a ledger, workspace, sidecar,
receipt, or path.

The only supported first slice is a fresh `mode=brs` wave with `max_workers=1`.
The original wave IDs are derived as
`{run_id}-practice-{wave}-{ordinal}` for contiguous ordinals `0..N-1`, with at
most eight intents. Every intent has its own request digest and all intents carry
the same detached `root_snapshot_sha256` through the projection.

## Wire and bounds

The exact top-level fields are `schema_version`, `protocol`, `run_id`, `mode`,
`wave`, `max_workers`, `root_snapshot_sha256`, `intents`, `executions`, `budget`
and `caps`. The protocol is `lunar-rsi-python-brs-child-preflight-v1`; the schema
version is integer `1`.

`budget` contains exactly `planned` and `consumed`. Both contain the eight existing
RSI counters (`practice_rounds`, `target_attempts`, `practice_episodes`,
`solver_invocations`, `unknown_retries`, `evaluator_invocations`,
`verifier_invocations`, `transfer_invocations`). A planned counter is a non-negative
integer or `null`; consumed counters are non-negative integers and cannot exceed a
finite planned limit. A wave cannot contain more intents than its planned practice
episodes or solver invocations, and completed executions must have consumed at least
one of each corresponding counter.

`caps` contains exactly `attempts`, `candidates`, `checkpoint_bytes` and
`aggregate_bytes`. They are current/prospective usage values and are bounded by,
respectively, 8 attempts, 32 candidates, 112 KiB checkpoint bytes and 64 MiB
aggregate evidence bytes. These checks are preflight refusals; they do not reserve
or consume any budget.

Input may be a strict canonical UTF-8 JSON byte string or an exact builtin `dict`
projection. Duplicate keys, non-canonical bytes, non-finite numbers, mutable
container subclasses, unknown fields, excessive depth (over 32), and inputs over
112 KiB are rejected before selection. The parser copies the accepted projection;
mutating a caller-owned dictionary after parsing cannot alter the result.

## Detached selection contract

`select_next_pending()` returns the first unexecuted intent in ordinal order, or
`None` after all original intents are executed. The returned
`BRSNativeChildSelection` contains only run/wave/ordinal/episode/request/root
identity and a literal `authority=False`. It has no claim, staging, ready/ack,
lineage, lease, owner, callback, filesystem or process field. No method in this
module can reserve, stage, claim, launch, spawn, evaluate, publish, reconcile or
grant a worker token.

The `executions` list must be an ordered subset of the original intent IDs. Foreign,
duplicate, reordered or otherwise missing IDs are refused; the preflight never
repairs the list or adopts a newer head. A future controller integration must pass
the selection into a separately specified owner/worker handoff and must retain the
existing DRS/v1 and provider-free BRS refusals when that handoff is absent.

## Acceptance

Focused tests cover canonical and duplicate-key parsing, depth/byte limits, exact
JSON shape, mutable-subclass refusal, mode/worker/ordinal identity, foreign and
reordered executions, budget accounting, all four capacity bounds, detached-copy
behavior, and the absence of authority fields. Tests do not open a ledger, touch a
file, call a process/evaluator, or exercise native dispatch.
