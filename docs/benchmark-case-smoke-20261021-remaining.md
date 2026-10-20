# Remaining benchmark case smoke (2026-10-21)

This record covers the three remaining benchmark cases copied from the external
read-only checkout. The source checkout at
`/Users/liminghan/Documents/fm/codesets/baidu/acg-fm/famou-bench/` was not
modified; its `git status --short` was empty after the run. All copied inputs,
submissions, and raw output are under the ignored
`.lunar-evolution/validation/benchmark-cases-20261020/` and
`.lunar-evolution/validation/benchmark-reruns-20261021/` directories.

No model SDK, WebAgent, remote evaluator, company evaluation service, or remote
campaign was used. These are direct local invocations of each copied case's
original evaluator.

| case | positive smoke | negative control | result |
| --- | --- | --- | --- |
| `steel_coil_cutting` | 27-cut deterministic CSV: `validity=1.0`, `overall=0.971555`, `combined_score=1.6158`, `spec_satisfied=51/51`, waste rate `0.0341` | one-row submission: `validity=0.0`; missing 50 specifications, first reported shortages include 965/955/930 mm | evaluator path and hard validity gate passed |
| `supply_chain_inventory` | all 409 service times set to zero: `validity=1.0`, objective `5,057,732.27`, `overall=0.2254` against `best_known=1,140,000` | one negative service time: `validity=0.0`, rejected with `Negative service time for stage 'Manuf_0142': -1` | evaluator path and hard validity gate passed |
| `ore_reclaiming_scheduling` | no positive submission was claimed. The copied prior submission had missing pad positions (`None`) and was rejected with a `TypeError`; a deterministic all-zero pad control was also run | all-zero pad control: `validity=0.0`, `C10 diffn` overlap between piles 0 and 1 | remaining scheduling fixture needs a feasible pad/time construction before a positive claim |

Reproduce the positive steel run:

```bash
python .lunar-evolution/validation/benchmark-cases-20261020/steel_coil_cutting/case/tests/evaluator.py \
  --data-dir .lunar-evolution/validation/benchmark-cases-20261020/steel_coil_cutting/case/data \
  --baseline-dir .lunar-evolution/validation/benchmark-cases-20261020/steel_coil_cutting/case/tests/baseline \
  --submission-dir .lunar-evolution/validation/benchmark-cases-20261020/steel_coil_cutting/submission
```

Reproduce the positive supply-chain run:

```bash
python .lunar-evolution/validation/benchmark-cases-20261020/supply_chain_inventory/case/tests/evaluator.py \
  --submission-dir .lunar-evolution/validation/benchmark-cases-20261020/supply_chain_inventory/submission \
  --data-dir .lunar-evolution/validation/benchmark-cases-20261020/supply_chain_inventory/case/data
```

Reproduce the ore negative control:

```bash
python .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/case/tests/evaluator.py \
  --submission-dir .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/submission \
  --data-dir .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/case/data
```

The steel and supply-chain results are provider-free fixture evidence only; they
do not change `production_admission` or `online_publication`. The ore result is
recorded as an explicit unresolved fixture gap rather than an optimization
claim.
