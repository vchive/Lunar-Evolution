# Rejected lifecycle implementation plan

The governing contract is [rejected-owner-lifecycle.md](rejected-owner-lifecycle.md).
Keep this as one continuous behavior PR. Do not split more guard-only primitives.

1. Native dispatch reuses the shared transaction and exact original owner method
   selection. Route its genuine all-rejected terminal to existing C1/P/C2/pre-arm
   methods. Preserve original source/native/control observation order and success.
2. The original lifecycle owns one private prepared-admission exchange. Its worker
   endpoint's mailbox wait-check submits one original admission request only after
   the existing owner service arms. Owner bridge invokes this exact session before
   final result construction. Neither side waits holding an observation mutex or
   workspace mutation lock.
3. Terminal observation/parser/evidence uses the genuine rejected journal and
   original rejected-provenance/C2/P pins, with manifest absent. Reuse existing
   result envelope and independent terminal snapshot kernels; do not invent a
   successful publication or a new durable schema.
4. Controller accepts actual failed terminal result and writes one exact selected
   root execution before retirement. Integrate explicit interrupted root settlement
   with existing terminal reconcile; unknown and drift remain read-only/fenced.
   Public recovery acquires one original nonreentrant lease; live settlement calls
   the exact already-held implementation, which asserts the lease before reading.
   Root execution and obligation removal share one checked SQLite transaction.
5. Update finite original policy pins once for the completed behavior graph and
   exercise natural-worker success/rejection plus interruption/recovery fixtures.
   Freeze after integrated focused/static review, then perform own-source platform,
   raw/source/import and full CI validation separately.

Implemented modules follow these boundaries: native dispatch retains the real
rejected C1/P/C2/capture; owner bridge invokes the exact original lifecycle; the
same worker performs the ready/ACK while waiting on its original mailbox; terminal
facts and independent evidence accept the genuine rejected journal without a
manifest; controller/store atomically cache the failed execution and retire only
after exact readback. The old success path and public refusal remain in place.

Development review found and corrected two composition issues before final freeze:
the live owner must not call the public recovery facade and reacquire its own
`flock`, and new terminal admission imports plus the executed canonical builder
must participate in finite alias/code policy checks. No global lock semantics or
capacity limits were relaxed. The terminal policy projection is fully computed
on each observation, then compactly hashed within the unchanged row limit.

Validation handoff: the new root fault file covers stops before root transaction,
after root commit before return, before original-channel retirement, and a channel
replacement after source observation. Every injected boundary asserts it was
reached and checks exact durable root/fence behavior and no live retry. Three
additional real-lock cases cover public recovery, already-held recovery and refusal
before observation without a lease. Final identical-source runs of all 14 new
behavior cases and 19 policy cases are pending; development snapshots remain
diagnostic evidence only.

Parallel ownership:

- Lifecycle author: this SDD, native dispatch/owner bridge, controller/store,
  original lineage policy integration, and dispatch/root behavior tests.
- Terminal reviewer: `rsi_python_brs_terminal_lifecycle.py`,
  `rsi_brs_terminal_evidence.py`, their parser/evidence/recovery tests. Agree the
  original exchange API before coding it. No simultaneous edits to shared files.
- Parent: genuine natural-worker integrated fixtures, frozen-source platform/PR
  validation and release/backlog evidence. The previous staged-ACK worktree remains
  immutable throughout this continuation.

Serial ordinal transition, append lineage, fresh per-episode binding and reserved
budget preservation remain one separate following behavior PR. Real static runtime,
project lifecycle and production CLI remain P1, with no real execution here.
