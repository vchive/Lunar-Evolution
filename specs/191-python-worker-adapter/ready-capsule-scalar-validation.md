# Fresh scalar ready-capsule validation

The exact `1e6f10f8` whole-case diagnostic completes with raw return code zero
in 554.7 seconds. Its ready-capsule `_shape` walk has 103,917,180 total calls
and 87,089 primitive calls, with 30.246 self / 40.084 cumulative seconds.
This identifies a local hotspot, not passing CI for a new source revision.

Validate exact scalar children inside their current container walk, avoiding a
recursive Python call for each leaf. Dictionary keys remain checked for exact
string type before visiting any item. Then visit each key before its value;
lists retain their original order and live iteration. Each scalar occurrence
still consumes one shared node and receives its original depth check before
length, integer size or current `math.isfinite` validation. Containers retain
recursive validation and their own node/depth checks.

Preserve depth 48, 100,000 nodes, 10,000 entries per container, 128 Ki characters
per string and 4,096 bits per integer. Empty containers at depth 48 remain valid;
all children at depth 49 fail. Do not cache, skip repeated objects, flatten the
whole graph or call foreign subclasses/metaclass hooks. Preserve fixed errors,
counter consumption, first refusal and live finiteness-hook ordering. No file
reads, evidence pins, canonical bounds, accounting or control gates change.

First run new semantic cases against the original product. Compare an independent
copy of the old recursive validator over scalar/container/depth/node boundaries,
cycles, hostile types, live hooks and multiple faults. Then run those cases and
existing capsule/consumer/staging regressions against the candidate, with Ruff,
compileall and diff-check. Independently compare full occurrence/finiteness
counts and bounded local primitive timing; do not add timing assertions to tests
or interpret them as mixed-case acceptance.

## Local verification

The final 77 new cases pass against the original product in an independent
process. The candidate and existing capsule/consumer/staging selection pass
162 unique cases with zero failures/errors/skips and raw return code zero.
An independent review compares actual HEAD and candidate function ASTs over
5,531 small cases, including live list/dict mutations and exception ordering;
all outcomes, remaining counters and finiteness events agree. Ruff, compileall
and whitespace checks pass.

An independent pure-memory occurrence comparison retains 2,885 visited nodes
and 16 live finiteness calls, while recursive entries fall from 2,885 to 354.
Nine alternating timing groups of 60 calls record medians of 374.23 and
348.69 microseconds, a local 6.82% saving. These are primitive measurements,
not mixed-case acceptance or an end-to-end speed estimate.

Ignored primary-workspace evidence under `release-closeout-20261025/`:

- `capsule-scalar-complete-baseline-jv9gty3i/`;
- `capsule-scalar-complete-focused-tq222t_9/`;
- `capsule-scalar-primitive-comparison-i6n5700n/`;
- `ready-capsule-scalar-independent-wyg8dkzr/review.json`.

The integrated source's own Linux mixed and final CI gates remain open.

Local validation: the first 70 semantic cases pass against the unchanged product
before implementation. The final 77-case suite also passes against the exact
`4acaf58b` `_shape` source loaded in a separate process; 162 candidate cases
(those 77 plus existing capsule, consumer and staging suites) pass with zero
failures/errors/skips. Focused Ruff, compileall and diff-check pass. Both original
and candidate preserve live-hook backend replacement, interruption and dictionary
iterator failures as well as accepted/rejected results and node consumption.

An independent AST extraction of the original function and the candidate each
consume 2,885 nodes and observe the same 16 floats on one inert memory graph.
Recursive `_shape` entries decrease from 2,885 to 354. Nine alternating blocks
of 60 local calls have medians 374.23 to 348.69 microseconds (6.82%); this small
primitive result is not an end-to-end prediction. Retained evidence lives under
ignored `release-closeout-20261025/capsule-scalar-complete-baseline-jv9gty3i/`,
`capsule-scalar-complete-focused-tq222t_9/` and
`capsule-scalar-primitive-comparison-i6n5700n/`. Independent review and the new
integrated revision's own CI/mixed acceptance remain pending.
