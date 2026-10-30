# Reserved rejection prefix parsing within one pure operation

The `3799f509` three-child mixed attempt retains a 600-second timeout. Its
time-associated diagnostic workspace reaches the third child's mailbox, but
has no PID-to-fixture attestation or stack establishing a CPU hotspot. This
change must not claim to close that acceptance failure or rerun its selector.

## Contract

`validate_reserved_brs_c1_transition` currently parses the same bounded prefix
twice: once for transition scope, once for the selected rejected entry. C2
parses it a third time for the preceding entry. Each parse decodes and checks
the entire immutable prefix, its canonical form, descriptors and pins.

Parse that prefix once per top-level transition and pass its detached facts
only between private helpers on the current stack. Keep public signatures and
the existing standalone entry and transition-scope behavior. No trusted/context
argument, module/thread cache or new I/O is exposed. Every later top-level call
rechecks the original prefix object and bytes; input mutation between calls
must still refuse. The wire, entry, journal, pin, size and association checks,
their rejection order and their error wrappers retain their current behavior.

This is a pure calculation change. Original SQL/FS observations, policy/source
pins, budget/deadline checks and owner/worker boundaries remain untouched.
Capacity helpers continue to use their existing fresh standalone operations.

## Plan and acceptance

1. Add semantic malformed-input/precedence and between-call mutation tests, and
   run them against the unchanged `3799f509` product module before editing it.
2. Split private entry and transition-scope calculations from prefix parsing;
   share one operation-local parsed result in C1/C2 transitions. Preserve entry
   error translation when the transition invokes the private calculation.
3. Add a call-count oracle requiring one `_prefix` invocation per C1/C2 call;
   separately require the public entry/scope paths to parse independently.
4. Run focused and relevant pure validator/capacity tests, Ruff, compileall and
   `git diff --check`. Compare valid results and exact refusal codes with the
   frozen original module over a bounded synthetic oracle.
5. Measure the same small pure DTO operations before/after without profiling,
   rotating order. Timing is local helper evidence, never a mixed/E2E claim.

An initial six-operation cProfile diagnostic confirms C1=2 and C2=3 prefix
parses for empty, two-child and seven-child historical prefixes. With two
historical children it reports C1 6.68 ms / C2 9.45 ms, with 3.71 / 5.32 ms
inside `_prefix`; seven historical children report 19.20 / 29.09 ms, with
12.78 / 20.49 ms inside `_prefix`. Those single profiled observations are not
performance acceptance thresholds or a prediction for the failed mixed case.

## Local validation

Before editing the product module, all 17 newly added semantic tests passed
against `3799f509`. The candidate's 24 new tests additionally require exactly
one prefix parse per C1/C2 invocation for zero, two and seven historical
children, independent standalone entry/scope parsing, exact malformed-input
precedence and fresh mutation refusal on later calls. These and the original
reserved rejection tests pass together (75 tests). Ruff, targeted compileall
and `git diff --check` pass.

The retained original module SHA-256 is
`3c98d5ec11a9c9bb0aaeefc59da18cae1866a49bde3f483cc7fb2609f53e8eee`;
the candidate is
`17c13627cb63375ab05b6a4ed58d9c9595458dbe3d79864bee4db2e3566c396c`.
A 552-case synthetic differential oracle compares C1, C2 and both standalone
entry variants over six historical-prefix patterns and 23 valid/malformed
variants. Returned values, exception types and exact refusal codes agree;
there are zero intercepted I/O/process calls and the candidate source remains
byte-identical before and after the diagnostic. This is bounded oracle
coverage, not a proof over all inputs.

The same diagnostic alternates original/candidate ordering across 21 rounds
of three unprofiled calls per variant. For two historical children, median
C1 is 3.412 to 2.442 ms (28.43% less), C2 5.083 to 3.099 ms (39.04% less).
For seven historical children, C1 is 10.465 to 6.885 ms (34.21% less), C2
14.880 to 7.445 ms (49.96% less). Empty-prefix C1 is 3.31% slower and C2
6.07% faster in this sample. Related offline tests were running concurrently,
so those numbers are local, potentially contended helper measurements, not
exclusive-machine performance thresholds or a mixed/E2E improvement claim.

Evidence is retained under
`.lunar-evolution/validation/release-closeout-20261025/reserved-rejection-prefix-reuse-kxzhrqdf/`,
including the original module, baseline receipt, diagnostic script and
`pure-operation-comparison.json`. No mixed selector, producer, evaluator or
model was run by the diagnostic. The `3799f509` mixed failure remains open.

The single related offline union finishes with 381 passed / 381 unique JUnit
nodes, zero failures/errors/skips, in 565.05 s (JUnit suite time 562.188 s).
Its nine selected files include pure validators/capacity/policy, local physical
inventory checks, original-owner C1 retention/uncertain-write fixtures and the
original inert checkpoint setup. It does not select the serial mixed driver
test. `related-union-command.json` retains the exact command and file list;
`related-union.xml` SHA-256 is
`095264d8efe3dae354228617656c4e9eff36460aa92c4de7e839d5c58baed668`.

Pytest also reports 27,483 warnings in total. The retained terminal samples
show `_pytest/pathlib.py` `rm_rf` cleanup warnings concerning historical
garbage paths (PermissionError / directory not empty). Its exit code is zero;
this is not a warning-free run. The terminal output was too large for the tool
response and was truncated, so this evidence cannot categorize every warning
or assign them all to test execution versus pytest exit cleanup. Preserve that
limitation and the complete JUnit; no original warning paths were removed or
altered to change the result, and the union was neither cancelled nor retried.
