# CI stage diagnostics: explicit, observational slice

## Problem and boundary

Original PR190/191 attempt 1 current/heavy jobs reached GitHub's six-hour job
limit. Retained check annotations explicitly report the platform timeout; six
terminal job log requests returned `BlobNotFound`. The exact blocked node,
process CPU and underlying cause remain unknown. Historical jobs succeeded.
This slice exposes future progress; it does not claim to fix an unknown stall.

## Contract

`tools/run_tests.py --diagnostics` explicitly opts into diagnostics. Without the
flag, commands, output, receipts and CLI routing retain their existing behavior.
There is no environment-driven opt-in. ContextVar scopes cover one validated
CLI invocation and reset after normal return, failure and nested invocation.
Invalid flags fail before activating diagnostics or dispatching a suite.

An enabled invocation emits `lunar-ci-diagnostic ` followed by a JSON object
with schema `lunar-ci-stage-diagnostic-v1`. Events are flushed to stdout before
collection/pytest starts and after the stage returns or raises. Fields identify
the known suite/role, `collection` or `pytest` phase, start/end, selection or
expected test count, elapsed monotonic seconds, original process exit code when
observed, validation exit code when available, and exception class when raised.
Collection end also reports the collected count. A start without an end means
completion was not observed. An absent process result remains `null`, never a
fabricated successful exit. Environment values, command lines, Python `-c`
code and exception messages are not added to diagnostic events.

Collection stdout stays captured for the unchanged node parser. Diagnostic
pytest changes only verbosity from `-q` to `-v`, exposing the original node
progress. Existing selection, order, full-file shard algorithm, seven fresh
heavy processes, JUnit validation and the sole known historical retry remain
unchanged. Its two original attempts are labelled 1/2 when diagnostics are on.
No test timeout, campaign budget or original 600-second mixed acceptance budget
is changed. No workflow retry or mixed dispatch is introduced.

The workflow enables the flag for current/heavy/history and sets
`PYTHONUNBUFFERED=1` so inherited pytest progress is not delayed by the tee pipe.
These logs are ordinary observations, not immutable execution custody or an
acceptance receipt. The platform can still terminate a job before logs/artifact
upload completes; this slice cannot recover missing old logs or guarantee a
terminal event under process/runner destruction.

## Implementation and validation

Implementation is limited to `tools/run_tests.py`, `.github/workflows/test.yml`
and `tests/test_ci_stage_diagnostics.py`. Focused checks cover default command
compatibility, flush ordering, raw/validation exit distinction, collection
failure/spawn error, generator selections, scoped reset, invalid CLI refusal,
unchanged historical retry and a local inert real pytest run with exact JUnit
case identities. Existing shard/runner seam tests cover selection and retry
compatibility. No mixed/full-suite/remote evaluation is required for this slice.
