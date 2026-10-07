# Validation

Validate canonical schema and bounded reads; duplicate/missing/extra/bool pins; byte and metadata
drift; valid rehash extension/shrink; whitespace and same-byte replacement; symlink/hardlink/FIFO;
publication faults and FD closure. Formal native tests cover identical claims before spawn,
gate refusal, original narrowed budget, unknown read-only/explicit cleanup, TERM-to-KILL drift,
post-cleanup/pre-receipt drift, retained replay and v1 compatibility without new authority.

Combine existing attempt/deadline/controller-death, worker verifier, scheduler/RSI and OpenEvolve
local composition regressions. Platform skips must be distinguished from enforcement. No model,
WebAgent, remote/company evaluator, upstream campaign or credential access is part of validation.

Feature173 is merged; its own final-head CI evidence is recorded below. Earlier PR7 CI does
not validate this feature.

Local installed Python3.11: final deadline/helper/claim/registration/worker suite358 passed,
0 skips/failures/errors, no cleanup warnings (`/tmp/lunar-deadline-anchor-final-v5-oct8.xml`).
Final native attempt/worker/deadline/scheduler/controller-death/broker/RSI/OpenEvolve composition
suite328 passed,0 skips/failures/errors (`/tmp/lunar-deadline-native-final-oct8.xml`), following
owner-tail and postspawn/postgate corrections. The last trailing boot-observation check was added
after that process imported the module; its final full anchor30 suite and combined358 suite
passed on the final source (`/tmp/lunar-deadline-anchor-final-v4-oct8.xml`). Helper127 and
protocol/handoff/runtime177 also passed; suite counts overlap and must not be summed.

Independent review found and corrected owner-observation and boot-observation drift windows.
Fault tests retain accurate gate/TERM side effects, block later signals and prevent trusted
recovery publication. Ruff `src tests tools`, compileall and diff checks passed. No C protocol
change, model, campaign or remote evaluator was used. CI now retains `deadline-anchor.xml`
independently, alongside the existing phases and original immutable archive retry policy.

PR #8 final head `f870cb95c10825e49129e50629731adb3a773595` passed complete Ubuntu
Python3.11/3.12/3.13 CI run `37669528518`. Each version's independently audited original XML
contains deadline358/1skip, runtime240/1skip, adapters173, native403/6skips, current10317/31skips,
archived2294 and frozen24; all0failure/error, all first attempt, no archive/current retries.
Merged at `d3f4fbf0ae531d3299ae6736382867d60fee1cc4`; main tree equals the tested head tree.
Post-merge main CI `37675779160` is a separate in-progress run at this update. This evidence
does not validate subsequent Feature174 or establish actual project/campaign acceptance.
