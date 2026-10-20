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
| `ore_reclaiming_scheduling` | CP-SAT-assisted deterministic schedule: `validity=1.0`, `overall=0.1277`, objective `261,012` against `best_known=33,335`; all 85 `tS`/`h`/`tR` entries are concrete | the earlier all-zero pad control: `validity=0.0`, `C10 diffn` overlap between piles 0 and 1; the copied prior submission also exposed missing pad positions (`None`) | evaluator path and hard validity gate passed; quality is a smoke baseline, not an optimization claim |

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

Reproduce the positive ore run:

```bash
python .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/case/tests/evaluator.py \
  --submission-dir .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/submission \
  --data-dir .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/case/data
```

The schedule was constructed in a disposable local environment with a temporary
CP-SAT helper; no solver dependency or generated schedule was added to Lunar
production code. To reproduce the negative control, use the ignored
`submission-negative/solution.json` fixture and run:

```bash
python .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/case/tests/evaluator.py \
  --submission-dir .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/submission-negative \
  --data-dir .lunar-evolution/validation/benchmark-cases-20261020/ore_reclaiming_scheduling/case/data
```

The three results are provider-free fixture evidence only; they do not change
`production_admission` or `online_publication` and are not optimization claims.
