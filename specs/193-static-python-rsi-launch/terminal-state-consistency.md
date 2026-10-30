# Original Podman terminal-state consistency

The fresh Shinka build on `01d740f0` completed all 318 commands, but its original
dependency consumer refused the retained report. Independent inspection located
the exact mismatch: freeze command 233 (`encodings.utf_8`) has original state
`Status="stopped"`, `Running=false`, integer `Pid=0`, integer `ExitCode=0`,
`OOMKilled=false`, empty `Error`, an original zero-code wait and reaped attach
client. The other 317 states are `exited`. The runner accepted that terminal
state; the common observation validator required only the `exited` spelling.
The consumer converted its `ValueError` into the fixed
`build_dependency_readback_or_evidence_failure` refusal.

The independently retained raw state is 332 bytes, SHA256
`9f4576697bebfbfd086c4da578f10bd21c0bb7318fe31d098e2326014d9bb951`;
the wait is the original `0\n`. Complete archive/VFS/control checks, original
directory identities and four-tree input FD/hash checks passed. A separate
read-only diagnostic using the original validator reproduced its exact refusal
chain. Original report, failure, deadline and source provenance remain unchanged.

## Corrected common rule

One private predicate is consumed by both the original runner and common
observation validator. A successful terminal state requires an exact dict with
an exact string tag in the finite set `{exited, stopped}`, `Running is False`,
exact integer zero PID and exit code, `OOMKilled is False`, and a missing/null
or exact empty string Error field. Booleans and floats cannot stand in for
integer zero. Active, created, initialized, paused, unknown or malformed tags
remain refused even when their other fields look terminal.

The runner still independently requires its original zero-code Podman wait.
The dependency consumer still requires complete original commands, reaped
attach clients, complete output sets and every original policy, source, VFS,
retention and cross-pin check. No wire version, recipe/default bytes, executor,
callback, retry or budget is added. A `stopped` spelling does not establish
complete namespace or descendant cleanup; all existing false authority claims
remain false. The corrected predicate also refuses malformed state fields
previously accepted accidentally by Python's equality with integer zero.

## Validation boundary

Focused regression covers both terminal spellings through the real runner and
retained/common validator chains, and refusal of nonterminal states, bad waits,
PID/exit/OOM/Error mismatches and malformed scalar types at their actual gates.
The real failed Shinka execution is never relabelled successful. Any corrected
post-build readback is a new, separately labelled observation of the original
retained evidence; it cannot create an original successful dependency receipt or
grant build/runtime acceptance. A new-source CI and independent audit remain
required before merge.

The final `0de18312` source passed all 826 unique cases across 19 complete Linux
files, including all 73 additions, in 9.241618 seconds including the harness.
There were no failures, errors, skips or retries. Collection, execution and
JUnit keys/order matched; all 2770 source files' bytes/Git execution bits were
unchanged, and all 285 recorded import origins belonged to that source inventory.
Ruff, compileall and diff checks passed. Existing groups remain 83/65 zero-skip;
the affected source group is 1167 and the expected group sum is 7983. This batch
does not repeat or add together the earlier 663 native/serial influence cases.
