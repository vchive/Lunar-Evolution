# Continuation: opt-in fresh subject history and bounded transcript reads

Status: implemented and locally verified, 2026-10-25; base `30b2df2f`.
Final branch CI and merge remain pending.

The ordinary effect-subject path currently keeps only bounded failure counters,
although AgentLoop and staged workflows already support SessionTranscript.
Add an explicit `effect-subject --session-history` switch and matching
`run_subject_adapter(..., session_history=False)` keyword. Defaults, frozen
request fields, prompts, success receipts, model requests, retry behavior and
budget ceilings remain unchanged. This does not recover the old failed smoke.

## Subject history contract

Reuse the existing SessionTranscript and AgentLoop session implementation.
For nonstaged subjects only, opt in before the first model request to a fixed
workspace-confined file: `sessions/subject.jsonl` in normal mode, and
`sessions/subject-<round:03d>.jsonl` in deep mode. No caller-supplied history
path or machine-wide session discovery is accepted. Reject any existing file
at that path, including symlinks and special files, and unsafe ancestors;
atomically create an empty file through the existing confined parent before
AgentLoop can read it. Never replay a prior attempt. The new flag combined with a staged workflow
must fail before a model request and must not alter staged master/build
transcripts. With equal tool results, a fresh empty transcript must yield
identical model messages, tools and deadline calculations to the default path
with a controlled clock. The new files are visible to workspace tools; listing
the workspace can therefore observe the opt-in artifact. No filesystem
invisibility or arbitrary tool-result equivalence is claimed.

Successful assistant/tool exchanges already written before a later failure
remain in the transcript. Existing API-key redaction, truncation, recent-entry
compaction and confined publication apply. Failure sidecars remain score-free
and contain no transcript text. The transcript is a local bounded debugging
artifact, not an immutable audit record, filesystem access proof or sandbox.
Same-UID code can still alter it, and truncation/compaction can omit content.
No new replay/resume authority, evaluator, remote service or production gate
is added. Opt-in transcript storage errors retain existing session failure
semantics; this is not an unconditional guarantee of successful recording.

## Bounded reader contract

Both confined and ordinary SessionTranscript.load currently read the whole
file before slicing its last `2 * max_total_bytes`. Replace this with a bounded
tail read from an opened regular file, using its observed size to seek and an
explicit read size of at most that cap. Appends after size observation must not
cause an unbounded read. Preserve JSONL decoding, malformed/truncated-line
skipping and the latest max_messages entries. Keep existing confinement and
missing-file/error handling, and existing generic history replay semantics.
This defect was not exercised by the old smoke, whose history was disabled.

## Focused verification

Use fake model runtimes only. Compare off/on requests and success receipt
bytes under a controlled clock, assert unchanged default absence of history,
bound deep files to distinct rounds, retain/redact exchanges after a late
failure, refuse old history and unsafe paths before requests, reject staged
combination, and verify the CLI opt-in. For both reader branches, inspect
actual explicit read sizes on an oversized/sparse file and preserve valid
tail JSONL while ignoring a truncated first line. Run related transcript,
subject and staged regressions, ruff, compileall and git diff --check. Save
JUnit, exact commands, return codes and pre-test source hashes in a new ignored
validation directory. This slice does not call a real model/evaluator. The
separate command-capture change is specified in
[bounded-command-capture.md](../064-budget-aware-candidate-preservation/bounded-command-capture.md).

The final local union ran 23 test files: 564 passed, zero failures/errors/skips,
with 2,352 complete registered source files equal before/after. Raw command,
prelaunch source manifest, return code, output and JUnit are retained under
`.lunar-evolution/validation/release-closeout-20261025/subject-tools-union-vzxpq71m/`
in the primary workspace. JUnit SHA-256 is
`402387f2629967cef499d9edd312b445b3f2e7ec727c3eeada3ed279ba99136c`.
The earlier 22 dedicated tests are included in that union, not additional cases.
Independent static review found no blocker. Whole-repository Ruff and
src/tools/tests compileall passed. Later documentation edits do not change the
tested product/test bytes or turn these local tests into final-source CI.
