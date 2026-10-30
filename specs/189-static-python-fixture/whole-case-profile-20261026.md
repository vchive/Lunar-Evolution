# Exact-source whole-case performance diagnostic

The single standard cProfile diagnostic on an independent archive of
`1e6f10f804495a3c1e8f41fc3f04968f01c11d02` completes with one passing
`three-child-mixed` case, pytest 554.44 seconds, launcher 554.705871 seconds
and raw return code zero. The outer and original inner budgets stay at 600
seconds, with zero retries and asynchronous faulthandler disabled. The 2,364
source files match the archive/Git bytes, sizes and executable bits before and
after. This macOS diagnostic does not replace the three original CI failures
or establish independent Linux acceptance for a successor source.

An earlier preparation stopped before the selector because it compared tar
permission 0664 with unpacked 0644 rather than the Git executable-bit contract.
Its failure remains retained. The actual selector ran once. One OS-level
one-second process sample near completion is retained separately; no signal
handler or second selector was added.

## Observations and limits

| Function or operation | Recorded calls | Recorded self / cumulative seconds |
| --- | ---: | --- |
| JSON dumps | 7,696,900 | 4.91 / 69.19 |
| JSON encoder iterencode | 7,716,571 | 57.10 / 57.10 |
| JSON decoder raw_decode | 942,835 | 48.41 / 52.94 |
| Ready-capsule `_shape` | 103,917,180 | 30.25 / 40.08 |
| Runtime-tree parser | 7,373 | cumulative 82.58 |
| Runtime-tree `_canonical` | 26,951 | 14.04 / 51.87 |
| Owner `_identity` | 1,395 | cumulative 174.57 |
| `_validate_persisted_policy` | 1,547 | cumulative 155.81 |
| Handoff `_validate_file_pin_payload` | 2,151,852 | 8.27 / 31.61 |
| `component_fingerprint` | 51,077 | cumulative 21.60 |

The standard profile's cumulative times overlap. Some threaded cumulative
timers exceed elapsed wall time, and some direct caller rows have anomalous
attribution. Do not sum these numbers, convert them into wall-time shares, or
claim a precise causal saving. `_policy` records only 5.67 cumulative seconds
and `_dedent_source` 1.23; this does not support continued blind fingerprint
optimization. The serial driver already owns an enclosing policy observation
scope, and its lifetime must not expand.

The next narrow implementation inlines exact scalar validation inside the
existing ready-capsule container walk. Full history reads and reference checks
remain fresh. Runtime-tree canonical JSON stays bounded and streaming; replacing
it with unbounded one-shot encoding would remove its early capacity gate.
The separate runtime-manifest reconstruction feasibility review remains
deferred because constructor/parser alias and serializer semantics need more
than a parser identity check. File-pin DTO drift revalidation remains required.

## Retained evidence

Ignored primary-workspace evidence is under
`release-closeout-20261025/exact1e6-whole-case-cprofile-hza1cn9p/`:

- `diagnostic-summary.json`, SHA256
  `c0474fa2abcbea2c70862647f2f692f247d83399a7000a34ea3a87360e8ef189`;
- `whole-case.pstats`, SHA256
  `17da44993da76e54664b94f7706da271801db58f880cdf49d4d2d4adb0814c80`;
- original XML, raw output/return code, source inventories, archive, claim,
  runner, top20/direct-edge extracts and the separate OS sample.

This is an inert provider-free fixture. No project producer, model service,
remote evaluator or benchmark platform ran. Runtime custody, production
admission and online publication remain unaccepted and disabled.
