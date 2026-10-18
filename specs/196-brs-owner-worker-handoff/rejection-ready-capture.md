# Original rejected-owner pre-arm capture

This is the connected pre-arm part of [rejection-owner-ready.md](rejection-owner-ready.md),
on top of PR132's accepted read-only observers. It is not the staged ready/ACK service.

The exact original `_BRSLineageCheckpointOwner.retain_rejection_ready_capture()` consumes
one capture attempt after its own confirmed C1/P/C2. The owner remains in
`rejected-provenance`. A successful call retains an internal immutable tuple; any failure
poisons the owner, and neither success nor failure can refresh or retry the capture.
It does not arm, wait for, dequeue, acknowledge or complete a worker request.

The retained comparison data includes original owner object custody, all six raw ledger
row groups and schema rows, original Condition/native RLock operations, original selected
scope, canonical admission reference/record bytes and record digest, and the exact
three-field ready payload (plan, prepared journal, anchor). The ledger domain is the union
of the original complete wave episode IDs and all held C2 admission-reference episode IDs.
Existing original run/episode/claim, budget/M0/intents/executions, P body/writer-returned
pin, source/material pins and database inode checks remain in force.

The existing-reference reader passes original run/C2/episode heads explicitly to
`RSILedger.python_admission_record`. It compares every head returned by rebuilt evidence
to those held heads and compares complete canonical record/reference bytes. It never
adopts the current checkpoint or calls the fresh-reference handler, registration or CAS.
All dynamic semantic/material checks run between two equal complete raw ledger captures;
the final comparison is followed by original inode, deadline, custody and empty-channel
checks. Semantic readers run outside both short observation and Condition locks.

Once the pre-arm Condition capsule exists, the original empty-channel validator verifies
it before acquiring its held native RLock and again inside that lock. This preserves the
old empty-domain refusal while preventing an intermediate callback from installing a
replacement Condition context operation. Queued, duplicate, closed or cancelled channels
are not a new baseline. No request is temporarily removed to pass an old getter.

A separate import-time finite guard covers new capture/reference functions, raw SQL
reader functions/constants, original observer entry points and declared runtime aliases.
It rejects function/code/default/closure/metadata/namespace drift before constructing the
compact policy projection. The enclosing owner policy independently retains that guard's
entry and closure. This projection is for unlocked pre-arm validation; complete final ACK
physical/context/DTO custody and stdlib cache-state review remain required.

Validation uses the genuine waiting worker and sealed local one/two-candidate fixtures.
Tests cover no durable/file/claim/budget change, original heads, one-shot consumption,
early natural enqueue without ACK, raw drift during an unlocked callback, replacement
P inode, closed channel, foreign thread and reader shadows. The reference reader and
finite guard also have focused negative matrices. Matching frozen macOS/Linux evidence,
independent review and complete dependency-ordered CI are separate acceptance gates.

The next implementation must bind the retained data to the same original pending request,
add `armed -> inflight -> committed/failed`, complete the final-reader graph and stage the
ACK until the last fixed gate. Capture data alone grants none of these permissions.
Dispatch, result/recovery, root settlement, owner retirement, serial successor and real
runtime/solver/CLI acceptance remain later work. Public native BRS, production admission
and online publication stay closed; only local inert/provider-free fixtures are used.
