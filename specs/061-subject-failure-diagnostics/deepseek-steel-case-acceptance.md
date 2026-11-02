# DeepSeek steel-cutting local smoke

Status: single original-budget attempt executed and failed (2026-11-02).
Schema2 runtime/budget_exceeded; no completed receipt/submission/evaluation.

The two newly registered DeepSeek scheduling attempts failed independently:
train reached its observed-token threshold; hospital rejected an HTTP200 tool
call. Preserve both failures. To exercise a smaller task through the complete
receipt/submission/local-evaluation path, select `steel_coil_cutting` based only
on its public instruction/data: 50 mother coils and 51 requirement rows in two
CSV inputs, 2,892 bytes total. No private score or solution was inspected for
selection; this is an additional functional smoke, not a replacement denominator
or an easier-case parity comparison.

Use the same focused-tested frozen source `f3257898b9080b2c6c8bc27c611d281e0d991f2f`
(tree `dfb6188541389f9522d38f03e2828ba9b80466b6`) as the two DeepSeek cases.
No new product implementation or new software regression is required for this
measurement-only variant; PR217's complete CI remains required before software
merge. Reuse the exact reviewed DeepSeek common/child bytes and profile:
`deepseek-chat`, 3,000 subject seconds, 40 tools, 160,000 observed tokens,
16,384 completion tokens; one fresh attempt, zero retries/fallback/resume.
Owner .env stays unchanged; only the new child's MODEL is overridden.

Copy the complete original case without modifying its source directory.
Publish only original instruction, business information and two CSVs, plus a
new public task that repeats the original instruction verbatim and explicitly
states the evaluator's filename/schema/representation contract. Inspect evaluator
imports/interface only after selecting the case. Publish no evaluator, private
baseline, algorithm or solution. The selected evaluator imports pandas, which
is unavailable under the existing evaluator's `-I -S` command. Preserve its
original bytes and provide a separate local evaluator venv, created with copied
Python executables and exact wheel-only, hash-locked pandas dependencies.
Pin interpreter, pyvenv.cfg, lockfile and complete venv file/directory inventories
before and after execution. Verify pandas imports in this venv without invoking
the evaluator, a model or a solver. No owner/development environment changes.

The new launcher may change only evaluator runtime preparation/validation:
verify its registered venv inventory at launch, immediately before conditional
evaluation, and afterwards (refuse subject-time drift before evaluation); invoke the registered
evaluator Python with `-I -B` (site packages enabled) instead of subject Python
with `-I -S -B`; and require the unchanged evaluator environment for completion.
The subject keeps its existing isolated-import interpreter/flags. Preserve all
one-shot, source/case/profile/receipt/submission/evaluator gates and limits.
Capture fixed dependency versions and import origins during the separate venv
preflight; do not describe those as instrumentation of the evaluator process.
Never pass provider credentials to the evaluator. This is local environment evidence,
not proof of an immutable OS. Independently review these precise helper changes
before launch. Do not rewrite the evaluator to avoid its prerequisite.

Create a distinct case/publication identity and attempt, pin exact complete
source/case/public/profile/helper/Python inputs, and independently review the
preparation. Push exact registration before authorization and dispatch. Use the
existing 3,020-second supervisor plus five seconds each TERM/KILL and 1 MiB per
stream. After original completed receipt validation and actual declared output,
invoke the unchanged copied local evaluator once, without model credentials,
for 30 seconds plus five seconds KILL/reap. No repaired or fabricated answer.
Require evaluator rc0 and finite scores with validity exactly 1; report quality
separately. Missing/invalid/failed/over-budget outputs remain failed attempts.

Preserve and independently review original history, logs, usage, terminal
receipt/failure, module provenance and before/after inventories without rerunning
inference or scoring. No WebAgent, remote evaluator, native RSI campaign or OS
isolation claim. `production_admission=false`, `online_publication=false`.

## Tasks

- [x] Select a smaller case on public input complexity before scoring inspection.
- [x] Define the exact public output contract and prepare frozen identities.
- [x] Independently review, push registration and launch once.
- [x] Review original terminal evidence and publish actual outcome.

## Prepared identities

The exact declared output is workspace-root `solution.csv`, with required
`mother_width,mother_cut_weight,sub1_width` and documented optional strip
width/count/weight fields. Only this root path is selected before any score.
Original13/copy14/public5 file ledgers retain original instruction, business
information and both CSVs. Copied original bytes are unchanged, with write bits
removed; this does not create an OS isolation claim. Original evaluator SHA256:
`2b2d19d5c238b88d2994d1810974d0735188924ad7ce522ba2aae4d71b459278`.

Case digest is `856bb60891a4d4b402920583068e0ebe71db3420b0f0d33e87b8c5127e930203`;
publication digest `2b86f36e59e6dacbe0560cb232a66001b2519e2c97e63fc43fc8cae7202ddd51`.
Fresh attempt: `ordinary-deepseek-f3257898-steel-cutting-20261102-attempt-001`.
One-shot manifest SHA256:
`af0b5a304e5ce43cd7287a9d76e458207b822f44ffef745d14cdd7cf4fb884bc`.

Evaluator venv has 4,586 files / 434 directories / 88,406,617 bytes. Exact
wheel-only hash-locked versions: pandas2.3.3, numpy2.3.4,
python-dateutil2.9.0.post0, pytz2025.2, tzdata2025.2, six1.17.0; Python3.13.12.
Environment manifest SHA256:
`cc43f4b7409e9f69fc718c63202f36cf29e123a8f8b65b5151d4c4b3b70afc02`.
Initial dependency-import preflight timed out at 30 seconds and was reaped;
its record is retained separately, with no model or evaluator invocation.
Subsequent import diagnostics and final version/origin preflight passed.

Common/child retain their prior reviewed bytes. New launcher SHA256:
`01cab2387a906a5b07507daf8a6e8d8cc18c640ec96461d3531c4dc4a2a2693c`;
preparer `2ac55675c6c9f09c5da7058496375dd54470cf48c46fcd8f631b215a7e3ec6b3`.
Independent code/environment review SHA256:
`71cf7345986a557ec2830f16bc2909ce6e29ce6f6d1beffc65049fafcabac72c`;
actual prepared-byte review:
`5e82d3609b1302f26a4d1227d84a7d34403b1d4226c73e10e3682fff0f2b110d`.
Both reviews found no blocker and performed no dispatch.

PR217's initial full CI exposed stale fixed-profile transport source pins;
that separate producer preparation integration is being corrected. This
ordinary smoke invokes neither preparer nor generated broker. Its execution
stays pinned to f3257898, not the later corrected source; do not substitute
its result for fixed-profile regression or production/native RSI acceptance.
Registration93831e75 was pushed before the one launch at
2026-11-02T13:51:48.247337Z. It ended rc2 in117.46290920861065 seconds:
22HTTP200 completions, 21 accepted rounds/28tools, 155,656 accepted partial
tokens; observed169,992 exceeded160,000. No evaluator ran. Independent
terminal review SHA256:
`43c4d7d59114909b1a63df8354a1e27ebbda6dd0b9aef01b7cdf0d0c6773200b`.
See the [actual result](../../docs/deepseek-steel-case-acceptance-20261102.md).
