# Validation

`uv run pytest -q --disable-warnings --basetemp=/private/tmp/lunar-native-output-20260928-02
tests/test_native_trusted_output.py`: 6 passed, including a compiled native target that wrote a
real two-file bundle under the trusted bootstrap.

`uv run ruff check src/lunar_evolution/native_trusted_output.py
tests/test_native_trusted_output.py` and `uv run python -m compileall -q
src/lunar_evolution/native_trusted_output.py`: passed.

Adjacent native-attempt, cooperative lifecycle, bundle-handoff and output-preparation suites:
31 passed. `git diff --check`: passed.

Tests use local files and one controlled recovered-terminal fixture. They do not run a provider,
external producer campaign, evaluator or publication. The still-open T159-05 is required for
production admission.

## Same-attempt capture checkpoint

The native runner now persists bounded envelope and material evidence under its original deadline.
A compiled two-file target is tested both with and without a local host-broker HTTP request.
Recovery verifies the receipt chain and rejects changed source bytes or broker journal bytes;
an expired deadline creates no receipt. The receipt remains ineligible for publication and the
request scope remains `brokered_requests_only`.

The combined native output/attempt, request transport/evidence, lifecycle matrix and isolation
regression passed **87 tests**. Ruff, compileall and diff checks passed. The HTTP target is a
local fixture; no external producer or model provider was called.
