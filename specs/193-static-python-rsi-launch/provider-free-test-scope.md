# Provider-free parser denial scope

The original Python 3.11 current-2 CI run passed the startup-closure parser's
call-phase assertion, then failed inside pytest's verbose call report before
fixture teardown. Its process-wide environment double rejected pytest's
terminal-width lookup. Error formatting then hit that same environment double,
and session-finish JUnit creation hit the process-wide `builtins.open` denial.
The original nonzero result and missing XML remain failures.

Keep the parser's complete filesystem, process, network and environment denial
matrix, but own those process-wide doubles inside `monkeypatch.context()` around
the parser call and its result assertion. Restore every patched API before the
test returns, so reporting and JUnit publication use their original APIs even
when the parser raises or an assertion fails. This changes test instrumentation
lifetime only; the parser, its input and pin bytes, test identity, selection,
budgets, retries and JUnit acceptance remain unchanged.

Validate the complete affected test file using verbose progress and original
JUnit case-key/count checks together with the other pending CI corrections.
Retain source, collection, exit and raw results. A focused pass does not replace
the complete final-head CI or authorize production admission.


## Focused verification

The first complete-file run on frozen
`269761b73cd79a199314b2b508b154c8c0c68e34` passed 67/67 in 0.635797 seconds,
but pyproject's default `-q` counteracted the harness's `-v`. That preserved
result is an ordinary-progress pass, not proof of verbose call reporting.

Only the external harness was corrected: explicitly clear addopts and assert
effective verbosity is one. Frozen
`2d1dcf7cf046e063745052ef36ec8c77ec5f473f` differs only in documents; all 67
cases passed with actual per-node verbose reporting and exact JUnit, zero
failure/error/skip, 0.789859 seconds on Darwin. One dispatch, zero retry; all
2,738 tracked bytes/modes unchanged. Preserve both original results, counting
67 unique identities rather than 134. Product/test instrumentation bytes did
not change between these runs. Original CI failure and missing XML remain
recorded. No parser/product behavior or original assertion changed.
