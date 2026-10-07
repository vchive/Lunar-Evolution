# Validation

Only local C/bootstrap, fixture, loopback and provider-free exact evaluators.

Local Python 3.11 installed project environment results:

- Producer config: 48 passed (`/private/tmp/lunar-producer-inputs-20261007.xml`).
- Retained helper + existing seed/generic handoff: 164 passed
  (`/tmp/lunar-seed-retained-oct7-all-v2.xml`).
- Actual native config + existing RSI/attempt/formal receipt: 138 passed
  (`/private/tmp/lunar-native-input-compat-20261007.xml`).
- Combined strategy/input/native/legacy suites: 568 passed, no skips/failures/errors
  (`/tmp/lunar-openevolve-native-combined-oct7.xml`, 82.718s). This run preceded the final
  nine strategy cases and conservative clock/publication refinements.
- Final actual strategy suite: 42 passed, no skips/failures/errors
  (`/tmp/lunar-openevolve-native-final-oct7.xml`, 30.496s). Covers those refinements, exact
  completed replay, active cancellation/ownership loss, narrower parent budgets, clock callback
  pauses, missing acknowledgement, effect replay refusal, callback drift and late commit cancellation.
- Final integration after public exports/CI wiring: 198 passed, no skips/failures/errors
  (`/tmp/lunar-openevolve-final-integration-oct7.xml`, 55.511s).
- Final trusted-constructor/legacy strategy regression: 272 passed, no skips/failures/errors
  (`/tmp/lunar-openevolve-constructor-final-oct7.xml`, 37.701s), including all 44 final native
  strategy cases and refusal to mutate leftover seed stage/backup directories.
- Ruff `src tests tools`, compileall `src tests tools`, public imports and diff check pass.

At this source commit the final-head Ubuntu matrix is pending; the PR checks and merge record
are authoritative for later CI/merge status. Local focused evidence is not a complete release runner.

Focused suites must include producer config binding, native input lifecycle, retained seed
admission, actual OpenEvolve strategy composition and legacy OpenEvolve compatibility. Required
negative cases: input/intent/executable/owner/deadline drift; repeated started claim; incomplete
execution/cleanup; cancellation/timeout; uncertain evaluation/publication; missing acknowledgement;
protocol downgrade; completed replay after expiry with no calls and unchanged bytes/inodes.

Run Ruff on `src tests tools`, compileall, branch diff check, and the final-head Ubuntu Python
3.11/3.12/3.13 complete current/archive/frozen CI. Keep actual first-run failure evidence. Fixture
success cannot close Python runtime provenance or real project/campaign acceptance.
