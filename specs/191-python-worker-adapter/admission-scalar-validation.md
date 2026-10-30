# Fresh scalar admission validation

The exact `c5366cee` independent Linux mixed run was terminated by its outer
600-second driver. It produced no passing verdict or internal timeout stack.
Keep that failure and the original budget. A pure history observation identifies
scalar shape recursion as avoidable local work; it does not identify the full
mixed-case bottleneck.

Within `validate_rsi_python_admission_shapes`, validate exact scalar children
in the current container loop. Every child still receives its original depth
check before type or finiteness checks. Reject all children beyond depth 48,
including scalar and empty-container children. Empty containers at depth 48
remain valid. Keep exact `type(...) is ...` comparisons, rejecting subclasses
without invoking foreign metaclass hash/equality or collection callbacks.
Each exact float still calls the current `math.isfinite` at the original point.

Non-scalar children retain recursive validation. Dictionary keys are checked
before values, and approved DTO fields remain a lazy, ordered `getattr`
generator: do not prefetch later fields or change the first observed error.
Do not add a visited set, flattened stack, cached validation or new allowlist.
Repeated objects are validated at every occurrence; cycles still fail at the
depth boundary. Internal `_depth` is an integer recursion counter.

Keep fresh SQLite row reads and parsing, complete canonicalization and byte
limits, parent-chain and admission-reference validation, full source/code
checks, current hooks and identity computations. No budget, request, public
wire format or production authority changes.

Acceptance includes an independent copy of the prior recursive validator as
oracle over accepted/rejected nested values, depth 48/49, cycles, subclasses,
foreign metaclasses and lazy DTO/finiteness callback ordering. Compare complete
history results and fresh SQL/parse/canonical/digest counts on a diagnostic
copy, then run admission/history focused tests, Ruff, compileall and diff-check.
Only a new exact source can receive its own original-budget Linux mixed run;
full CI and independent review are still required before merging.

The pre-implementation pure candidate matched 1,082 oracle shape/depth cases
and callback-order checks. Nine alternating local history measurements showed
median 10.7753 ms to 10.3187 ms (4.24%); complete projections and fresh boundary
counts matched. This is a local measurement, not end-to-end acceptance.

A subsequent comparison on the newly captured diagnostic 26-row ledger did
not show a measurable gain (8.550 ms baseline, 8.581 ms candidate); the older
30-row ledger showed 11.739 ms to 10.763 ms. Preserve that variation rather
than claiming a reliable mixed-case improvement. Full policy observations
cost about 66.6 ms, but warm observations inside the existing scope cost
0.111 ms and do not invoke freeze/fingerprints or file I/O. No matcher or
additional policy cache is justified by these measurements.
