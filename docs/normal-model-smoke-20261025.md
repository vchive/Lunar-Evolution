# Ordinary model/local evaluator smoke (2026-10-25)

The single ordinary model attempt **failed**. The third model turn timed out
waiting for response headers; no completed subject receipt or `schedule.json`
was produced. This does not establish model solve quality, completed end-to-end
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
| Recorded progress | 3 model turns,4 tool steps; no complete usage/subject receipt |
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
