# Bounded command capture continuation

Status: implemented and locally verified; final branch CI and merge pending.
This does not reopen the frozen model attempt.

## Observed gap and scope

`LocalToolRegistry` used the existing selector-based bounded process runner only
when a process observer was installed. The ordinary subject has no observer and
used `subprocess.run(capture_output=True)` instead. Truncating the returned text
after exit did not bound capture memory during execution. This is a separate gap
from the historical fourth model request timeout; no causal link is established.

Reuse `_bounded_process_bytes` for all command calls. Keep argv/shlex validation,
no-shell execution, configured environment and the original context-local
remaining deadline. Keep observer/release callbacks optional and unchanged.
Capture at most `max_output_bytes` bytes of each stream; crossing that limit is
a failed tool result with `output_limit_exceeded`, even if the process exits zero.
This intentionally replaces the unobserved path's truncate-after-success behavior.
Describe the output limit in the model-visible command schema.

Normal exit/nonzero status and partial stdout/stderr on timeout remain visible.
Nonzero exits now also carry the existing runner's fixed `process_failed` code.
As on the observed path, stdin is closed with `DEVNULL`; invalid UTF-8 output
is replacement-decoded instead of failing the old text-mode decoder. The byte
limit applies to captured streams, not the final rendered result including
replacement characters, labels and errors.
The existing runner starts a private process group, performs bounded kill/drain
cleanup and preserves uncertainty on cleanup failure. This is not a filesystem
sandbox, proof against detached descendants, immutable custody or a new process
ownership authority. No retry, model request, evaluator or receipt is introduced.

## Validation

- Preserve argv diagnostics, model-led correction, token/tool accounting and
  nested/concurrent deadline propagation using the bounded runner boundary.
- Run real local commands without an observer: normal/nonzero and timeout with
  partial output, each-stream overflow, byte rather than character limits, and
  finite return when a child retains the pipe after its parent exits.
- Keep existing observed process tests and candidate runner tests unchanged.
- Run focused tests, Ruff, compileall and diff checks; record actual outcomes
  without treating them as model E2E or static RSI runtime acceptance.

The combined subject/transcript/command/candidate-runner regression passed
564 cases from 23 files, with zero failures/errors/skips; its complete prelaunch
and post-test 2,352-file manifests agree. Evidence is retained at
`.lunar-evolution/validation/release-closeout-20261025/subject-tools-union-vzxpq71m/`
in the primary workspace. The JUnit SHA-256 is
`402387f2629967cef499d9edd312b445b3f2e7ec727c3eeada3ed279ba99136c`.
Independent static code review, whole-repository Ruff and src/tools/tests
compileall passed. This includes eleven real-process/schema cases for the new
unobserved boundary; it is not an inference request or a frozen-runtime test.
