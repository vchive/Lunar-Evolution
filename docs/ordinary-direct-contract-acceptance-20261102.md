# Ordinary direct-contract acceptance — 2026-11-02

Status: failed; independent original-evidence audit passed 32/32 checks. The
single registered attempt ended after exceeding its observed-token budget.
No completed receipt, evaluator invocation or score was produced.

## Registered scope

This is the independent [public-contract variant](../specs/061-subject-failure-diagnostics/direct-contract-live-acceptance.md),
not a restart or replacement of the failed unchanged-input attempts. All eleven
copied benchmark files remain unchanged. The added 1,311-byte `public-task.md`
publishes the required answer filename, numeric matrix fields, dimensions and
minutes; it contains no answer or private scoring logic. The twelve-file variant
has a new case/publication identity and exactly three public files.

Frozen product main is `32cce01d36f84096bd24c6523e19d80d558e7cf6`,
tree `7c93d1780c10ad4885e99bcc9085b535f91b4655`: 2,817 files and
308 directories. Its software is byte-identical to the already regressed PR211
baseline; only four Markdown status files differ. The original CI
`41376210045` passed all 45 jobs. Each Python 3.11/3.12/3.13 run had
28,019 passes and the same 134 baseline skips, including all 59 additions.
No product source, test, tool or workflow changes for this measurement.

The fixed allowance is 3,000 subject seconds, 40 individual tool calls and
160,000 observed tokens, one attempt and zero retries. The outer subject
watchdog remains 3,020 seconds plus at most five seconds each for TERM/KILL.
The child adds only `--model-request-log`; the reviewed supervisor and bounded
1 MiB-per-stream capture remain unchanged. Logs are saved at termination, not
exposed incrementally by this measurement helper.

Only subject rc0, original completed receipt/profile/request validation and clean
supervisor observations permit one unchanged local evaluator invocation. Its
allowance is 30 seconds plus at most five seconds for KILL/reap. No submission
may be repaired or substituted. Functional completion requires finite validity,
quality and overall fields with validity exactly 1; quality is reported separately.

## Registration and retained evidence

Registration commit `f676de30f6d3451bd707b866e7a8f7ab6acc78b2` was pushed
before dispatch. The sole launch began at
`2026-11-02T04:53:25.964010+00:00` (12:53:25 Beijing time).

The primary workspace retains the original evidence under:

```text
.lunar-evolution/validation/ordinary-direct-contract-20261102/
  direct-run-32cce01d-rj_w42lk/
```

The 6,645-byte one-shot manifest has SHA256
`df0c314b0dfd8f453a40cbd3ba645a0a9426e6c71fd57b9d3c66299ce5eefd82`.
The 8,020-byte independent preparation review passed; its SHA256 is
`2f6fba7208f81b953a55552e8299b02cf2f89e6721fcab6a2460f55ae682234e`.
The root execution gate records `approved_for_single_dispatch`, with SHA256
`64c411aae8b6db47acd5afc05d580cd53b97feb2f7e84d4c9ce8dfe4879b6acb`.
The original profile is hash-bound and handled privately; credentials, endpoint,
model identity, prompt and tool bodies are not exported into this report.

## Actual result

The original launch ended at `2026-11-02T05:16:25.486140+00:00`
(13:16:25 Beijing time). Subject process elapsed time is measured separately
from preparation, launch supervision and post-run evidence collection.

| Observation | Original result |
| --- | --- |
| Subject process | rc2 in 1,195.449322 seconds; original child reaped and pipe EOF verified |
| Outer watchdog | No timeout reason or TERM/KILL attempts |
| Terminal diagnosis | schema2, `stage=runtime`, `code=budget_exceeded`, `limit=max_total_tokens` |
| Accepted usage | Eight rounds: 38,754 input + 61,897 output = 100,651 tokens; cost unknown |
| Observed usage | Nine rounds: 46,719 input + 127,433 output = 174,152 tokens, above 160,000 |
| Trigger response | `trigger_recorded=false`; usage completeness remains partial |
| Retained history | 24 messages: system1/user1/assistant8/tool14, strict pairs, zero pending results or compaction |
| Request progress | Nine complete start/terminal chains, all completed; 38 wait events, no failed request or missing endpoint |
| Completed receipt / selected submission | Neither produced |
| Local evaluator | Correctly skipped as not completed; scores null |
| Evidence integrity | 32/32 independent checks passed; actual acceptance=false |

The ninth response completed at HTTP status 200 after 705.494 seconds. The last
periodic local observation was `wait_response_headers`; a later completed
terminal is present, so this attempt is not a transport-timeout result. The
response raised cumulative observed usage above the stop threshold and was not
accepted into history. This explains why nine completed request logs coexist
with eight assistant records. It does not establish the response's answer
quality or a complete bill. The 160,000-token threshold is checked after usage
is observed; it is not a server-side generation or billing cap.

The independent v4 audit executed once after launcher termination. It verified
the frozen source against Git/archive/modes and before/after inventories, all
2,817 files/308 directories, twelve case files and three public inputs, opaque
profile/request bindings, 240 loaded Lunar origins, UTC/rc/reap/EOF, one attempt
with zero retries, original failure/usage/history/progress, and the exact
pre-evaluator secret-scan scope (nine files, 34,969 bytes). It did not load
configuration, export history text, dispatch a model, run an evaluator or rerun
product tests. Whole-process-group cleanup is not proven by original-child
reaping.

The create-only `independent-direct-contract-terminal-audit-v4.json` is
14,011 bytes, SHA256:

```text
a7d6c78b4b0f3f6500825ef6ea9ba550144eb3d2f91729b3737d501d5adbe6db
```

A second independent reviewer directly cross-checked 49 original evidence pins,
14 manifest assets, the complete source/case inventories and six status
documents. No discrepancy or merge blocker was found. Its create-only
`independent-terminal-crosscheck-v1.json` is 6,947 bytes, SHA256
`709f17b9bb2c2907e71910c5ccd8cc2b368750e92d1adef0f7f3136b6c945088`.
This review did not rerun the audit, model, evaluator or product tests.

Audit preparation versions v1–v3 were never executed and remain retained.
Their corrections address actual gate field names, safe failure projections
and optional best-effort log gaps; no running helper or original result was
changed to fit the audit. Passing evidence checks verify the failed record,
not task completion. No attempt is resumed or retried.

## Interpretation boundary

A completed variant cannot replace the failed unchanged-input result or
establish WebAgent parity. Request logs describe local observations, not server
queue/inference time, cancellation, complete billing or foreign-process cleanup.
No WebAgent, remote/company evaluator or native RSI campaign is included.
Immutable worker consumption and native RSI prerequisites remain open;
`production_admission=false` and `online_publication=false`.

Ordinary-model E2E P0 remains open. This variant establishes that the published
format reaches the ordinary input path, but it did not produce a completed
receipt or score and cannot establish that the format correction is sufficient.
The earlier unchanged-input response-header timeouts retain their independent
failed results and unresolved causes.
