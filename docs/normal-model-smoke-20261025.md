# Ordinary model/local evaluator smoke (2026-10-25)

The single ordinary model attempt **failed**. After three completed model turns
and four completed tool results, the fourth model request timed out waiting for
response headers; no completed subject receipt or `schedule.json` was produced.
This does not establish model solve quality, completed end-to-end
acceptance, static RSI runtime support or production admission.

## Frozen attempt and observed result

The tested product source was main
`0bff6b92b9b05f7b780bf4c2ee6f38bdab4b3833`, tree
`0b65a7b283a8b2f30ff25308e24b4131e34d920d`. It used the existing
`effect-subject` CLI and the configured OpenAI-compatible model, loaded privately
from the owner's existing `.env`. Credentials and endpoint were not put in argv
or this report. No WebAgent, remote evaluator or company evaluation service ran.

The input was the existing copied train-delay case. Only the unchanged public
`instruction.md` and `data/instance.json` were projected into the attempt:

| Public input | Bytes | SHA-256 |
| --- | ---: | --- |
| `instruction.md` | 826 | `def6dcc6b5a144653a7fdd9786f535b4f35f11a2b5ca26dab609d9c52db17520` |
| `data/instance.json` | 993 | `1e1bb1bcc902228866eb2f646dc076ba1ed7fc4bc94a14ede3f0e9abc1e4a4a8` |

Before launch, the local manifest fixed one attempt, no retry, a600-second
subject deadline,12 tool steps and a160,000 observed-token stop threshold.
The token threshold depends on returned provider usage; it is not a hard server
generation or billing cap. The outer watchdog was620 seconds plus bounded
termination, and the separate local evaluator had30 seconds. No budget was
changed after launch. This is separate from earlier registered campaigns and
the deterministic fixture trials; none of their attempts was reopened.

| Observation | Result |
| --- | --- |
| Subject process | rc2 after600.245336833 seconds; internal deadline, no outer watchdog timeout |
| Failure | schema5 `stage=model`, `code=timeout`, `reason=transport_timeout` |
| Recorded progress | 3 completed model turns,4 tool results; fourth request failed; no complete usage/subject receipt |
| Last request | `phase=open_response`,593,719ms elapsed,593,715ms request timeout |
| Last transport milestone | `wait_response_headers`; HTTP status absent |
| Submission | Missing; no fixed-script or repaired answer was substituted |
| Independent local evaluator | rc0, but validity/quality/overall all0; fatal missing `schedule.json` |

The two predeclared output locations were `schedule.json`, then
`output/schedule.json`; the first existing regular file would be selected
without score-based selection. Neither existed. Evaluating the missing result
does not turn the failed subject into a completed solve. Provider consumption
after the interrupted request remains unknown; no server cancellation or
absence of billing is asserted.

## Evidence and interpretation limits

Original ignored evidence is under the primary workspace at
`.lunar-evolution/validation/normal-model-main-1tz1g0us/`. It retains the
prelaunch manifest/profile/request, one-shot marker, before/after inventories,
failure diagnostic, redacted process output, local evaluator output and result.
The independent review is in
`.lunar-evolution/validation/feature189-20261025/ordinary-model-independent-audit-59tkt3v2/independent-audit.md`,
SHA-256 `db8d23b773f4752f84d8558ba01e06a6168118bd0e324e5eca241b205fc73623`.

All1,008 registered product/code files and11 copied-case files had equal
before/after bytes, sizes and modes. The218 loaded Lunar modules had origins
in the selected checkout and source-file SHA-256 matching that inventory.
This is an ordinary trusted local smoke: `-I/-S/-B` plus source-origin checks
do not prove immutable source consumption or prevent reading existing bytecode.
The command tool was enabled without an OS filesystem sandbox, and a full tool
argument transcript was not retained. Therefore access to paths outside the
workspace was not independently verified; the initial public projection alone
does not prove the private evaluator was inaccessible.

