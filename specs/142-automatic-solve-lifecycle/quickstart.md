# Automatic background solve

The background mode supports new native `solve --evolve --multi-file` runs and their explicit
continuations. Install the repository with `uv sync --extra dev` first.

## Offline acceptance

From the repository root, run:

```sh
.venv/bin/python tools/run_tests.py --suite native-e2e \
  --junit-dir .lunar-evolution/test-results/native-e2e
```

This creates fresh temporary workspaces and a loopback-only model fixture. It launches actual
Python coordinators, compiles a fixture evaluator, executes generated fixture candidates,
independently scores them, and verifies parent delivery. No model credentials or remote service
are needed. The scenarios also cover waiting for input, explicit continuation, cancellation,
deadline cleanup, recovery, terminal idempotency and wheel installation outside the checkout.
The runner verifies checkout imports and the selected test count, isolates pytest settings and
writes `native-e2e.xml` with failures, errors and platform skips visible. This focused suite does
not require historical checkouts or the fixed historical installer version; the installation
tests still require `uv` and cached build dependencies. It does not replace the full three-stage
release regression or registered real-model acceptance.

For just the actual foreground/background coordinator scenarios, run:

```sh
.venv/bin/python -m pytest -q tests/test_automatic_detach_phase_c.py
```

## Use with a configured runtime

Configure the runtime endpoint, model and credential through the existing runtime options and
`LUNAR_EVOLUTION_API_KEY` environment variable. Use a new home for your work; archived evidence is
not a writable home. For example, with a configured OpenAI-compatible endpoint and an existing
input file:

```sh
lunar-evolution solve "Build and optimize a complete multi-file solution for this input" \
  --evolve --multi-file --detach --agent-loop \
  --runtime openai-compatible --endpoint "$MODEL_ENDPOINT" --model "$MODEL_NAME" \
  --input ./input.json --candidate-generation-max-steps 40 \
  --evaluator-preparation-timeout 600 --evaluator-preparation-wall-timeout 1800 \
  --solve-wall-timeout 3000 --home .lunar-evolution --json
```

Use the returned `run_id` for all later operations:

```sh
lunar-evolution status RUN_ID --home .lunar-evolution --json
lunar-evolution events RUN_ID --home .lunar-evolution --json
lunar-evolution cancel RUN_ID --home .lunar-evolution --json
```

When `status` reports `awaiting_input`, the coordinator exits and releases ownership. Answer with
the same runtime settings:

```sh
lunar-evolution answer RUN_ID "The objective is ..." --detach --agent-loop \
  --runtime openai-compatible --endpoint "$MODEL_ENDPOINT" --model "$MODEL_NAME" \
  --home .lunar-evolution --json
```

For an admissible interrupted run or recoverable preparation failure, use:

```sh
lunar-evolution resume RUN_ID --detach --agent-loop \
  --runtime openai-compatible --endpoint "$MODEL_ENDPOINT" --model "$MODEL_NAME" \
  --home .lunar-evolution --json
```

`solve --resume --run-id RUN_ID --detach` is the equivalent solve entry point. Both restore the
saved multi-file and evolution policies. Supplied policy overrides must match. A rejected launch
after answer acceptance keeps the answer; use explicit resume instead of answering again.

Each admitted continuation gets one new active-execution deadline under the same saved policy.
Human waiting and process-launch delay are excluded. Exhausted, successful, failed or cancelled
runs do not start another worker. A busy owner or unconfirmed process cleanup refuses a second
execution. Historical automatic runs without the lifecycle marker, explicit profiles and external
producers are outside this background mode.

Offline acceptance establishes execution and recovery behavior. It does not establish real-model
success rates or close the separately registered real-delivery acceptance.
