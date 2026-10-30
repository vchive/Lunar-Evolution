# Path/scheduler candidate acceptance, 2026-10-27

The exact tested source is `298fe05aee62da0af1c7d92b2341c091150ef8f6`,
tree `0e0c10ab7fb7657b16e2505a298bc1ae1f7ac26a`. Its local union passes,
but its sole Linux mixed acceptance fails at the original 600-second deadline.
PR189 cannot merge on this evidence. A documentation successor is not the
tested source.

## Local union

67 files contain 2,610 distinct collected tests, all passing, with zero failures,
errors or skips. Raw rc is zero; elapsed time is 103.65521020884626 seconds.
The old 2,245 nodes are retained. All 2,384 source files match Git/archive bytes,
sizes and executable bits before and after. Independent audit passes 24 checks.
No runtime `sys.modules` origin census was retained locally.

Primary-workspace ignored evidence under `release-closeout-20261025/`:

- `path-scheduler-final-union-6kfca_fe/`; original JUnit SHA256
  `65d45068d6291293d15ead82a1e109d1f649ac0055ef36884cab41dfda15db56`.
- `path-scheduler-union-independent-zgoverzb/review.json`; SHA256
  `a3588b80af41dcb401ba51426981af987ebe1966fd543229b1c1766058549366`.

Ruff over `src tools tests`, compileall and diff checks also pass. Local path and
shape timing measurements remain microbenchmarks, not mixed acceptance results.

## Linux acceptance

Selector:
`tests/test_rsi_brs_reserved_serial_integration.py::test_natural_reserved_children_complete_in_original_order[three-child-mixed]`.

The single execution uses the original 600 seconds, with zero retries and
asynchronous faulthandler disabled. The deadline starts before output-open and
Popen; PID/starttime/UID setup consumes that same budget. It times out after
600.0159354899079 seconds, raw rc -15. Output streams are empty. Neither JUnit
nor execution-terminal origins exist. The retained 217 preflight imports do not
replace execution-origin evidence.

The archive's 2,675 entries and 2,384 regular source files match Git and the full
source inventories before and after. Six runner scripts match their original
pins. 25 independent preservation checks pass; a further read-only review
confirms the evidence and arithmetic. SSH/orchestrator rc0 means evidence
collection completed, not that the case passed.

The initial uncompressed upload timed out before preparation or driver launch.
A read-only check found its known directory empty, with zero case executions.
The compressed successor transfers the same original source and runner bytes
into a new create-only directory and executes the case once. The failed
transport directory, original tool error and classification remain retained.

Evidence:

- `brs-mixed-298fe05a-qa2jpfmj/`: original transport failure/classification.
- `brs-mixed-298fe05a-compressed-bjlgnb8m/`: sole execution and original records.
- `pid-accounting-offline-analysis-qv1zbsf6/real298-artifact-verification.json`,
  SHA256 `79a7e0c4b1d859eae8b6d0ac864a92eacc6bbd2df82904bab59766f9070b4b73`.

## Known-PID observations and limits

120 samples retain the known unreaped Popen child's PID, UID and starttime.
The process counters share the same sample 0-to-119 window:

| Observation | Delta |
| --- | ---: |
| Wall time | 594.998627324 seconds |
| Thread-group user + system CPU, excluding child processes | 596.79 seconds |
| Leader-only scheduling runtime | 511.773792792 seconds |
| Leader-only runqueue wait | 0.112289451 seconds |

Observer thread CPU over the entire sampler is 0.055160043 seconds; it is not
limited to the first-to-last process sample window.

The counters support investigating computation cost in this known process.
They do not identify the responsible function, quantify the observer's full
interference, describe every worker thread/descendant, or prove an I/O/root
cause. The last sample is near 595 seconds: the final approximately five
seconds and termination-time counters are absent. No whole-process-group exit
proof is inferred. Optional counters and their scope remain as recorded.

The offline analyzer passes 50 pure fixture tests and independent static review
before its one execution on the final records. Its complete sequence describes
the sampled window, not terminal process/group accounting.

- `pid-accounting-offline-analysis-qv1zbsf6/real298-analysis.json`, SHA256
  `1d7cb2d3c736919f9591727f27cbf5f53cb7b792ee6f7c23b0c8c6aacd21631e`.
- `pid-accounting-offline-analysis-qv1zbsf6/real298-independent-review.json`,
  SHA256 `eaff55f9f990d4c60c9493f6b8506a7a1aac873411e445f5e3c76af3931e93d1`.

## CI and remaining gates

[Run40441736505](https://github.com/vchive/Lunar-Evolution/actions/runs/40441736505)
is still in progress for exact head298fe05a, attempt1. Its complete result and
33 artifact ZIPs must be collected after natural termination. The reviewed
terminal collector is prepared but has not executed. Do not cancel, retry or
push a documentation-only update to interrupt this run.

P0 remains the mixed timeout and computation-cost investigation, successor-source Linux/CI gates,
and the separate earlier ordinary-model E2E failure. No model request, remote
evaluator or company evaluation ran here. P1 still requires accepted static
runtime custody/build, sealed startup and authoritative inputs, followed by
real solver/broker lifecycle and production CLI. The isolation environment
blocker remains unchanged; P2 distributed work stays deferred.

`production_admission=false` and `online_publication=false` remain in force.
