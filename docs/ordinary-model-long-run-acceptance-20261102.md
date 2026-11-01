# Ordinary-model long-run acceptance — 2026-11-02

Status: running. The single fresh attempt started at 02:13:07 Beijing time
(`2026-11-01T18:13:07.414622+00:00`). No outcome, completed usage or score is
claimed while the subject is active.

## Registered conditions

This is the independently specified [long-run acceptance](../specs/061-subject-failure-diagnostics/ordinary-model-long-run-acceptance.md),
using the same model and unchanged copied train-delay case as the earlier
ordinary smoke. It uses frozen product main
`5c62ca270d78c605ca189399c8b8caadcd11e1b7`, tree
`febb48196250768cb01e66c51b9f499b17e3f0a7`: all 2,808 files and 308 directories.
The product's original 45 CI jobs and independent 28-check artifact review
passed before this preparation. No product source, test or tool changed for
the new measurement.

The fresh profile changes only the timeout and maximum tool steps. Its fixed
allowance is 3,000 subject seconds, 40 individual tool calls and 160,000
observed tokens, one attempt and zero retries. Observed tokens are not a hard
server billing cap. Each model call receives the existing remaining subject
time. The outer watchdog is 3,020 seconds with at most five-second TERM and
KILL waits. A local evaluator may run once with a 30-second execution deadline
and at most five seconds for KILL/reap, only after subject completion and full
original receipt validation. A completed E2E additionally requires an actual
submission, evaluator rc0, finite score fields and `validity_score == 1`.
No minimum quality threshold is introduced.

Only unchanged `instruction.md` and `data/instance.json` are initially projected
to the subject. All eleven copied-case files and the original benchmark remain
unchanged. No WebAgent, remote/company evaluator or native RSI campaign is
included.

## Preparation evidence

The prelaunch registration commit
`0c87fac9b341c736cdfdad3b2b84306bbaf11a3a` was pushed before execution.
The private, create-only manifest is 5,105 bytes with SHA256
`ab471ba658db3aa8771336e1fc04bf727ab3b6543959a30a87aa8ceddde75260`.
Independent static review passed 46 checks; its report SHA256 is
`bf652c2493c9a265a02d6de802ef329425a4f1fa32e0ba1c901f2210136516cb`.
The reviewed bounded supervisor is unchanged from the earlier attempt.

Evidence is retained under the primary workspace:

```text
.lunar-evolution/validation/ordinary-model-acceptance-20261102/
  long-run-5c62ca27-7773cy38/
```

The launcher retains actual UTC boundary observations, bounded redacted
captures, original usage/failure/history evidence, before/after source/case/
profile checks and loaded-module origins. Configuration is loaded privately
only at the actual launch. The new endpoint fingerprint cannot reconstruct
either historical endpoint; no key digest is recorded.

## Interpretation

The two historical 600-second/12-step attempts remain failures. This new
3,000-second/40-step result has its own denominator and cannot repair their
response-header stalls, establish a matched-budget result or imply WebAgent
parity. Until original postrun evidence is audited, ordinary-model E2E remains
open.

This is a trusted local smoke. Source readbacks and origin checks do not prove
immutable consumption, OS confinement, private-evaluator inaccessibility,
server cancellation, complete foreign-process cleanup or billing completeness.
Native RSI runtime, production admission and online publication remain false.
