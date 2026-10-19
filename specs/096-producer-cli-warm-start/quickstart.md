# Export and warm start

Use an already completed local Shinka result directory and the Lunar contract it was intended to
solve. Set `SHINKA_FINGERPRINT` to your pinned 64-character lowercase SHA-256 identifying that
producer version/configuration; use the same pin for export and import.

```sh
lunar-evolution export-shinka-result ./shinka-run \
  --output ./shinka-export \
  --contract ./contract.json \
  --producer-fingerprint "$SHINKA_FINGERPRINT" \
  --program-id program-1 --program-id program-2 --json

lunar-evolution evolve ./contract.json \
  --producer-result ./shinka-export \
  --producer-fingerprint "$SHINKA_FINGERPRINT" --producer-id shinka \
  --generator-command "/absolute/path/to/generator" \
  --evaluator-command "/absolute/path/to/local-exact-evaluator" \
  --population-size 4 --max-rounds 3 --json --home .lunar
```

The first command exports material only. Its JSON output includes
`evidence_scope=retained_local_material`, `solver_execution=retained_result_export`, and
`production_admission=false`; these fields describe the export boundary and are not a process or
publication receipt. Its output directory must be new, with an existing parent;
Shinka's database must be quiescent with no WAL/SHM/rollback-journal sidecars. Repeated `--program-id`
values select an ordered set, including rows the producer marked incorrect. Alternatively use
`--top-k N` (default one) to select producer-correct rows by producer score; the two forms are
mutually exclusive. Export output reports `exported`, material count, export root and envelope
digest. It creates no Lunar home/database and calls no evaluator or producer process.

The second command prepares a manifest in memory, then uses normal Lunar seed admission. The local
exact evaluator decides validity and score. Exported scores/correctness are only source evidence;
invalid seeds are rejected, and an all-invalid batch fails before population search. Choose a
population size large enough for the accepted seeds. `--producer-id` is an optional additional name
pin. The producer fingerprint is required and must match the envelope declaration; it is not derived
from that untrusted declaration automatically.

Keep the exported root and evaluator configuration unchanged for resume. Add `--resume --run-id ID`
to the same evolve command. Completed resume revalidates seeds with the local evaluator and keeps
stable seed identities without rerunning the generator. `--detach` forwards the producer root and
pins to the normal background child. Do not combine `--producer-result` with `--seed-manifest` or
its dependency/environment override flags. Producer import uses the generic adapter's existing
source-bundle dependency digest and declared-protocol environment digest; it does not attest to an
external runtime installation or downloaded dependencies.

The same evolve flags accept any completed `lunar-producer-result-v1` directory, including material
exported by another compatible producer. They do not run or install Shinka/OpenEvolve. A manifest
can also be prepared directly with `lunar_evolution.prepare_producer_seed_manifest(...)`; preparation alone
never creates a Candidate, score or evaluator receipt.

# Offline validation

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_producer_handoff.py tests/test_producer_cli.py tests/test_producer_cli_integration.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
uv build --offline
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/096-producer-cli-warm-start" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