No baseline improvement or WebAgent comparison is reported. Earlier fixture
scores stay fixture evidence. The next model investigation must preserve this
failure and determine service/request behavior before registering further
acceptance work. `production_admission=false`, `online_publication=false`.

## Follow-up diagnosis and accounting fix

`model_turns=3` counts successfully parsed and accepted responses; the next,
fourth request failed. With the configured token ceiling, those first three
responses necessarily had valid usage in the in-memory ledger. The old failure
sidecar did not persist that subtotal, so its exact value is no longer available
from the retained evidence. No subtotal is reconstructed or added to that run.

The successor implementation retains accepted snapshots in bounded v6 failure
diagnostics, labeled partial; the failed request's consumption stays unknown and
missing prices remain null. Normal/deep collectors do not promote the subtotal
to completed usage, a success receipt or a score. See the
[continuation contract](../specs/061-subject-failure-diagnostics/accepted-usage-continuation.md).
Its local regressions do not change this failed model attempt's status.

A separate read-only inspection of the user-provided gateway's public `/docs/`
page and its script confirmed the documented Chat Completions fields used here:
model, messages, optional tools and non-streaming requests. It sent no inference
or credential-bearing request. This supports basic request-shape compatibility;
it does not establish why the historical request failed to return headers.

For a separately registered fresh subject, `effect-subject --session-history`
now retains the existing bounded, API-key-redacted conversation and tool records
at `sessions/subject.jsonl` (deep mode: `sessions/subject-<round:03d>.jsonl`).
The default remains off. Existing files and staged-workflow combinations are
refused before model calls; this option does not replay a previous attempt.
Records may be truncated, compacted or modified by same-UID code; they are
debugging material, not an immutable access audit. Transcript loads now read
only a bounded tail even if the underlying file is oversized or grows.

The ordinary command tool also now uses the existing bounded process reader
without requiring an observer. Exceeding either output-stream limit returns a
failed tool result instead of buffering all output before truncating it. These
changes passed 564 combined local tests and independent static review. They do
not identify the old timeout's cause, restore its missing transcript/usage or
complete a model E2E acceptance. No additional model attempt was made in that
implementation slice.

## Independent synthetic protocol diagnostic (2026-10-26)

A separately registered diagnostic used the exact `3799f509` archive. It made
two model calls with a 30-second limit each, a 75-second outer limit, zero
retries and zero tool executions. A sent a short message without tools; after
its success, B sent a fixed assistant batch with two distinct tool IDs and the
corresponding synthetic `list_dir` / `read_file` results plus the ordinary tool
schemas. It did not run AgentLoop, the original benchmark or an evaluator.

Both calls returned HTTP 200, passed the real runtime parser and matched their
expected short marker. A took 13.200 seconds and B 2.132 seconds; the launcher
returned rc0 in 16.410 seconds. Reported and runtime-accepted usage agreed:

| Request | Input tokens | Output tokens | Total | Consumption unknown |
| --- | ---: | ---: | ---: | --- |
| A | 17 | 83 | 100 | false |
| B | 801 | 35 | 836 | false |
| Combined | 818 | 118 | 936 | false |

The actual request-body sizes/SHA, source inventories, 217 loaded origins,
one-time claim and registration snapshot were checked. All 2,362 archived source
files had matching bytes/modes before and after. Configuration values, endpoint,
keys and headers are absent from the retained diagnostic projections.
Evidence is retained in the primary workspace's ignored
`.lunar-evolution/validation/release-closeout-20261025/model-g0-synthetic-3799-registration-7ehduf4o/`;
its single-invocation audit SHA256 is
`9dd1d5bddf978655ae5cbd79c4595e1437a9fc3a245c3612e10f4e15e7c19d77`.

This establishes that this small two-tool history is currently accepted by the
service and runtime. It does not reconstruct the old conversation, diagnose its
fourth-request timeout or turn the original case into a passing E2E result.
The transport child reopens pinned source paths; pre/post hashes do not prove
immutable consumed bytes. No further model request is part of this diagnostic.
