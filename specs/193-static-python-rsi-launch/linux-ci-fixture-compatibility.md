# Linux CI native fault-fixture include compatibility

## Observed failure

Run `40909497309`, head `fec732ce`, reports eight failures in
`tests/test_native_descendants_drain.py` on Python 3.11, 3.12 and 3.13. The
original Python 3.11 artifact contains 4372 exact JUnit cases: 4334 pass,
8 failure, 0 error and 30 skip. The original failures and artifacts remain
retained; this change does not relabel them as passing.

Each failure occurs while strictly compiling the local fault-bootstrap fixture,
before its supervision scenario executes. The fixture includes the real
`native_producer_isolation.h` before its syscall-interception macros. That
helper first includes Linux filter/seccomp UAPI headers inside a function body.
Their header guards then prevent the later global resource-helper include from
declaring `struct sock_filter`, `struct sock_fprog` and `struct seccomp_data`
at file scope. Clang consequently reports incomplete types in
`native_whole_scope_successor_resources.h`.

## Minimal correction

Include the real resource-helper header before the isolation-helper header in
the fixture prelude, matching the existing order in `native_bootstrap.c`.
Both helpers remain before the fixture's syscall-interception macros. Preserve
the actual helper bodies, all fault scenarios and assertions, compiler selection,
static compilation and `-Wall -Wextra -Werror` requirements. Do not alter the
production seccomp policy, native resource gate or compiler acceptance rules.

## Verification boundary

Use one consolidated Linux regression for the affected fixture and original
supervision scenarios after the coherent fixes are frozen. Also run Ruff,
compileall and diff checks. No retry, skip, warning suppression or weakened
assertion substitutes for a successful strict compile and scenario result.
The original Python 3.11 artifact and summary establish the reported counts;
the separately retained Python 3.12/3.13 summaries and JUnit report the same
counts and eight failing nodes. This fixture correction does not establish
static Python runtime or installation acceptance.


## Coherent focused verification

Frozen tree `28f7164b2ea5a5af061ca2f0b07cdcb7b4e5128d`, 2,741 tracked files:
ten complete affected files on Linux/Python3.12.3 passed408 cases with zero
failure/error and one Darwin-only skip, 409unique collected, 39.026092 seconds,
one dispatch and zero retry. Complete ancestry files on Darwin/Python3.11.15
and3.13.12 independently passed the same37 cases without skips, in1.076127 and
1.010370 seconds. Do not add repeated identities across versions. Source bytes
and modes stayed unchanged; exact collection/JUnit and module origins are
retained. Ruff, compileall and diff checks pass. Original unsuccessful CI
results remain unsuccessful; new complete CI is still needed before main.
