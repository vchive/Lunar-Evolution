# Selected owner waiting during episode settlement

## Problem and scope

An inert, acknowledged selected worker may append its completed episode while the
owner waits for the future. The owner's repeated full admission check captures a
running episode head in one connection and compares it in another. A deterministic
barrier reproduces `rsi_python_admission_episode_conflict` in both the old mutation
fixture and the unmodified success case. The original failing logs/XML remain
separate evidence; a fixture correction alone does not resolve the positive race.

Change only the private selected owner wait loop and shared fixed pin projection.
Do not change store CAS, generic/DRS admission checks, public dispatch, wire/schema,
publication authority, or retry/recovery. `production_admission=false` remains.

## Validation boundaries

Keep the complete selected invocation gate at binding and worker entry, in the
real ready-service observation scope before ACK delivery, after `future.result()`,
and again after channel close and successful executor shutdown. It retains all
original admission record, canonical episode/native claim, file pin and captured
head checks. Only this complete final validation can precede a usable return receipt.

While the future is pending, use an explicitly named private wait gate. It checks:

- exact original selected handoff identity before and after caller hooks;
- actual controller/ledger/workspace/sidecar/owner identities and active original
  owner scope, captured checkpoint head and exact payload;
- original planned/request budgets and absolute deadline, without refresh;
- original source/configuration, policy, memory and execution-control pin values;
- the original producer root/sidecar proof and retained immutable staging policy
  and history, without doing a cross-connection CAS on the changing episode head.

The fixed projection runs source/configuration hooks outside the short observation
mutex, then rechecks captured state/checkpoint freshness. It grants no launch, ACK,
publication, head advancement or receipt. The ready handler still executes the
complete original gate before any real admission CAS. The worker also retains its
complete before-settlement checks. Waiting does not swallow a conflict, recapture a
head, adopt a new state, retry or fabricate a phase.

## Implementation and verification plan

1. Extract the existing fixed pin projection, retaining the immutable producer
   proof/staging checks separately from mutable admission-reference validation.
2. Leave the existing complete selected assertion available at every authorization
   and terminal boundary. Replace only the pending loop assertion with the wait gate.
3. Add a controlled real-ACK success interleaving that holds the worker before its
   terminal append and releases it during owner fixed-pin observation. Verify zero
   mutable admission CAS calls during that wait and full gates after worker exit.
4. Cover pending source, budget/deadline, selected handoff, state and checkpoint drift,
   failed immutable producer proof, no channel completion/receipt/head advancement,
   and source hooks that require another observation thread.
5. Run focused inert fixtures, adjacent selected service/settlement and owner gates,
   Ruff, compileall and diff checks. Preserve original diagnostic failure evidence.

The parallel pre-wave policy change adds `mode` and `plan` to `_run_fingerprint` at
the selected projection call. Integration must carry those arguments to the extracted
fixed projection rather than restoring the old call signature.
