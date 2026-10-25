# Zero-margin source normalization

PR188's original `30b2df2f` CI failed the three-child mixed serial case on
Python 3.11, 3.12 and 3.13 under the unchanged 600-second control. Preserve
those failures; do not rerun that source or enlarge the control. The previous
single-thread diagnostic identifies repeated `textwrap.dedent` work as one
local cost, without establishing its end-to-end share.

For an exact string whose first character is neither space, tab nor newline,
the first line already establishes an empty common indentation. The ordinary
`textwrap.dedent` algorithm cannot remove an indentation prefix in this case.
It must still remove space/tab-only lines. A fast path may perform that same
whitespace-only-line substitution and omit collecting all indentation runs.
Empty strings, indented or newline-prefixed strings and string subclasses use
the original backend. Changed dedent functions/code or either regex backend
also use the current backend, so a backend change is not silently bypassed.

This is a fresh pure calculation on every call, with no new cache. Keep both
complete source reads, source association/backend/code checks, extraction LRU
and byte bounds, newline/strip normalization, live config/default/capture/code
hooks, code-size enforcement and final identity SHA computations. This
continuation does not permit caching normalization or identities.

Acceptance requires an independent standard-library oracle over edge cases
and representative source, backend replacement tests, existing drift/cache
refusals, whole-policy projection and observation-count comparison, focused
tests and static checks. Local primitive timing is not a mixed-case result.
Only a new exact source may receive its own original-budget Linux acceptance
and full CI; none of these checks imply runtime or production admission.

The subsequent exact `c5366cee` independent Linux mixed run did not pass: its
outer runner terminated the test at 600.034 seconds (raw return code -15),
before JUnit or final runtime-origin reporting. Pre/post archive members agree.
This does not locate the internal controller phase. Preserve the failure;
the helper comparisons above do not close this gate, and this source must not
be rerun or given a larger budget to obtain a pass.
