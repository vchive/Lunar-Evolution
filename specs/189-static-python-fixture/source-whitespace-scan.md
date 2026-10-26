# Skip redundant whitespace-line scans for ordinary source

The exact `1e6f10f8` stock original-owner C1 profile passes once in 17.77 s.
Its 72,463 component fingerprints spend 1.111 s inside `_dedent_source`;
that is a nested local measurement, not the cost or cause of the failed
three-child mixed case. All three original CI failures remain recorded.

Extend the existing zero-margin calculation only. For an exact nonempty
string whose first character establishes zero common indentation, a
space/tab-only line can match the original multiline whitespace regex only
if the string contains a space or tab immediately before LF, or ends in a
space or tab. When all three conditions are absent, return the original
string without running the regex. Otherwise retain its original substitution.
The two substring searches run in the string implementation and add no cache.

Keep the original dedent function/code and both regex identity guards before
the shortcut. Indented strings, newline-prefixed strings, subclasses and
changed backends continue through the live standard-library backend. Keep
all source reads, associations, runtime/config hooks, bounds, newline/strip
normalization and final identity computation. Do not change policy scopes,
history reads, budget checks or the 600-second control.

Validate against the installed `textwrap.dedent` over whitespace/end-of-line
boundaries, generated input and repository sources, plus existing cache,
identity, drift and changed-backend tests. Record helper timing separately
from the eventual new-head mixed acceptance; a faster helper does not close
that gate.

## Validation

Before editing the helper, all 35 expanded normalization tests pass against
the original product. The candidate passes the 124-case source/cache/identity
selection with zero failures, errors or skips. That first command emits
historical pytest garbage-cleanup warnings at exit; its output is truncated,
so it is not described as warning-free. The subsequent isolated-basetemp
selection includes the same 124 cases, all 52 C1 policy tests and one stock
original-owner C1 retention/checkpoint test: 177 unique JUnit cases pass,
zero failures/errors/skips, raw rc0, 10.128 s. Its JUnit SHA-256 is
`c6b54f0f4035054dae460389a4a2df2d759495238ca82321abbba550740ea947`.
Whole-repository Ruff, compileall and `git diff --check` pass.

Independent review compares all 177,156 strings of length zero through five
over an 11-character boundary alphabet with the installed `textwrap.dedent`;
all results agree. Backend-change handling remains intact. This complements
the generated-input and repository-source oracle in the tests.

A rotating 21-round pure-helper comparison (50 calls per round) measures
86,970-character `_policy` source at median 356.1 to 151.5 microseconds and
11,008-character budget-class source at 49.5 to 20.1 microseconds. The
indented-method sample changes by less than 1%; two tiny whitespace-containing
fallback samples are 11%–14% slower (about 26–38 nanoseconds per call).
The initial timing command imported an older installed checkout and stopped
before sampling; the recorded comparison explicitly selects and verifies
this worktree's `src`. Timing is only helper evidence, not a mixed or overall
performance result. Materials are under ignored
`release-closeout-20261025/source-whitespace-scan-e9lf_5p8/` and
`independent-source-whitespace-review-72e5zx1y/`.
