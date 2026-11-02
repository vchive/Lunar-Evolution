# DeepSeek ordinary-model benchmark acceptance

Status: both single attempts executed and failed (2026-11-02).
No completed receipt, submission, evaluator or score.

The user explicitly authorized a DeepSeek run while diagnosing the earlier
transport failures. The configured gateway's same-host authenticated GET models
listing returned `deepseek-chat` with HTTP200; that discovery made no inference
request. Select this advertised identity without editing the owner's .env.

Use frozen source `f3257898b9080b2c6c8bc27c611d281e0d991f2f`, tree
`dfb6188541389f9522d38f03e2828ba9b80466b6`, including the newly focused-tested
[transport categories](transport-error-category.md). The complete CI for this
product change is required before merge and can run alongside these attempts.
Each frozen product has 2,826 files and 308 directories. Final registration
documents are later commits and do not alter this frozen execution source.

Each case is a fresh ordinary attempt: `deepseek-chat`, 3,000 subject seconds,
40 tool calls, 160,000 observed tokens and `max_completion_tokens=16384`.
One attempt per case, zero retries, no fallback/resume or cap changes. Run the
two cases at most concurrently. These limits do not establish remote token
enforcement or a hard billing cap.

Copy the exact previously registered capped public-format cases and evaluator
bytes; retain the 12/3 train and 14/7 hospital case/public-file inventories.
Only the requested model changes in the profile. The existing bounded common
helper stays byte-identical. The child permits exactly the registered model
change, overrides only MODEL in its own environment, and records registered
model identity rather than falsely asserting equality to the previous model.
The launcher changes only the corresponding receipt identity check. Endpoint
and key remain private and unchanged, loaded only during actual launch.

The original supervisor (3,020 seconds, then five seconds each TERM/KILL,
1 MiB per stream), pinned imports, request logs, receipt checks and conditional
local evaluator remain in force. Only original completed receipt validation
and an actual declared submission allow one evaluator call (30 seconds plus
five seconds KILL/reap), without provider credentials. No invented, substituted
or repaired submission. Functional acceptance requires evaluator rc0, finite
scores and validity exactly 1; report quality separately.

The fresh ignored root is primary-workspace
`.lunar-evolution/validation/deepseek-benchmark-cases-20261102/`.

| Case | One-shot manifest SHA256 |
| --- | --- |
| train_delay_rescheduling | `42776da09a20aeddeae138cac967516b510b7c8a9606c1850127a4bd739a4919` |
| hospital_or_scheduling | `8a0f33dc00b7752c42de0f813c7e26acd7824254118c4c6eebab70748b222c62` |

Common helper SHA256 is
`87b7208c3482892fd8735ed18146e9e21d0cafa82a2560e6561e027e8f74a423`;
launcher `9a93798bec888b75d9839538d9c355dc789c0f4e7e0aae3bb42aa01168b08823`;
child `b1908f5b30d259f16913b33dc831ef3c79465d3840b46106742b57a37fdcc380`.
The independent helper review passed 19 checks, report SHA256
`345b4c74c7e43e66a6f236d6c27e0435160e61a8bc756c21c3ecce00e8bec78d`.
The independent exact prepared-byte review passed 48 checks, report SHA256
`77a8e9caeb4329cce0928facbc2fef8da17a6110720e7470fcb26cf998a47f83`.
It checked both manifests, complete source/case/public/evaluator/helper/Python
identities, model-only profile changes, budgets and unused attempt roots.
Push this registration before root authorization and dispatch.

Preserve original terminal events, history/usage/failure/receipt, process and
before/after evidence. Independently review results without rerunning inference
or scoring. Keep every historical failure; a new model result does not establish
same-model benchmark parity, general reliability or evolution benefit.
No WebAgent, remote evaluator or native RSI campaign. This is trusted local
validation; no OS isolation or private-evaluator-inaccessibility claim.
`production_admission=false` and `online_publication=false` stay unchanged.

## Tasks

- [x] Define the model, cases, budgets, acceptance gates and fresh identities.
- [x] Prepare source archive, copied cases, profiles and one-shot helpers.
- [x] Independently review exact preparations, push registration and launch once.
- [x] Preserve and independently review actual results and conditional scores.
- [x] Publish actual outcomes; software complete CI/main integration is separate.

## Actual execution

Registration `24098669f4430ed5af84b8d34623e058d3ece6f4` was pushed before
both launches at `2026-11-02T13:00:37.966Z`. Train ended rc2 after
415.635339833796 seconds: 19 HTTP200 requests, 18 accepted rounds/21 tools,
144,050 accepted partial tokens; the next 16,521 brought observed usage to
160,571, exceeding 160,000. Schema2 runtime/budget_exceeded preserves the
triggering round as unaccepted. Hospital ended rc2 in 109.0237058326602
seconds: 17 accepted rounds/24 tools and 114,715 partial tokens; request18
returned HTTP200 but failed tool-call validation in 6,415ms (schema7
invalid_tool_calls). Its precise parser branch and triggering usage were
not retained. No transport failure occurred; no evaluator was invoked.

The 47-check independent original-terminal review passed, SHA256
`caf6001b5eea78aa2880dc1c81162b2eba40788681366e69bd1c5702f8c8f72b`.
All source/case/profile/import/process/old-evidence checks passed; this
validates failed records, not functional E2E. See the
[actual result record](../../docs/deepseek-benchmark-case-acceptance-20261102.md).
