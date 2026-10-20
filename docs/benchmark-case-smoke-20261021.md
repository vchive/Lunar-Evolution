# Irregular packing benchmark smoke (2026-10-21)

This record covers one additional deterministic, local-only benchmark case copied
from the external read-only benchmark checkout. The source checkout was not
modified. The copied case and submissions live under the ignored
`.lunar-evolution/validation/benchmark-cases-20261020/irregular_packing/`
directory; raw rerun output is under
`.lunar-evolution/validation/benchmark-reruns-20261021/irregular_packing/`.

The evaluator is the copied case's `tests/evaluator.py`. It uses Shapely for
polygon intersection; the local run used the ignored dependency cache at
`.lunar-evolution/validation/.bench-deps/`. No model SDK, WebAgent, remote
evaluator, company evaluation service, or network call was used while
producing the submission or running the evaluator.

| run | validity | overall | objective/metric | boundary |
| --- | ---: | ---: | ---: | --- |
| deterministic 17-column grid (200 puzzles, 20,100 rows) | 1.0 | 0.0590 | `total_score=1166.3931` (`best_known=68.7812351193`) | valid |
| duplicate placement in puzzle `002` | 0.0 | 0.0000 | n/a | rejected: `Overlap: 002_0 & 002_1` |

The valid submission uses a conservative 1.2-unit grid and zero rotation. It is
an evaluator-path smoke fixture, not an optimization claim: the quality ratio
is low because the simple grid is much larger than the reference. The negative
run confirms that polygon overlap is a hard validity gate.

Reproduce from the Lunar repository root:

```bash
PYTHONPATH=.lunar-evolution/validation/.bench-deps \
python .lunar-evolution/validation/benchmark-cases-20261020/irregular_packing/case/tests/evaluator.py \
  --data-dir .lunar-evolution/validation/benchmark-cases-20261020/irregular_packing/case/data \
  --submission-dir .lunar-evolution/validation/benchmark-cases-20261020/irregular_packing/submission
```

The source and copied `instance_01.json` have identical SHA-256
`484b5a6b61cb3b6d88df6829cdb5d0ffadb7a200d2ce79fdc7c20de40c9b6561`.
These results remain provider-free fixture evidence and do not change
`production_admission` or `online_publication`.
