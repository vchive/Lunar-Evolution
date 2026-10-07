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

The first head `bb1a4b3` run `37647462556` Python3.13 retained a real current-suite failure:
`test_inherited_lock_has_no_gap_after_launcher_exits` used `select.select()` with a descriptor
above FD_SETSIZE. New trusted adapter173, existing native403, archive2294 and frozen24 phases
had no failures. Its first `current.xml` retains9867 cases/1 failure/30 skips; no full-phase retry.
The ownership readiness test now uses DefaultSelector with the same10s deadline and exact lock
handoff assertions. An actual high-descriptor pipe duplicate exercises the same child handoff;
no descriptor-table exhaustion or product ownership behavior is changed. The corrected head must
independently pass the full matrix.

The corrected ownership + native strategy focused run passed80 cases with no skips/failures/errors
(`/tmp/lunar-pr6-high-fd-focus.xml`); this includes the real child lock adoption with stdout FD>=1024.
Ruff, compileall and diff check passed again after the correction.

Focused suites must include producer config binding, native input lifecycle, retained seed
admission, actual OpenEvolve strategy composition and legacy OpenEvolve compatibility. Required
negative cases: input/intent/executable/owner/deadline drift; repeated started claim; incomplete
execution/cleanup; cancellation/timeout; uncertain evaluation/publication; missing acknowledgement;
protocol downgrade; completed replay after expiry with no calls and unchanged bytes/inodes.

Run Ruff on `src tests tools`, compileall, branch diff check, and the final-head Ubuntu Python
3.11/3.12/3.13 complete current/archive/frozen CI. Keep actual first-run failure evidence. Fixture
success cannot close Python runtime provenance or real project/campaign acceptance.
