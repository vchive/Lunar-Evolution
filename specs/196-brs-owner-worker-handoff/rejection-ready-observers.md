# Rejected-owner ready channel observation prerequisites

## Scope

This implements two read-only prerequisites of
[rejection-owner-ready.md](rejection-owner-ready.md), following the bounded ledger
reader in PR131. It does not implement the original owner's one-shot ready service
or make an ACK visible. The owner still has no new ready arm/take/commit path.

The existing admission `service()` publishes its ACK before its observation context
exits. A separate transport instance would also be insufficient to enforce the
original owner's one-shot scope: another instance could be constructed for the same
channel. Keep those problems in the later owner integration. Do not introduce a
callback, digest argument or caller-created permit to bypass the missing owner gate.

## Synchronization custody

An internal synchronization observer captures the exact original Condition, native
RLock, bound native operations and waiter deque. It checks the finite Condition
methods and their declared transitive dependencies against independently retained
import-time bindings. A first capture must reject already replaced methods or
aliases; accepting current code as the baseline is insufficient.
Preserve the original presence or absence of stdlib aliases with an independently
held missing sentinel: Python3.12 does not expose `threading._islice`. Absence is
different from a present null value; adding, deleting or replacing a binding must
still fail against that platform's retained original domain.

Validate exact types, plain string attribute keys, allowed instance attributes and
bounded native waiter domains before invoking methods, performing lookups or
comparing values. Reject Condition subclasses, instance method shadows, replaced
native locks/operations, foreign waiters and changed function code/defaults/metadata.
The observer itself must not acquire through an unvalidated Condition context or
call a waiter callback. It never waits, notifies, closes or releases a worker.

The guard is local comparison data. It does not pin the controller observation
context, physical file readers, SQLite graph, material DTOs or the complete final
ACK reader. It grants no ownership, semantic validity or execution authority.

## Selected queued request custody

The channel observer receives a primitive expected domain supplied by the future
original owner: original owner thread, run, complete episode domain, selected
episode/handoff digest and consumed singleton nonce. It requires the original
selected, uncompleted handoff and exactly one genuine queued request.

Under the validated original native lock it captures the original channel,
Condition/lock, queue, requests, nonce/completed containers, pending and detached
ready object identities, together with immutable plain field values. Equal-value
replacement containers, pending objects or ready DTOs must fail a later comparison.
The observer retains the ready bytes and digest as raw comparison data; canonical
encoding, digest recomputation and admission semantics require the separate complete
semantic validation bracket. No DTO serializer,
JSON parser, user equality hook or arbitrary callback runs under the lock.

Only the queued state is supported: queue contains that pending, servicing is false,
pending state is queued, cancelled is false, error/ACK/ACK fields are null, and the
selected-completed set is empty. The observer does not arm, dequeue, stage/construct
an ACK, mutate a pending field, close, notify, reserve budget or write a ledger row.
The capsule is not an authorization token. Semantic admission, C2/P custody and
original owner's one-shot state remain separate required gates.

## Validation and remaining integration

Use real inert worker threads through unchanged `request()` and genuine selected
handoff binding; do not inject a pending. Cover successful capture/recheck without
ACK, equal-object replacement, primitive/type drift, shadows and callback traps,
close/cancellation/legacy service transitions, and bounded waiter/domain checks.
Fixtures close before bounded join, outside both observation and Condition locks.

Run focused tests, Ruff, compileall and diff checks. Freeze a single source and use
matching macOS/Linux test inventories and isolated editable imports before scoped
acceptance. Independently review the implementation and raw evidence. Complete
GitHub CI remains required for main integration.

The next original-owner slice must retain C2/reference/run/episode/claim/P pins,
establish unused/armed/inflight/committed state on that exact owner, bracket full
semantic validation with the bounded ledger captures, and finish the physical,
deadline and finite-reader gates. Only then may a dedicated final condition hold
assign permanent ACK fields. Public native BRS, production admission and online
publication remain closed; P2 and remote evaluation remain deferred.
