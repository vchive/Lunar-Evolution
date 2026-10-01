# Explicit repeated-pass confidence gate

## Scope and contract

This is an opt-in deterministic analysis of local repeated observations. It does not replace the
default transfer regression gates, schedule evaluation, authenticate evaluator observations or
activate memory. A runner/promotion orchestrator may explicitly require its evidence in addition
to the existing source, verifier and holdout gates.

`PassObservation` binds a task digest, repetition, public seed, boolean official pass, observation
receipt and optional bounded score. Scores are retained only for inspection. `ConfidencePolicy`
specifies a finite confidence level, minimum/maximum sample counts, minimum official pass rate and
allowed pass-rate regression. Maximum samples are bounded to 4096 per arm; thresholds are in
0..1 and confidence is in 0.5..0.999999. No score can substitute for `passed=True`.

`evaluate_transfer_confidence` freezes a task-manifest digest, evaluator fingerprint, full policy,
and no/old/current-memory observations. Every arm must have exactly the same task/repetition/seed
keys, unique within the arm, and at least two repeats for every task. It computes a two-sided Wilson
interval for each arm's aggregate Bernoulli pass rate. Too few samples returns `unresolved`.
With sufficient samples, an observed pass-rate failure or regression returns `fail`. Otherwise the
candidate lower confidence bound must meet the minimum, and its lower bound minus each baseline
upper bound must meet the explicit regression tolerance. Inconclusive bounds return `unresolved`.
Only `pass` yields additional promotion evidence; it never grants governance admission by itself.

The interval assumes comparable, approximately independent Bernoulli observations. Aggregate
intervals do not establish task-family generalization or compensate for correlated/noisy samples.
Intervals are marginal per-arm confidence intervals, not a simultaneous family-wise guarantee
over all promotion comparisons. Their method is recorded as `wilson-score-marginal-v1`.
The policy is fixed before analysis; callers must not search policies until a rejected report passes.
Strict zero regression tolerance may leave equal high-performing arms unresolved; callers must
choose and justify any bounded tolerance explicitly.

Canonical report bytes bind raw observations, summaries, verdict/reasons and all input pins.
`recover_confidence_report` requires the caller's retained `expected_receipt_sha256`, can also check
independent expected task-manifest/evaluator/policy pins, and recomputes the full deterministic
analysis. Changed metadata, policy, summaries, eligibility, missing/duplicate samples or
noncanonical bytes are rejected. Recovery invokes
no callback and consumes no additional evaluation budget.

## Implementation and validation

Files: `rsi_noise_confidence.py`, `test_rsi_noise_confidence.py`.

- Known Wilson values and deterministic replay.
- Insufficient sample and uncertain-confidence outcomes are unresolved.
- Better sufficiently sampled candidate passes; high scores with failed passes and observed
  regression fail; explicit tolerance cannot be changed without a new receipt.
- Missing/duplicate/misaligned seeds/repetitions, nonboolean passes, nonfinite/out-of-range policy,
  excessive sample counts, tampered/self-rehashed reports and noncanonical bytes reject.
- Caller mutation of returned report projections cannot mutate frozen evidence.

Run focused tests, Ruff, compileall and diff checks. No remote evaluator, WebAgent, provider or
real OpenEvolve/Shinka campaign is involved.

## Local validation result

The implementation and 57 focused confidence tests pass. Focused Ruff, compileall and
`git diff --check` pass. This remains an explicit analysis API. A future promotion integration
must bind the report's raw observation receipts and manifest/evaluator pins to its actual frozen
transfer campaign and snapshot pair; the confidence receipt alone is not memory admission authority.
