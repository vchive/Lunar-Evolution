# CI test stall stack observations

Status: implemented; affected software cases have passing results across the
preserved original batch and Git-context correction. Complete CI remains open.
Baseline: 90b6d890.

## Observed problem

Original CI runs have six-hour platform cancellations in regression steps after
successful checkout, setup and provenance. A later PR191 job explicitly reports
lost communication with the hosted runner. Original terminal log downloads
returned BlobNotFound; no exact blocked test or underlying cause is established.
Phase/node progress alone cannot explain a Python thread waiting inside a test.

## Contract

Under the existing explicit `--diagnostics` option only, pass the locked pytest
built-in `faulthandler_timeout=300` option to actual test execution. A test taking
five minutes emits its Python thread stacks. Keep the original test process,
selection, ordering, deadlines, retries, exit status and exact JUnit gates. The
watchdog observes; it must not kill a process, retry, extend a budget or turn an
unknown result into a pass. Default invocation stays byte-for-byte equivalent.

The built-in dump contains filenames, function names and line numbers; do not
add locals, live argv/environment, arbitrary process inspections or uploads.
Coverage is setup/call/teardown within pytest's test protocol, not a guarantee for
collection, interpreter shutdown, native child processes, or a disconnected
hosted runner. Emit no claim that this diagnoses or fixes the original failures.

## Validation

Check exact arguments in both modes; raw/JUnit failure separation and historical
retry contract remain intact. Use a single naturally ending inert subprocess to
prove a shortened test-only timer emits a stack while preserving its original
exit code/JUnit inventory; do not run or replay consumed mixed acceptance HEADs.
Run affected runner, diagnostics and aggregation tests together, plus Ruff,
compileall and diff checks. Preserve original CI failures/cancellations.

## Verification — 2026-10-29

Frozen 7ec5399403b2c9a2ad543a8f12df2714e89b3933 contains 2733 source files.
Remote source upload timed out before pytest dispatch. A local working-checkout
preparation also refused before dispatch because it included ignored files.
The unchanged frozen archive was then tested on Darwin: five complete files,
393 unique, 378 pass/1 failure/14 errors/0 skip in 23.174844 seconds. All 15 were
old historical tests whose Git operations could not run in a source tar without
Git metadata. No product/test change followed: only those original 15 were
executed in the proper Git workspace, all passing in 5.880922 seconds. Source
bytes and Git modes remained unchanged. Original failures and preparation
records are retained; this is 393 applicable passing identities, not 408
distinct cases or one complete CI run. The new natural-ending real dump test
passed, including exact JUnit/exit behavior and absence of private values.
Manifest count: 83 groups/65 zero-skip, expected sum 7300. Ruff, compileall and
diff checks pass. Source-loader AST and explicit dynamic-module evidence are
distinguished from the six sys.modules origins in the original batch.
