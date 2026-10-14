# Native preclaim execution-control boundary

This continuation closes a missing observation in the existing read-only
`NativeRSISchedulerProvider.validate_preclaim` gate. The retained input deadline
uses Unix time; an optional controller-owned `SolveExecutionControl` supplies a
second, fixed monotonic deadline and composed parent/run/child cancellation.
Both constrain the same child. Neither may be replaced by the other.

## Required behavior

Before reading sealed launch inputs or inspecting the episode claim, preclaim
checks the original explicit cancellation callback and calls the original shared
control's `check("rsi_native_preclaim")`, when present. Already cancelled controls,
expired monotonic controls and failed control observations refuse immediately.

After the repeated ledger/claim observation, preclaim checks both authorities
again. This rejects cancellation or expiry occurring during input/fingerprint/
ledger observations, including the final claim read. It then rereads sealed
inputs with `require_unexpired=True`, checks their original request/memory/plan
binding and compares the complete original context fingerprint. A final callback
therefore cannot extend either retained deadline or silently change broker,
intent, strategy or hooks. The cancellation callback and execution-control object
must remain the exact original objects, including when a replacement has equal
deadline fields.

The gate never constructs a control, changes `started_at`, remaps the retained
absolute deadline, replenishes a timeout, creates/settles a claim, consumes an
attestation, launches a process or invokes a producer. Caller changes are left
intact as evidence and cause refusal; the gate does not restore caller state.
Existing request/plan/ledger checks and started/terminal recovery refusal remain.
Preclaim remains an observation gate, not a reservation or launch authority;
the fresh claim/dispatch owner must still revalidate under its existing lock.

Bound contexts retain their exact failure ledger and original constructor pin.
Legacy native contexts originally constructed without that binding use only an
invocation-local pin of the gateway-supplied exact `RSILedger`, with query-only
claim observations and identity checks before/after reads and at the final return
boundary. Neither callback may replace the context, attach/drop the failure ledger,
replace the constructor pin or replace the database inode. The compatibility path
does not create persistent failure authority or weaken Python child ledger binding;
see `fresh-native-preclaim.md` for its scope.

Public scheduler refusal codes are `preclaim_cancelled`,
`preclaim_deadline_expired`, `preclaim_control_invalid` and
`preclaim_cancellation_invalid`, with the existing scheduler prefix. Retained
absolute-deadline expiry continues through the existing `launch_invalid` gate.
Context replacement or deadline drift uses `preclaim_context_changed`.

## Verification

`tests/test_rsi_native_preclaim_control.py` uses staged inert bytes and a real
local ledger with fake monotonic/wall clocks; it never executes those bytes.
Cases cover positive repeated observations without deadline extension; initial
local/composed cancellation and exact monotonic expiry; cancellation/expiry at
either claim read; explicit cancellation at the final claim read; deadline
extension, equivalent-control replacement and retained absolute expiry during
the final callback; and failed control/cancellation observers. Every case checks
absence of new claim, episode, result and producer-directory mutation.

The existing controller child-preview tests remain compatibility coverage.
Validation must use this worktree's `PYTHONPATH=src` rather than another checkout's
editable install. Focused tests, Ruff, compileall and `git diff --check` are
required on the final source. This slice provides no real model, CPython,
toolchain, OpenEvolve/Shinka campaign, remote evaluator or production runtime
evidence. `production_admission=false` remains unchanged.
