# Failure-boundary curriculum policy

Feature 160's `FailureBoundaryPolicy` makes the provider-free failure-driven curriculum's
diversity, boundary probing and per-cluster budget explicit. It consumes only bounded public
failure observations and prior selections. It does not call a model or evaluator, inspect private
holdout data, mutate memory, or enable bandit/RL learning.

## Configuration contract

| Field | Default | Contract |
| --- | --- | --- |
| `policy_id` | `failure-boundary-v1` | Fixed supported policy version; unknown versions are rejected. |
| `prefer_uncovered_capability` | `True` | Prefer matching clusters that add uncovered capability/prerequisite coverage. Must be a Boolean. |
| `hard_negative_after` | `1` | After this many selections from a cluster, choose its hard-negative/boundary task. Integer in 1–128. |
| `max_cluster_selections` | `32` | Maximum choices from one cluster. Integer in 1–128 and at least `hard_negative_after`. |
| `normal_novelty` | `100` | Recorded novelty for normal/diversity tasks; integer in 0–100. |
| `hard_negative_novelty` | `80` | Recorded novelty for hard-negative tasks; integer in 0–`normal_novelty`. |

`to_dict()` returns the complete immutable configuration. `from_dict()` rejects missing/unknown
fields, unknown versions and numeric substitutions for Booleans. `digest()` hashes its canonical
configuration. Policy configuration is included in the curriculum component fingerprint and the
ledger digest, including when no selection has been recorded yet.

## Selection contract

1. Match the diagnosis against failure code, capability, public observable or practice task.
   If none match, retain the existing deterministic synthetic failure observation behavior.
2. Exclude matching clusters whose selection budget is exhausted. If every matching cluster is
   exhausted, fail before appending a selection or charging global curriculum budget.
3. With coverage preference enabled, select the cluster with the most uncovered distinct
   capability/prerequisite labels; resolve ties by stable cluster ID. With preference disabled,
   select the smallest eligible cluster ID.
4. Before the boundary threshold, choose the base practice task. If it was already selected,
   choose a deterministic `:diversity:N` task and record `failure_cluster_diversity`.
5. At or after the threshold, choose the configured hard-negative task, or a generated boundary
   task. Repeated probes receive deterministic numeric suffixes. Record
   `failure_boundary_probe` and `hard_negative=True`.
6. Record only newly covered capability/prerequisite labels, configured novelty, selection
   reason and global budget before/after. Each successful choice consumes one unit; failed
   choices consume none. No identical cluster/task pair is emitted twice.

The default policy preserves the previous first-task/second-boundary behavior. The novelty values
are auditable policy metadata, not evaluator scores or evidence that a generated task is useful.

## Durable replay and drift gates

New selection events retain the public `diagnosis` and `policy_sha256` alongside their selection
fields. `from_ledger()` verifies the policy digest, reconstructs coverage/counts, repeats cluster
selection from the diagnosis, and recomputes task, reason, coverage, novelty, budget, hard-negative
flag and selection identity. A changed policy, over-budget history, substituted cluster or changed
decision fails closed. Replay restores original budget consumption rather than performing a
second solver/curriculum side effect.

The controller checkpoint retains `policy`, `seed`, `budget`, `ledger` and `ledger_digest`. Resume
requires the current policy to match the checkpoint and recomputes component fingerprints before
any new work. A custom policy must be supplied again on restart.

Legacy checkpoints without `policy` mean the fixed default v1 policy. They cannot adopt a custom
policy. Their original seed/budget/ledger digest is validated with the historical formula, and
legacy selection events without diagnosis/policy metadata are accepted only under the default
policy. Their recorded cluster is retained, while every derivable selection field is recomputed;
the original diagnosis cannot be reconstructed. Newly written checkpoints use the policy-bound
digest, and all new selections carry the additional context fields. Existing run/component
fingerprint checks still apply: support for legacy checkpoint shape does not authorize replay
across code/configuration drift.

## Acceptance boundary

Focused tests cover bounded policy configuration, prerequisite diversity, threshold behavior,
eligible-cluster fallback, no-change exhaustion, deterministic replay, policy/digest drift,
selection-field tampering, custom-policy controller restart and default-only legacy recovery.
These are local fixture guarantees. They do not validate a real evaluator, an OpenEvolve/Shinka
campaign, model quality, automatic controller policy selection or learning gains.

```bash
PYTHONPATH=src:. pytest -q tests/test_rsi_curriculum.py tests/test_rsi_curriculum_resume.py
ruff check src/lunar_evolution/rsi_curriculum.py src/lunar_evolution/rsi_controller.py \
  tests/test_rsi_curriculum.py tests/test_rsi_curriculum_resume.py
python -m compileall -q src/lunar_evolution
git diff --check
```
