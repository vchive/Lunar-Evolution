# Local benchmark case smoke (2026-10-20)

This record covers deterministic, local-only checks against read-only copies of
three optimization cases supplied in an external benchmark checkout. The source
checkout was never modified. Copies and raw evaluator output are kept under the
ignored directory `.lunar-evolution/validation/benchmark-reruns-20261020/`.

The original case evaluators were run directly against the copied inputs and
submissions:

| case | submission | validity | overall | objective/cost |
| --- | --- | ---: | ---: | ---: |
| train delay rescheduling | copied schedule | 1.0 | 0.5282 | 141700 |
| city delivery routing | 12-route submission | 1.0 | 0.0379 | cost 21309622 |
| city delivery routing | 9-route negative control | 0.0 | 0.0 | rejected: exactly 12 vehicles required |
| hospital OR scheduling | deterministic greedy schedule | 1.0 | 0.0326087 | cost 28520 |

The Lunar `effect-trial` harness was also run three times on the copied train
delay fixture. All three runs were ready with `validity=1.0`, `overall=0.6827`,
and `objective=109620`. This is provider-free fixture evidence only:
`formal_conclusion_eligibility=ineligible` and
`model_evidence=not_provider_observed`.

These runs validate the copied-case/evaluator path and deterministic harness.
They are not a model campaign, a remote evaluator result, or production RSI
admission; `production_admission` and `online_publication` remain false.

