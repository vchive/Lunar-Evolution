# Observe ready EOF at an expired cleanup boundary

The final local union on source `c27e2c9733a31fbc1e4e91833c33224507186093`
ran 2,150 cases and failed one 5 ms candidate timeout assertion: the returned
status was `failed`, while the test expected `timed_out`. Its retained output
does not identify the actual error code, exit code, or cleanup observations.
The cause of that original invocation is therefore unknown. Do not retry it
or infer that the deterministic scenario below explains the original failure.

The process reader currently treats a nonempty selector map at the cleanup
deadline as failed cleanup before observing already-ready EOF. A scheduling
delay can leave a killed, exited process's ready EOF registered at that point.
Use fake process, selector, clock, and read operations to demonstrate this
path without launching a process or depending on scheduling.

At the existing cleanup deadline, permit exactly one selector batch with
`select(0.0)`. Read each ready registered stream at most once, with the existing
bounded read size, and then leave the loop unconditionally. Only EOF removes
a registration. A still-open registration, missing readiness, data instead of
EOF, `BlockingIOError`, or `InterruptedError` cannot establish clean cleanup.
Do not wait again, reset the deadline, increase the grace period, or treat the
parent's exit as proof that inherited pipes closed.

This last batch observes EOF only. Discard newly read nonempty data without
appending it to captured output, increasing totals, or setting a new overflow
reason. The expired path previously did not read these bytes. Preserve an
already-observed overflow and the existing error precedence. Other read
`OSError` exceptions still propagate through `finally`; never turn them into
a successful result. Keep prior failed kill observations sticky and preserve
tracked process-group confirmation and release requirements.

First retain the deterministic regression's failure against the old product.
After the narrow product change, run the new fake-only cases plus focused
runner/evaluator/ownership tests, Ruff, compileall, and `git diff --check`.
Add the original short-timeout assertion's result tuple to its diagnostics
without changing its 0.005 second budget or expected status. A passing fake
reproducer is local regression evidence and does not close the separate Linux
mixed acceptance gate or prove the original union failure's cause.
