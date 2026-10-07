# Validation

Validate canonical schema and bounded reads; duplicate/missing/extra/bool pins; byte and metadata
drift; valid rehash extension/shrink; whitespace and same-byte replacement; symlink/hardlink/FIFO;
publication faults and FD closure. Formal native tests cover identical claims before spawn,
gate refusal, original narrowed budget, unknown read-only/explicit cleanup, TERM-to-KILL drift,
post-cleanup/pre-receipt drift, retained replay and v1 compatibility without new authority.

Combine existing attempt/deadline/controller-death, worker verifier, scheduler/RSI and OpenEvolve
local composition regressions. Platform skips must be distinguished from enforcement. No model,
WebAgent, remote/company evaluator, upstream campaign or credential access is part of validation.

Implementation and verification are in progress; earlier PR7 CI does not validate this feature.

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

Final-head complete Ubuntu3.11/3.12/3.13 CI and main merge remain pending at this source commit;
the subsequent PR checks and merge record supply actual status. Earlier PR7 CI is not this
feature's evidence.
