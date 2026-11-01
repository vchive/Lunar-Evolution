# Ordinary-model acceptance — 2026-11-01

The fresh train-delay attempt **failed**. Eight model turns and eleven tool
results completed, then the ninth model request exhausted the remaining subject
deadline while waiting for response headers. No submission or completed subject
receipt was produced. Ordinary-model E2E remains an open P0.

## Frozen execution and result

The attempt used a complete source snapshot of main
`e19be0d12365c34b514e8346f82cb84a208df475`, tree
`a8c35bedbe9f5766d30efcb8278c3e41e059c635`, and the existing eleven-file
copied train-delay case. Only unchanged `instruction.md` and
`data/instance.json` were projected into the subject workspace. The original
benchmark was untouched. Configuration was loaded privately at launch; the
configured model matched the original failed attempt's model.

The predeclared limits were unchanged: one fresh attempt, zero retries,
600 subject seconds, 12 steps and 160,000 observed tokens. The outer watchdog
was 620 seconds plus five-second TERM/KILL bounds. A local evaluator would have
had 30 seconds, conditional on successful subject completion and validation by
the original `EffectTrialRunner._subject_receipt` implementation.

| Observation | Actual result |
| --- | --- |
| Subject child (parent observation) | rc2, 601.363881 seconds, reaped, pipe EOF verified |
| Outer watchdog | Not triggered; no TERM/KILL attempted |
| Failure diagnostic | schema6, `stage=model`, `code=timeout`, `reason=transport_timeout` |
| Failed request | ninth request; `open_response` 352,518ms against 352,513ms remaining timeout; `wait_response_headers`, no HTTP status |
| Completed interaction | 8 model turns, 11 tool results |
| Accepted partial usage | 21,488 input + 13,139 output = 34,627 tokens across 8 rounds; cost unknown |
| Submission / completed receipt | Neither produced |
| Local evaluator | Not invoked: `evaluation_skipped_not_completed` |
| Source and copied case | Complete before/after inventories match |
| Credential scan | 7 attempt files / 22,410 bytes checked, no configured endpoint/key match |

The retained history has nonempty function names, unique nonempty IDs within
each assistant batch and eleven correctly paired tool results, with no pending
tool call. This excludes those observed transcript defects in this attempt;
it does not explain the provider's missing response headers. The failed
request's consumption and any server-side cancellation remain unknown. The
partial subtotal is neither completed usage nor a billing total.

## Review and evidence

Before inference, independent static review verified the frozen launcher and
all 2,803 source files, 308 directories and eleven copied-case files. Four
short offline checks passed in one invocation: isolated child refusal, normal
exit, output limit termination and a terminal child with a held pipe. They did
not load model configuration or run product tests, inference or an evaluator.

Original private evidence is retained under the primary workspace:

```text
.lunar-evolution/validation/ordinary-model-acceptance-20261101/
  draft-v2-e19be0d1-e51wkcvl/
```

The exact v5 manifest SHA256 is
`a8b9292b56f980828e995bd0af1a9d2bdb853f952dcc527a5413360378d3cf6e`.
It binds the one-shot scripts, complete source archive, inputs, interpreter,
prior model profile and fixed limits. Superseded unexecuted drafts, the
authorization, process facts, original history/failure sidecar, inventories
and result remain separate. Raw process streams were not retained; explicitly
redacted copies are labeled. Receipts and history were not rewritten.

Independent original-result audit v2 passed all 36 consistency checks,
including the complete source/case inventories and 239 actual loaded module
origins. Its SHA256 is
`325359a36fb0377208cf40ca9e13769142a817b27e473cef270478edba9f4399`
(`independent-original-result-audit-v2.json`, 7,955 bytes). This accepts the
failure evidence, not the case. The first audit incorrectly hashed raw profile
JSON instead of the existing normalized profile contract; that failed audit
was retained and corrected separately without rerunning the attempt or
changing its original evidence.

This is an ordinary trusted local smoke, without an OS filesystem sandbox or
immutable input custody. Module-origin checks do not establish immutable
consumption, and the initial public projection does not prove private evaluator
inaccessibility. No WebAgent, remote/company evaluator, native RSI campaign or
model substitution ran. Runtime/admission/publication authority remains false.

## Remaining P0

Investigate the response-header stall using the retained request phase and
history plus provider-side request/service evidence if available. No local
code defect or causal repair has been established. Do not hide this failure
with synthetic scores, retries, a different model or a larger budget. Any
further real attempt needs a separately specified fresh investigation.

The [2026-10-25 failure](normal-model-smoke-20261025.md) and its separate
missing-output diagnostic evaluation remain unchanged. This attempt made
more progress and preserved partial usage, but still did not complete E2E.
