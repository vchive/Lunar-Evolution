# Lunar Evolution

Lunar Evolution is a standalone, local-first agent for conversational problem solving **and concrete
data production**. It is inspired by Hermes' continuous sessions, practical tools, and long-running
memory, but keeps the durable task ledger, artifacts, optional memory, and algorithm outputs in a
run-scoped local directory. It does **not** require a machine-wide Hermes, OpenCode, or Codex
installation. A natural-language answer is only the audit trail; an algorithm mission is complete
only when its declared output files pass independent checks and are delivered as hashed artifacts.

The project is being developed with Spec-Driven Development (SDD). The current executable
deep-evolution effect-measurement boundary is captured in
[`specs/051-deep-evolution-effect-trial/`](specs/051-deep-evolution-effect-trial/), with the
controlled feedback contract in
[`specs/052-deep-evolution-feedback-contract/`](specs/052-deep-evolution-feedback-contract/) and
the diagnostic failure projection in
[`specs/053-deep-effect-failure-statistics/`](specs/053-deep-effect-failure-statistics/). Its normal
single-session predecessor remains in
[`specs/050-content-addressed-effect-kit/`](specs/050-content-addressed-effect-kit/). It compiles
one or two local reference-benchmark cases into a deterministic public-only trial kit and records owner-confirmed
cross-release content equivalence without pretending it is an official publication identity. This
builds on the fresh Lunar Evolution subject, exact private extractor/evaluator harness adapter, and offline
per-run results converter for the external reference benchmark in
[`specs/049-reference-benchmark-adapters/`](specs/049-reference-benchmark-adapters/) and the strict protocol in
[`specs/048-reference-benchmark-breakthrough/`](specs/048-reference-benchmark-breakthrough/). That protocol adds a bounded,
recoverable one/two-case normal-Agent trial against exported reference-benchmark per-run history.
It deliberately does not call an evolution strategy or claim 20-case parity. This builds on the
quality-diverse native population in
[`specs/047-quality-diversity-population/`](specs/047-quality-diversity-population/) and the
solver-visible scoring contract in
[`specs/043-solver-scoring-contract/`](specs/043-solver-scoring-contract/), building on the
adversarial evaluator-audit boundary in
[`specs/042-adversarial-evaluator-audit/`](specs/042-adversarial-evaluator-audit/), the
private-data profiling boundary in
[`specs/041-private-data-profiling/`](specs/041-private-data-profiling/) and the frozen evaluator
bundle in
[`specs/040-frozen-evaluator-bundle/`](specs/040-frozen-evaluator-bundle/), which builds on the
execution-grounded refinement loop in
[`specs/039-execution-grounded-refinement/`](specs/039-execution-grounded-refinement/) and the
optional exact scorer in
[`specs/038-objective-harness-handoff/`](specs/038-objective-harness-handoff/), which adds an
optional exact local objective scorer to the execution-grounded search in
[`specs/037-execution-grounded-evolution/`](specs/037-execution-grounded-evolution/), building on
the evolved-output materialization boundary in
[`specs/036-evolved-output-materialization/`](specs/036-evolved-output-materialization/), building
on the conversational evolution handoff in
[`specs/035-conversational-evolution-handoff/`](specs/035-conversational-evolution-handoff/),
building on the runtime-profile benchmark in
[`specs/029-runtime-profile-benchmark/`](specs/029-runtime-profile-benchmark/), building on the
evolution Agent evidence work in
[`specs/030-evolution-agent-evidence/`](specs/030-evolution-agent-evidence/), and the structured
algorithm output work in
[`specs/031-structured-algorithm-outputs/`](specs/031-structured-algorithm-outputs/), building on the
algorithm input staging work in
[`specs/032-algorithm-input-staging/`](specs/032-algorithm-input-staging/), building on the
strict role evidence contracts in
[`specs/033-role-evidence-contracts/`](specs/033-role-evidence-contracts/), building on the
one-shot runtime artifact envelope in
[`specs/034-runtime-artifact-envelope/`](specs/034-runtime-artifact-envelope/), building on the
unified evolution benchmark in
[`specs/028-unified-evolution-benchmark/`](specs/028-unified-evolution-benchmark/), building on the
reproducible native benchmark in
[`specs/027-evolution-benchmark/`](specs/027-evolution-benchmark/), building on the evolution Agent
loop in
[`specs/026-evolution-agent-loop/`](specs/026-evolution-agent-loop/), building on the built-in
algorithm role DAG in
[`specs/025-algorithm-role-dag/`](specs/025-algorithm-role-dag/), building on the conversational
algorithm mission in
[`specs/024-conversational-algorithm-mission/`](specs/024-conversational-algorithm-mission/), building
on the verified candidate execution work in
[`specs/023-verified-algorithm-execution/`](specs/023-verified-algorithm-execution/), building on
the completed runtime-backed evolution and independent evaluator ensemble in
[`specs/022-runtime-backed-evolution/`](specs/022-runtime-backed-evolution/) and
[`specs/021-evaluator-ensemble/`](specs/021-evaluator-ensemble/), which is built on
independent artifact acceptance contracts in
[`specs/008-artifact-acceptance-contracts/`](specs/008-artifact-acceptance-contracts/) and domain
routing, profiles, and budgets in
[`specs/007-domain-routing-solver-evaluator/`](specs/007-domain-routing-solver-evaluator/). The earlier
WebAgent-style experiment is retained as a superseded draft in
[`specs/002-webagent-effect-parity/`](specs/002-webagent-effect-parity/).

## Conversational algorithm missions

You can now start an algorithm task without authoring a contract by hand. `solve` first compiles a
strict `AlgorithmProblemContract`, then attaches a versioned plan and runs the normal durable DAG:

```bash
lunar-evolution solve "根据订单数据设计配送路线" --runtime mock --json --home .lunar-evolution
```

For a local model, use an explicit repository runtime (no global Hermes/OpenCode/Codex state is
read):

```bash
lunar-evolution solve "根据订单数据设计配送路线" \
  --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1/chat/completions \
  --model your-local-model --json --home .lunar-evolution
```

The compiler must return a strict JSON envelope; one complete lowercase `json` code fence with LF
delimiters is also accepted as framing. Prose, multiple objects, duplicate keys and non-finite
numbers are rejected without repair or retry. If a material objective, input, constraint, or
deliverable is unknown, the run returns `status=awaiting_input`; answer the same run and it will resume
compilation:

```bash
lunar-evolution answer <run-id> "最小化总行驶时间" \
  --runtime openai-compatible --endpoint http://127.0.0.1:11434/v1/chat/completions \
  --model your-local-model --json --home .lunar-evolution
```

The run ID remains stable. Contract, plan, compiler manifest, input answers, and generated task
artifacts are all local and SHA-256 indexed. The baseline generated DAG is
`data_discovery → formulate → solve → verify`; candidate evolution remains an explicit opt-in
stage through `evolve`.

For a conversational mission that should search candidates immediately, use `--evolve`. Lunar Evolution compiles the contract first and then links a second durable evolution run:

```bash
lunar-evolution solve "根据订单数据优化配送路线" \
  --runtime mock --evolve --strategy population --max-rounds 3 \
  --json --home .lunar-evolution
```

The JSON response includes the intake `run_id` and `evolution.run_id`. The intake keeps the
validated contract and explicitly supersedes its unstarted generated-plan tasks; the child owns
`evolution/archive.jsonl`, `state.json`, and `result.json`. Staged `--input` files are copied into
the child with the same SHA-256 and size, never with the source-machine path.

For new native `population` runs, every generated `.py` candidate runs in its own archive directory
before model evaluation. It receives digest-checked `data/raw/*` copies and a minimal
non-secret environment. Required and present optional outputs must pass the immutable
CSV/JSON/JSONL/text contract; a process or output failure becomes local validity zero and skips the
model evaluator entirely. Successful evaluator requests contain a bounded source excerpt,
execution summary, and output path/schema/size/SHA-256 metadata—not raw input or output contents.
Source-only contracts receive the same process gate without requiring output files.

When the compiled contract declares `outputs`, Lunar Evolution then runs the selected best candidate
once more in a separate final workspace. Search-time output is evidence only and is never promoted
directly. The final candidate must recreate the exact declared files before Lunar Evolution stages their
bytes and journals the output batch in the intake workspace. Final paths use no-clobber links;
all new artifact rows and promotion evidence commit in one SQLite transaction. The response exposes this as
`evolution.materialization`; a failed process, timeout, missing/malformed output, symlink,
oversized file, or conflicting destination makes the effective `solve` status fail and prevents
`deliver`.

Feature [088](specs/088-recoverable-output-publication/) makes a failed multi-file publication
recoverable: a confirmed uncommitted batch removes only its own new links and preserves existing
outputs. Resume validates the batch before accepting a materialization result. Unknown commit
state or changed evidence preserves the attempt and stops delivery. Filesystem readers can still
observe a prefix during publication or until crash recovery runs; the atomic boundary is the
SQLite batch. Staging and journal files are retained. Output recovery never reruns the candidate
or infers a terminal result from output files alone.

Feature [089](specs/089-recoverable-materialization-result/) also makes terminal result registration
recoverable. Lunar Evolution retains the validated result bytes and a database preparation receipt before
publishing `result.json`. Resume can finish that exact pending result and register its artifact and
events atomically, without executing the candidate again. A completion receipt prevents damaged
completed results from being silently repaired. Old results remain subject to strict read-only
validation. Fragmented terminal preparation still requires diagnosis; the protocols below cover
candidate launch, execution registration and earlier delivery phases.

Feature [090](specs/090-durable-materialization-launch/) records and syncs a launch intent in the
child workspace and SQLite before entering the final runner. A nonblocking child lock covers the
whole materialization lifecycle; another active caller gets `materialization_already_running`.
If the controller exits after authorization, resume preserves the attempt and refuses to launch it
again, even when no execution result exists. Intact completed results and prepared terminal
publications remain reusable after validating launch and execution evidence. Intent records
authorization, so interruption before the runner actually starts can also require diagnosis.
This prevents automatic duplicate launch under the protocol; it does not guarantee completion or
exactly-once execution or identify surviving processes.

Feature [091](specs/091-recoverable-materialization-execution/) makes explicitly prepared execution
registration recoverable. After the runner returns, Lunar Evolution checks the exact execution bytes and
launch intent, retains a journal, and records a preparation receipt. The execution artifact and
its events then commit together. Resume can finish this pending registration without running the
candidate; retained completion or downstream publication evidence prevents deleted records from
being rebuilt. Raw `execution.json` alone never authorizes recovery.

Feature [092](specs/092-recoverable-materialization-delivery/) continues delivery from a complete
modern execution registration. If no downstream publication exists, resume independently verifies
the retained attempt and durably records a delivery plan before publishing. Once prepared, it
reuses committed output evidence to finish the terminal result; confirmed output rollback produces
an explicit failed result without republishing. The candidate never runs again during recovery.
Damaged prepared or committed records stop recovery; an intact terminal can finish a missing
delivery completion receipt. Exact older terminal preparations remain recoverable without
migration. Interruptions before complete execution or delivery preparation can still require
diagnosis; successful delivery is not guaranteed.

Feature [093](specs/093-readonly-materialization-diagnostics/) adds
`diagnose-materialization PARENT_RUN_ID EVOLUTION_RUN_ID`. It reports bounded observations for
launch, execution, delivery, outputs and terminal evidence without initializing the run, creating
locks, invoking recovery, or running a candidate. The database and any uncheckpointed WAL are
read from a private snapshot so source records and directory entries remain unchanged. Reports
always set `recovery_eligibility` to `not_assessed`; an attention or unavailable result preserves
evidence for normal resume and manual diagnosis.

Feature [094](specs/094-materialization-evidence-bundle/) adds
`export-materialization-evidence PARENT CHILD --output FILE`. It writes a bounded, no-clobber,
脱敏 bundle containing the 093 report and protocol identity/hash summaries. The command uses the
same private database/WAL snapshot before normal storage initialization; it never writes the run
workspace or database and never authorizes recovery.

Feature [095](specs/095-manual-execution-attestation/) adds the explicit operator command
`attest-materialization-execution PARENT CHILD --receipt FILE`. A reviewed canonical receipt binds
one exact launch, candidate, task and retained execution file, including its digest and inode.
Lunar Evolution preflights a private database copy, then revalidates under the lifecycle lock and records the
attestation together with execution preparation. The command only registers execution; normal
resume can then continue delivery without rerunning the candidate. Exact receipt retries are
idempotent, while changed bytes, reused nonce and downstream records are refused. This is local
operator authorization and audit evidence, not proof that a process ran or outputs succeeded.
See the [operator guide](specs/095-manual-execution-attestation/quickstart.md) for receipt format and
recovery limits. No attestation is generated automatically from raw evidence or diagnostics.

Resuming the intake reuses the same child and terminal materialization, verifies candidate and
output digests, and rejects changed strategy settings instead of executing or overwriting again.
Contracts without `outputs` keep the existing source-only result. `evolve CONTRACT` remains
available when separate generator/evaluator commands or an OpenEvolve wrapper paired with a local
exact evaluator are needed.

When a domain already has an exact local objective or constraint checker, keep the conversational
compiler/generator path and replace only model scoring:

```bash
lunar-evolution solve "optimize routes and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --strategy population \
  --evaluator-command "/absolute/python /absolute/score_routes.py" \
  --json --home .lunar-evolution
```

The harness receives the candidate path after local execution/output validation and can inspect its
sibling `data/raw/*`, `output/*`, and `execution.json`. It returns the existing strict
`EvaluationReport`; archive selection maximizes its non-negative `combined_score`, so a cost
minimizer can use `1 / (1 + cost)` and retain raw cost with direction `minimize` in
`detailed_scores`. The subprocess receives a minimal UTF-8/locale environment rather than model
credentials or arbitrary parent variables. Its command is fingerprinted but not persisted; resume
must supply the same `--evaluator-command` again. Final output still comes from the independent
clean-room materialization, never directly from search evidence.

If no exact scorer already exists, native search can explicitly compile one before the first
candidate:

```bash
lunar-evolution solve "minimize route cost and write output/routes.csv" \
  --input ./orders.csv --runtime openai-compatible \
  --endpoint http://127.0.0.1:11434/v1 --model local-model \
  --evolve --compile-evaluator --strategy population \
  --max-rounds 5 --json --home .lunar-evolution
```

The evaluator compiler is a separate runtime turn. Before invoking it, Lunar Evolution verifies the
exact staged input ledger and locally profiles CSV, JSON, JSONL, or text data. The compiler sees
only relative paths, format, byte size/SHA-256, row or line count, actual field names, conservative
types, null counts, and unique counts. It never receives rows, raw values, samples, extrema,
category labels, or source-machine paths. Malformed/ambiguous data, unsupported formats, symlinks,
or ledger drift fail before the compiler or search runs.

The compiler must return a strict objective, Python evaluator, one synthetic rejecting probe per
hard constraint, at least two valid probes, and a declared better/worse score ordering. Lunar Evolution
statically rejects dangerous imports and dynamic execution, runs every probe locally, and parses
every result through `EvaluationReport`. It then starts a fresh adversarial auditor turn. The auditor
sees the immutable contract, private structural profile, objective, and evaluator source—but not
the compiler's probes, raw values, or any solver/search evidence—and must produce a second complete
probe suite. Search starts only after both suites prove constraint validity, matching error codes,
and strict score ordering. This catches correlated evaluator/self-test omissions such as accepting
duplicate entities merely because row counts match.

Before the first probe in either suite runs, every synthetic input must pass the same format
parser as real input profiling: JSON objects or arrays of objects, JSONL object records, CSV with
valid headers and row widths, or UTF-8 text. This also applies to probes with invalid outputs.
Small synthetic inputs may differ from private row counts and field statistics; admission does
not infer business schemas from field descriptions. Existing frozen bundles load without replaying
probes or reapplying this creation-time check. See [126 validation](specs/126-synthetic-input-format/validation.md).

Lunar Evolution hashes and freezes `objective.md`, `evaluator.py`, canonical `probes.json`, independent
`audit.json`, canonical `input-profile.json`, and `manifest.json` under the intake run. The profile
and audit digests are part of bundle identity. Resume re-profiles current ledger-bound bytes and
reuses the same bundle without another compiler or auditor call; input, profile, audit, permission,
or manifest drift fails closed.

Once the bundle passes both gates, native Agent solver generations receive the complete canonical
hard/soft constraints and assumptions plus a fingerprinted scoring contract. The contract exposes
the frozen objective and a bounded evaluator excerpt in the prompt; exact read-only
`scoring/objective.md` and `scoring/evaluator.py` copies are available in the isolated generation
workspace. This lets the solver align I/O, feasibility, and the actual higher-is-better score before
its first candidate. The authoritative evaluator stays in the parent bundle, and `probes.json`,
`audit.json`, `input-profile.json`, raw values, and machine paths are never copied into solver
workspaces.

Agent solvers may also return one bounded `experiment` beside candidate source: a short hypothesis,
change tags, and target metric directions. Lunar Evolution treats that declaration as intent, never as
proof. After independent evaluation it derives seed/improved/unchanged/regressed/invalid experiment
cards, score delta, and compatible metric deltas from the append-only archive. Later population
prompts receive up to eight recent cards plus bounded per-tag outcome counts. Resume
reconstructs the same memory without storing reasoning traces, mutable insight files, embeddings,
or another model call.

That verified memory now drives a deterministic prompt-only `search_directive` for every Agent
generation. An empty search explores; later parentless seeds diversify or repair the latest invalid
attempt; valid parents refine; and population parents with inspirations recombine. The directive
also separates change tags with measured improvements from repeatedly invalid, regressed, or
unchanged tags. It adds no planner call or scheduler state: candidate selection, budgets, and the
independent evaluator remain authoritative, and resume rebuilds the same directive from the archive.

The same bridge adds a compact contract-driven `algorithm_playbook`. Each supported problem type
has an ordered repository-owned repertoire of self-contained, standard-library-capable algorithm
families plus domain modeling and result-replay checks. Explore/diversify generations allocate
untried and then least-attempted families from independently evaluated experiment history;
repair/refine retain the selected candidate's family when known, while recombine exposes distinct
parent/inspiration families. The solver is asked to return the selected family tag with its bounded
experiment declaration, but execution and the evaluator—not that declaration—still determine the
outcome. No domain package, skill installation, or extra inference turn is required.

For native population search, those canonical family tags also form bounded quality-diversity
niches. Each island retains its best evaluator-valid candidate and, while capacity permits, one
valid elite from every distinct family before filling remaining slots with the existing
score/token-novelty order. Parent sampling uses family elites, and inspirations prefer valid
families different from the parent and from each other. Unknown or malformed tags receive no
protected slot, while untagged legacy archives retain the historical ranking fallback. Family is
therefore a search descriptor only: evaluator validity and score still own final-best selection.

## Small reference-benchmark effect trials

The available historical result for `reference-benchmark 1.10.6` is an AgentServer/company-platform
normal-Agent experiment, not a WebAgent or deep-evolution experiment. Its model/tool interactions
are turns inside one solution attempt. WebAgent deep evolution is activated separately by `/evolve`;
the checked-in source defaults to five outer iterations when no numeric budget is supplied.

For an affordable first effect milestone, build a deterministic public-only kit from one or two
local private case trees. When the owner has established that the selected historical and current
case contents are equivalent despite release-label changes, record that explicitly:

```bash
lunar-evolution effect-kit .lunar-evolution/reference-kit \
  --case supply_chain_inventory=/absolute/reference-benchmark/03_assignment/supply_chain_inventory \
  --owner-attested-content-equivalence --json
```

The generated `suite.json` derives its local publication, profile, CaseRevision, public ledger, and
harness identities from bytes. The generated `cases/<key>/` tree contains only `instruction.md`
and direct `data/*` inputs. No private source path, evaluator, extractor, ground truth, release
number, or raw data value is copied into the JSON provenance.

The archived local evaluation selected `glm-5.1` from existing WebAgent experiment records.
The GPT commands here illustrate the comparator workflow; its baseline cannot be relabeled for GLM.
Historical scores and their original configuration remain in the
[historical archive](docs/history-archive.md). These examples do not constitute a new measurement
or claim that an archived result was produced by the renamed implementation.

Save the matching comparator experiment-results response and convert those per-run results offline.
When the export carries adapter metadata, the converter requires consistent allowlisted evidence and
rejects unsupported or conflicting sources before writing a baseline. Adapter-free legacy exports
remain accepted only through the compatibility path. The
attestation flag labels content equivalence as owner-attested and forces formal ineligibility:

```bash
lunar-evolution effect-baseline results.json .lunar-evolution/reference-kit/suite.json baseline.json \
  --experiment-id EXPERIMENT_ID \
  --requested-model gpt-5.6-sol \
  --effective-model openai/gpt-5.6-sol \
  --model-evidence not_observable \
  --adapter-kind agentserver --baseline-source company-platform \
  --owner-attested-content-equivalence --json
```

Use the adapter identity observed in the export: `agentserver`, `company-platform`, or `webagent`.
The default remains `webagent` for compatibility and rejects explicit AgentServer evidence.

Before spending model or extractor credentials, run the read-only preflight. It rechecks the
selected suite, baseline, public projection, command executables, explicitly allowlisted
environment names, model-profile digest, and the exact Python environment used by the harness.
The dependency probe only checks import resolution and installed metadata; it does not run either
private script or call a model. Values of the named environment variables are never written to the
report:

```bash
lunar-evolution effect-preflight .lunar-evolution/reference-kit-real-001/suite.json \
  .lunar-evolution/reference-kit-real-001/baseline-agentserver.json \
  --case-source supply_chain_inventory=.lunar-evolution/reference-kit-real-001/cases/supply_chain_inventory \
  --subject-command "/absolute/lunar-evolution effect-subject --model gpt-5.6-sol --max-steps 100" \
  --subject-env LUNAR_EVOLUTION_MODEL_ENDPOINT --subject-env LUNAR_EVOLUTION_API_KEY \
  --harness-command "/absolute/lunar-evolution effect-harness --case-root /absolute/private-case --python /absolute/harness-venv/bin/python --extractor-env ANTHROPIC_AUTH_TOKEN --extractor-env ANTHROPIC_BASE_URL --extractor-env ANTHROPIC_MODEL" \
  --harness-env ANTHROPIC_AUTH_TOKEN --harness-env ANTHROPIC_BASE_URL --harness-env ANTHROPIC_MODEL \
  --harness-python /absolute/harness-venv/bin/python \
  --harness-import anyio --harness-import claude_agent_sdk \
  --harness-package claude-agent-sdk==0.1.81 \
  --requested-model gpt-5.6-sol \
  --output .lunar-evolution/effect-preflight-real-001.json --json
```

In this example, `baseline-agentserver.json` is an AgentServer/company-platform
historical projection created from an owner-provided export. It is suitable for descriptive comparison only and does not establish
WebAgent parity, suite parity, or statistical superiority. A matching WebAgent export must be
converted separately before making a WebAgent-specific comparison. The preflight report is
point-in-time evidence. `effect-trial` and `effect-deep-trial` still perform their own validation
when they start and do not treat a stale report as permission to run.
Generate a new kit at the example path when using the current adapter. Existing kits and historical
exports retain their original identities in the separate archive; moving them does not update
content identities or authorize a new comparison.

For a matching-model comparator trial, use the built-in adapters in normal mode:

```bash
lunar-evolution effect-trial .lunar-evolution/reference-kit/suite.json baseline.json \
  --case-source supply_chain_inventory=.lunar-evolution/reference-kit/cases/supply_chain_inventory \
  --subject-command "/absolute/lunar-evolution effect-subject --model gpt-5.6-sol --max-steps 100" \
  --subject-env LUNAR_EVOLUTION_MODEL_ENDPOINT --subject-env LUNAR_EVOLUTION_API_KEY \
  --harness-command "/absolute/lunar-evolution effect-harness --case-root /absolute/private-case --extractor-env ANTHROPIC_AUTH_TOKEN --extractor-env ANTHROPIC_BASE_URL" \
  --harness-env ANTHROPIC_AUTH_TOKEN --harness-env ANTHROPIC_BASE_URL \
  --requested-model gpt-5.6-sol \
  --runs-per-case 3 --timeout 3600 \
  --workspace .lunar-evolution/effect-trial-001 --json
```

For macOS runs, both `effect-trial` and `effect-deep-trial` optionally accept
`--keep-awake-report /absolute/new-host-session.jsonl`. This verifies a process-owned assertion
against idle system sleep before loading trial configuration or credentials, holds it through the
existing trial call, and releases it on normal or exceptional exit. The report must be fresh, have an
existing parent without symlink components, and be outside the workspace and all case sources,
including on resume. Unsupported hosts or failed acquisition reject before trial dispatch.
Without this option execution is unchanged. Python supervisors may use
`from lunar_evolution.host_session import host_execution` and `with host_execution(report_path): ...`.

The bounded host journal records assertion checks, cleanup, and wall/monotonic clock observations.
Its work outcome distinguishes a returned call from an exception; native receipts and scores
remain authoritative. It does not change timeouts or prevent lid-close, manual or low-battery
sleep. Clock divergence is not an exact sleep duration, and partial journals do not prove cleanup.
See [Feature 083](specs/083-host-execution-guard/quickstart.md) for the lifecycle and local checks.

The suite freezes the benchmark publication, evaluation profile, CaseRevision, public-file ledger,
and extractor/evaluator digests. The baseline contains individual comparator results; Lunar Evolution derives
the historical best locally and does not accept a manually entered target score. Only the separate
harness command may provide validity and score. A case milestone is achieved when all planned
Lunar Evolution runs finish, model identities match, and at least one evaluator-valid Lunar Evolution score is strictly
higher than that case's evaluator-valid baseline historical best. This is a single-case
breakthrough—not whole-suite parity or statistical superiority. Use `--resume` with the same
options to preserve completed logical runs after an interruption. Subject/harness separation is a
bounded request and filesystem-layout contract, not an OS sandbox; use an owner-provided sandbox
for an untrusted same-user command. Lunar Evolution rechecks frozen controls, public sources, and run records
before writing a successful report. Only logical records whose digests are already registered in
runner-owned state are reused; an unregistered record is independently rescored in a new attempt.
The built-in subject is a fresh attempt-local Agent loop with
no memory or transcript reuse. The harness recomputes the external reference benchmark's canonical CaseRevision content
digest, matches its public projection, hashes `tests/extractor_agent.py` and
`tests/evaluator.py`, runs each stage once, and starts the evaluator without inherited
model/extractor credentials. Lunar Evolution does not download historical publications or authenticate to
the external reference benchmark; those remain explicit owner-controlled local inputs. A content-equivalence attestation is
reported as `descriptive_owner_attested_content_equivalent`, never as cryptographic proof of an
identical official publication or as a statistically powered superiority conclusion.

To measure the outer evolution effect separately, use the deep protocol. It defaults to five outer
rounds, matching the checked-in WebAgent `/evolve` source default when no numeric argument is given:

```bash
lunar-evolution effect-deep-trial .lunar-evolution/reference-kit/suite.json baseline.json \
  --case-source supply_chain_inventory=.lunar-evolution/reference-kit/cases/supply_chain_inventory \
  --subject-command "/absolute/lunar-evolution effect-subject --model gpt-5.6-sol --max-steps 100" \
  --subject-env LUNAR_EVOLUTION_MODEL_ENDPOINT --subject-env LUNAR_EVOLUTION_API_KEY \
  --harness-command "/absolute/lunar-evolution effect-harness --case-root /absolute/private-case" \
  --harness-env ANTHROPIC_AUTH_TOKEN --harness-env ANTHROPIC_BASE_URL \
  --requested-model gpt-5.6-sol --runs-per-case 2 \
  --workspace .lunar-evolution/deep-effect-trial-001 --json
```

Rounds within one attempt share a subject workspace, and every round starts a fresh subject process.
The next round receives only the previous round's bounded `RoundFeedback` projection: finite
scores, generic allowlisted metrics, a hash-only candidate manifest, a best-round pointer, and a
repair/stagnation directive. It does not receive baseline rows, private harness files, raw process
output, or credentials. Set `--stagnation-rounds` to control the bounded non-improvement window
(default `2`). The exact harness runs after every round, and the report records the best round,
P50/P90 score and quality distributions, the round-best curve, and safe feedback directives. This
is an effect-layer comparison, not WebAgent prompt identity, full-suite parity, or a statistically
powered superiority result. Use `--resume` with the same options after an interruption. The
`effect-trial` command remains the normal-mode baseline and follows the same state-registered
logical-record authority rule.

Resume re-reads every recorded subject telemetry field and harness metric, and verifies recorded
request digests. A clean incomplete prefix continues in the same attempt; process or boundary
failures restart in a new attempt while preserving earlier evidence. Reusing an unrecorded subject
round requires a matching request-bound receipt, while any unrecorded harness result is discarded
and rescored by the exact private harness. An unregistered logical-run record is also rescored in a
new attempt. A verified previous-record journal covers interruption between record and state
replacement by restoring the last state-authorized prefix. Legacy completed records remain readable,
but an old workspace cannot retroactively prove that pre-hardening code did not register a
subject-preseeded record; rerun it when the stronger integrity guarantee is required.

Each case report also includes bounded `failure_statistics`: failed logical-run error codes,
round-level feedback categories, recorded/completed round counts, timeout totals, and a fixed
per-round ledger (including empty rounds). These counters are operational projections of validated
receipts; they do not create scores or change the private harness's score authority.

Failed built-in subjects can also leave a score-free diagnostic sidecar: `receipt.failure.json`
in normal mode or `receipts/001.failure.json` for a deep round. The runner validates its original
request identity and copies the fixed-field projection into the attempt's `diagnostics/` directory.
It records a bounded stage/error code, observed model/tool counters and optional numeric HTTP
status; raw process output, exception text, tool content and credentials remain discarded. Missing
or invalid diagnostics preserve the original process failure. These optional subject claims cannot
authorize a score, successful receipt, or resume. The entire public `case/` tree is read-only;
solver scripts and outputs belong elsewhere in the subject workspace. See
[Feature 061](specs/061-subject-failure-diagnostics/spec.md).

Typed profile budget failures use diagnostic version 2, with the token/cost limit, configured
maximum, exceeded/exhausted state, and separate accepted and observed usage snapshots. An exceeded
response appears only in observed usage; an exact-ceiling tool response is already accepted but
cannot execute tools. Both snapshots describe partial reported usage, never complete failed-run
consumption or provider billing; cost uses the configured profile prices. Numbers outside the
diagnostic cap (10^15, or 10^6 rounds) become null at the maximum/snapshot boundary, without changing
budget enforcement. Version 1 remains readable and is still used when richer typed evidence is unavailable. Historical
diagnostics, successful receipts and report usage are not backfilled. See
[Feature 066](specs/066-budget-failure-evidence/spec.md).

Typed model failures retain their original error code and add a fixed reason and observed response
status in version 3. Version 4 also reports the failed request's local phase, elapsed milliseconds
and actual timeout argument. The phases distinguish opening the response, reading its body,
validating it and handling an HTTP error body. Opening includes connection and response acquisition;
it does not identify a server or network root cause. Invalid timing falls back to version 3, and
versions 1–3 remain readable. See [Feature 079](specs/079-model-failure-evidence/spec.md) and
[Feature 080](specs/080-model-request-timing/spec.md).

Version 5 additionally retains the bounded worker's last local milestone, HTTP exchange index and
elapsed milliseconds from transport start. This can distinguish connect, request-write and header
progress, including redirect hops, while preserving the coarse phase and final status. Invalid or
missing detail falls back to the existing projection; versions1–4 remain readable. Local writes
returning do not establish remote receipt or execution. See
[Feature 122](specs/122-transport-milestone-observation/spec.md).

These observations describe only a request that propagated a typed failure. They do not log a live
request, survive an outer process kill, recover failed-request usage or change retries and scoring.
Milliseconds are rounded down; a positive timeout below one millisecond appears as zero, while
null means no explicit timeout. The recorded timeout is the caller's request limit, and elapsed
time includes necessary cleanup.

On POSIX macOS/Linux, finite HTTP timeouts now use one absolute transport deadline, including worker
startup, request/response pipes, DNS, connection and body reads. An isolated standard-library worker
performs the HTTP exchange; the caller terminates and reaps it before returning on timeout. A
lifeline pipe also ends the worker if its parent dies. Each call owns its worker, and no request is
retried or late response accepted. Finite limits must be positive numbers at most 86400 seconds.

The worker adds process startup overhead. Endpoint, credentials and narrowly projected proxy/TLS
settings travel through anonymous pipes; the worker inherits neither the full caller environment
nor a custom in-memory urllib opener. Environment NO_PROXY and SSL_CERT_FILE/SSL_CERT_DIR remain
supported, along with the standard library's default HTTPS negotiation. With timeout=None the
original direct urllib path remains, including its lack of an absolute transport deadline.
Parent-side JSON/model parsing and OS cleanup are not a hard realtime whole-function deadline,
and disconnecting cannot guarantee a remote server stops processing or billing.
See [Feature 081](specs/081-http-transport-deadline/spec.md).

The generated evaluator is explicit local executable authority, not a claim of OS sandboxing. It
runs with isolated Python, closed stdin, minimal non-secret environment, timeout, and bounded
output. Its exact source is visible to compiled-evaluator solvers as read-only scoring guidance,
while compiler/audit probes remain private; the authoritative copy is independently reverified and
executed outside solver generation workspaces. Use `--evaluator-command` when an owner-reviewed
domain harness already exists; the two modes are intentionally mutually exclusive.

Provide real local data explicitly with repeatable `--input` options. A source is staged into the
run's `data/raw/` directory and copied into each isolated task attempt; use `SOURCE=DEST` when the
destination must match a contract path:

```bash
lunar-evolution solve "根据订单数据设计配送路线" \
  --input ./orders.csv \
  --input ./vehicles.json=vehicles.json \
  --runtime openai-compatible --agent-loop --json --home .lunar-evolution
```

Inputs are recorded as `kind=input_data` with size and SHA-256 metadata. The source machine path is
never persisted, and resuming with the same bytes is idempotent. Algorithm roles read the verified
copies from `data/raw/...` in their own attempt workspace, just as they write outputs under their
private `output/` directory.

When a one-shot OpenAI-compatible model cannot call file tools, a structured task may return a
bounded JSON artifact envelope instead of writing directly:

```json
{"text":"Route table generated.","artifacts":[{"path":"output/routes.csv","content":"order_id,route_id\n1,r1\n"}]}
```

The runtime writes only these relative UTF-8 files into the private attempt workspace. The same
`OutputSpec`/role acceptance, hashing, retry, and delivery checks still apply; tool calls remain
available through the explicit `--agent-loop` option.

For a more explicit specialist workflow, add `--role-dag`:

```bash
lunar-evolution solve "根据订单数据设计配送路线" --runtime mock --role-dag --json --home .lunar-evolution
```

This uses `data_discovery → problem_formulator → solver → evaluator → reviewer`. It is still the
same local SQLite run and artifact handoff; the switch only selects a richer built-in plan factory.
Each non-Solver role also has a strict hand-off contract: DataDiscovery must write
`data/processed/data-profile.json`, ProblemFormulator must write
`solve/problem-formulation.md`, Evaluator must write a schema-valid `evaluate/evaluation.json`, and
Reviewer must write `evaluate/review.md`. These files are hashed as `role_evidence` artifacts;
missing or malformed evidence causes a retry/failure even when the model returns convincing prose.

### Conversation versus result data

An algorithm mission has two deliberately separate result channels:

1. `result.txt` and role reports preserve the conversational explanation and evidence trail.
2. `algorithm_problem.outputs` declares machine-consumable files that the Solver must actually
   write. Supported formats are JSON, JSONL, CSV, and non-empty UTF-8 text; declared fields are
   checked independently of the Solver's prose.

The Solver writes logical paths such as `output/routes.csv` in its private attempt workspace. Only
after independent evaluation passes does Lunar Evolution copy the file to the stable run workspace,
`<run-workspace>/output/routes.csv`, hash it, and record it as `kind=output`. This means a parent
Agent can consume data deterministically:

```bash
lunar-evolution status <run-id> --json   # algorithm_outputs + SHA-256 metadata
lunar-evolution deliver <run-id> --json  # fail-closed delivery decision
```

Role-DAG evidence is available through the same `status --json` response under `role_evidence` and
is included in delivery evidence. It remains attempt-local, so only validated Solver data files
are promoted to the stable `output/` directory.

If a required output is missing or malformed, a convincing chat response cannot make the run
succeed. Contracts written before the optional `outputs` field remain fully compatible and keep
the existing result/runtime delivery behavior.

Declared outputs are mandatory even when a custom task acceptance expression uses `any`. For
example, a matching “solver completed” text branch cannot waive missing CSV fields. An optional
output may be absent, but a present invalid file, directory, symlink or obstructed parent path
fails the same independent checks. Ordinary and delegated Solvers, contract candidate execution
and final evolved-output materialization share this validator. Failed checks feed the existing
repair/retry flow, and only passing outputs are promoted for delivery. See
[Feature 060](specs/060-mandatory-output-validation/spec.md).

## Bootstrap

Python 3.11 or newer is required. Clone the repository and run the installation commands from its root:

```bash
git clone https://github.com/vchive/Lunar-Evolution.git
cd Lunar-Evolution
```

Using [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

Using Python's standard environment tooling:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the standalone mock agent

```bash
uv run lunar-evolution run "Create a durable local run report" --runtime mock
uv run lunar-evolution status <run-id>
uv run lunar-evolution events <run-id>
uv run lunar-evolution resume <run-id>
```

The distribution and sole console command are named `lunar-evolution`. The Python package is
`lunar_evolution`; `python -m lunar_evolution` invokes the same CLI. After activating the installed
environment, either invocation works outside the repository without setting `PYTHONPATH`.

The default home is `.lunar-evolution/` in the current working directory. Set `LUNAR_EVOLUTION_HOME` or pass
`--home PATH` to use another local directory; `--home` takes precedence over the environment variable.
The mock runtime is deterministic and requires no network, credentials, model, or user-global Hermes state.

Feature [145](specs/145-lunar-evolution-identity/spec.md) changes the package, command, user-configuration
variables and versioned product identities together. No predecessor command or configuration aliases
are installed. Existing state and sealed measurement records are retained separately; renaming does
not migrate their bytes, make their hashes equivalent, or establish that an old run can resume.
The [historical archive](docs/history-archive.md) records the fixed revision and integrity index.
Historical model results describe that archived implementation, not a new result for this namespace.

## Explicit external runtime

An external agent can be used only when explicitly configured:

```bash
export LUNAR_EVOLUTION_RUNTIME_COMMAND='my-agent --json'
uv run lunar-evolution run "Inspect this repository" --runtime subprocess
```

The command receives the task prompt on stdin and runs inside the task workspace. Lunar Evolution never
searches for Hermes or imports `~/.hermes`.

## Explicit Agent delegation

Lunar Evolution can also act as a local control plane for another CLI/TUI Agent. The worker is supplied
explicitly; no Hermes, OpenCode, OpenClaw, or Codex installation is discovered or required:

```bash
lunar-evolution delegate "inspect the repository and write an answer" \
  --agent-command "/absolute/path/to/agent-wrapper --json" \
  --agent-name my-worker --agent-role solver \
  --capability read_files --capability write_artifacts --json
```

The command receives one JSON request on stdin and returns one JSON object (or bounded plain text)
on stdout. The request includes the durable `run_id`, `task_id`, role, required capabilities,
attempt workspace, and timeout. A structured response can declare `text`, run-relative `artifacts`,
`metadata`, and `status`. Lunar Evolution verifies and SHA-256 hashes those artifacts, evaluates the
text, and remains the only component allowed to settle the SQLite task/run. Absolute executable
paths, timeouts, malformed output, non-zero exits, and workspace escapes fail closed.

For a long delegation, add `--detach`; the command returns a durable run ID and a local child keeps
working. Re-enter it later with the same explicit worker command:

```bash
lunar-evolution delegate --run-id <run-id> \
  --agent-command "/absolute/path/to/agent-wrapper --json" \
  --agent-role solver --json
```

This makes the same project usable in three ways: directly as a standalone Agent, as a child called
by Codex/Hermes/OpenClaw, or as the controller that delegates a role to one of those tools. The
library equivalents are `AgentRequest`, `AgentResult`, `AgentRegistry`, `RuntimeAgentAdapter`, and
`CommandAgentAdapter` from `lunar_evolution.agents`.

The separate typed `WorkerService` API provides persistent worker sessions with
`dispatch/send/list/wait/resume/cancel`, independent execution instances, owned process cleanup
and explicit recovery. See the [local worker quickstart](specs/143-local-worker-lifecycle/quickstart.md).
Runtime and custom adapters require fresh-instance factories for these concurrent sessions.
`send` queues input for explicit `resume`. CLI delegation and model-facing worker tools have not
yet migrated to this API.

## Continuous Hermes-inspired model session

Lunar Evolution includes a dependency-free OpenAI-compatible HTTP adapter and a bounded continuous
tool-calling loop. Point it at a local Ollama, vLLM, LM Studio, or other compatible server:

```bash
export LUNAR_EVOLUTION_MODEL_ENDPOINT='http://127.0.0.1:11434/v1/chat/completions'
export LUNAR_EVOLUTION_MODEL='your-local-model'
lunar-evolution run "Inspect this repository" --runtime openai-compatible --agent-loop --json
```

You can pass `--endpoint` and `--model` instead of environment variables. Hosted endpoints may use
`LUNAR_EVOLUTION_API_KEY` (or `--api-key`); the key is sent only as an Authorization header and is redacted
from persisted errors. The adapter accepts the standard OpenAI response shape plus Ollama-style
responses, and all normal retries, evaluator checks, artifacts, and recovery remain owned by the
local controller. Add `--allow-exec` to expose bounded no-shell command execution:

```bash
lunar-evolution run "Run the tests and fix the failing file" \
  --runtime openai-compatible --agent-loop --allow-exec --max-steps 40
```

The controller remains the orchestrator: it validates and schedules optional dependency plans,
retries failed attempts, hands verified artifacts to dependent tasks, and recovers after an
interruption. It is not a WebAgent stage machine.

For plans with independent tasks, local workers can overlap without sharing runtime session state:

```bash
lunar-evolution run --plan plan.json --runtime mock --workers 2 --json
lunar-evolution resume <run-id> --runtime mock --workers 2 --json
```

The default is one worker, preserving serial behavior. `--workers N` is a local bounded thread
pool; the CLI creates a fresh repository-owned runtime adapter per task, while SQLite remains the
claim and dependency-ordering authority. Cancellation fans out to all active adapters, and late
results are discarded by the same durable rules as serial execution. No Hermes/OpenCode/Codex
installation or remote queue is required.

### Master policy and versioned plans

The local Master layer carries over WebAgent's highest-value effect-layer behavior without its
service plane. It chooses the smallest useful action, stores an auditable plan revision, and keeps
patch/replan and delivery decisions in SQLite:

```bash
lunar-evolution decide "What does SQLite WAL mode provide?" --json
lunar-evolution plan plan.json --runtime mock --json
lunar-evolution plan <run-id> --json                 # inspect current revision
lunar-evolution patch <run-id> patch.json --json
lunar-evolution replan <run-id> replacement.json --json
lunar-evolution resume <run-id> --runtime mock --json # execute newly opened tasks
lunar-evolution deliver <run-id> --json
```

`plan` creation is atomic with the run and task DAG. Each revision has a parent version and remains
immutable. A stale patch is rejected before any write; completed task definitions cannot be
rewritten, while failed or superseded work can be reopened and resumed. `deliver` fails closed
unless the run passed independent evaluation and has hashed result/runtime artifacts; an
algorithm-output contract additionally requires every required `kind=output` artifact. All command
outputs support `--json`, making the CLI suitable for Codex, OpenClaw, Hermes, or another local
parent agent.

### Domain routing, profiles, and execution budgets

Every executable run receives a deterministic local route: `general`, `data`, `research`, or
`coding`. The selected Solver/Evaluator profile, matching evidence, and execution budget are stored
with the run and returned by `status --json`; no provider call or machine-wide Agent installation is
needed to choose them.

```bash
lunar-evolution run "Analyze a CSV and write a report" --runtime mock --json
lunar-evolution status <run-id> --json
```

Budgets fail closed: they bound scheduler task count, total attempts, session tool calls, controller
elapsed time, and indexed artifact bytes. A breach writes a `budget_exceeded` ledger event and makes
the run ineligible for `deliver`, without discarding prior artifacts. `PlanDocument` accepts an
optional `budget` object with `max_tasks`, `max_attempts`, `max_tool_steps`,
`max_runtime_seconds`, and `max_artifact_bytes`.

### Algorithm problem contracts (Feature 012)

For algorithmic work, a plan may carry an `algorithm_problem` contract. It records the problem type,
input schema, decision variables or prediction target, objective direction, provenance-backed hard
and soft constraints, success criteria, deliverables, and explicit assumptions. The contract is
validated before the run starts and is visible in both `plan` and `status --json`.

Contract-bearing runs reserve a local role workspace:

```text
data/raw/ · data/processed/ · solve/ · evaluate/ · output/ · evolution/
```

`algorithm-workspace.json` contains the plan revision and a SHA-256 digest of the canonical
contract. The directories are a boundary for Solver/Evaluator roles. The local evolution library
now consumes this contract without starting a remote service or importing a machine-wide Agent.

An algorithm mission can declare concrete data outputs instead of relying on prose deliverables
alone:

```json
{
  "outputs": [
    {"path": "output/routes.csv", "format": "csv", "fields": ["item_id", "route_id"]},
    {"path": "output/summary.json", "format": "json", "fields": ["total_distance"]}
  ]
}
```

Required outputs are independently checked after the Solver runtime returns. JSON/JSONL records are
parsed, CSV headers are checked, declared fields must exist, and text outputs must be non-empty.
Passing only a conversational completion claim is insufficient: after the checks pass, files are
promoted from the attempt workspace to the run-level `output/` directory, SHA-256-indexed as
`kind=output`, exposed under `algorithm_outputs` in `status --json`, and included by `deliver`. The
`outputs` field is optional, so older contracts remain compatible.

New contracts use `population` by default and may select `openevolve` as an optional explicit local
subprocess. The historical evolution strategy value `loop` remains parseable in old contracts,
archives, results, and sealed effect-trial evidence, but it cannot start or resume a new evolution
iteration. `LoopStrategy` remains importable as a non-mutating compatibility stub whose active
methods raise `loop_strategy_retired`. The current local `--workers` option only parallelizes
independent DAG tasks; it is not population search.

The retired strategy name is separate from `AgentLoopRuntime`, `--agent-loop`, and
`--agent-runtime-loop`. Those options still wrap one model invocation in Lunar Evolution's bounded
tool-capable runtime; they do not select the evolution algorithm.

### Local evolution strategies

The strategy seam is available as a library so a standalone caller or another Agent can supply its
own solver/generator and evaluator:

```python
from lunar_evolution import CandidateDraft, EvolutionConfig, EvolutionContext, build_strategy

context = EvolutionContext(
    contract=contract,
    workspace=run_workspace,
    generate=lambda request: CandidateDraft("def solve():\\n    return 1\\n"),
    evaluate=lambda path, contract: report,
    config=EvolutionConfig(strategy="population", max_rounds=5),
)
result = build_strategy(context).run()
```

`population` maintains a bounded active set plus the complete archive and can use local islands and
ring migration. Its generic `evolve` path can optionally initialize from the verified-seed admission
defined by [`specs/084-verified-seed-handoff/`](specs/084-verified-seed-handoff/); when a manifest is
supplied, an empty admitted subset fails before generation or population mutation. Without a
manifest, population retains native generator initialization. `openevolve` is opt-in and requires
an explicit absolute executable plus a local evaluator command; the base installation does not
install or discover OpenEvolve. Historical behavior is documented under
[`specs/013-evolution-strategies/`](specs/013-evolution-strategies/), while the active migration is
defined by [`specs/085-population-first-evolution/`](specs/085-population-first-evolution/).

The same boundary is available through the standalone CLI.  Native strategies require explicit
local generator/evaluator commands; their first argument is a run-scoped request or candidate path
respectively:

```bash
lunar-evolution evolve contract.json \
  --strategy population \
  --generator-command "/absolute/python /absolute/generator.py" \
  --evaluator-command "/absolute/python /absolute/evaluator.py" \
  --json --home .lunar-evolution
```

The command creates a normal SQLite-backed run and returns `run_id`, candidate counts, the best
candidate, and the canonical workspace.  Use `--detach` for a durable child process, then resume
with the same contract and explicit commands:

```bash
lunar-evolution evolve contract.json \
  --strategy population --population-size 8 --detach \
  --generator-command "/absolute/python /absolute/generator.py" \
  --evaluator-command "/absolute/python /absolute/evaluator.py" \
  --json --home .lunar-evolution
lunar-evolution evolve contract.json --resume --run-id <run-id> \
  --generator-command "/absolute/python /absolute/generator.py" \
  --evaluator-command "/absolute/python /absolute/evaluator.py" \
  --json --home .lunar-evolution
```

The generic `evolve` command can optionally import an already produced population seed manifest.
This path is population-only and requires the caller's current dependency and environment identity:

```bash
lunar-evolution evolve contract.json \
  --strategy population \
  --seed-manifest "/absolute/path/to/seed-manifest.json" \
  --seed-dependency-sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --seed-environment-sha256 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --generator-command "/absolute/python /absolute/generator.py" \
  --evaluator-command "/absolute/python /absolute/local-exact-evaluator.py" \
  --json --home .lunar-evolution
```

The manifest's contract digest must match `contract.json`; its `evaluator_kind=exact_harness` and
evaluator fingerprint must match the explicit local evaluator command; and its
dependency/environment digests must match the two explicit flags. The digest flags are invalid
without `--seed-manifest`. Omitting all three seed options preserves the generic evolution path
without an imported manifest. The staged Master→Build path and benchmark do not infer or attach a
seed manifest. Resuming a seeded run requires the same manifest, dependency/environment digests,
and exact evaluator command so Lunar Evolution can repeat admission and reject changed material or
identity before population mutation. The stable `seed-*` identity binds both evaluator kind and
fingerprint. For an external seed, Lunar Evolution converts both producer evidence and seed metadata to
the fixed digest-only summary `{present, score_present, payload_sha256}` before they enter canonical
state; raw external scores, payloads, and prose are not archived.

OpenEvolve output is untrusted candidate material. Even when its result envelope contains an
external score, Lunar Evolution admits and ranks the candidate only after the explicit local evaluator
returns a matching receipt:

```bash
lunar-evolution evolve contract.json \
  --strategy openevolve \
  --openevolve-command "/absolute/path/to/openevolve-wrapper" \
  --evaluator-command "/absolute/path/to/local-exact-evaluator" \
  --json --home .lunar-evolution
```

The wrapper runs in a private mode-0700 system temporary directory and receives only a bounded
contract/budget configuration whose workspace points back to that directory. Its stdout and stderr
are discarded. After local evaluation succeeds, Lunar Evolution atomically publishes a stable
`seed-*` candidate with `strategy=openevolve`, `iteration=1`, and a matching receipt; the producer
workspace is removed. Resuming an already completed run verifies canonical source, provenance,
configuration, and receipt, invokes the current local evaluator again, and does not rerun the
producer.

Command-backed runs persist credential-safe SHA-256 fingerprints for both the generator/solver and
evaluator adapter profiles. Resume rejects a changed command, Agent name, role, or required
capability before claiming the task, so one candidate archive is never silently mixed across
different execution configurations. Raw command arguments are not written to strategy state.

For algorithm work that must prove a candidate actually runs, add an execution command. The runner
receives the candidate path, runs in that candidate's attempt directory, and produces bounded
`execution.json` evidence before the evaluator command is called:

```bash
lunar-evolution evolve contract.json --strategy population \
  --generator-command "/absolute/path/to/generator" \
  --candidate-runner-command "/absolute/path/to/run-candidate" \
  --evaluator-command "/absolute/path/to/evaluate-candidate" \
  --json --home .lunar-evolution
```

The evaluator keeps its existing candidate-path argument and can read the sibling
`execution.json`. A runner timeout, non-zero exit, oversized output, or path violation becomes an
invalid report before the evaluator is invoked and can never replace the best candidate. The
evidence file is indexed and hashed by the local ledger. The runner remains opt-in on this low-level
command, so historical command-only and Agent-backed evolution remains compatible.

### Repository-owned runtime evolution

Native evolution can use Lunar Evolution's own runtime as the solver, evaluator, or both. This is the
standalone path: it does not import or discover a machine-wide Hermes, OpenCode, Codex, Claude Code,
or DeepSeek Harness installation. The runtime profile is explicit and is adapted through the same
strict `AgentCandidateGenerator` / `AgentCandidateEvaluator` bridges as external workers:

```bash
# A local runtime command can produce candidate source for solver prompts and
# a strict EvaluationReport JSON object for evaluator prompts.
lunar-evolution evolve contract.json --strategy population \
  --agent-runtime subprocess \
  --agent-runtime-command "/absolute/path/to/local-agent --json" \
  --json --home .lunar-evolution

# Or call an OpenAI-compatible local server directly.
lunar-evolution evolve contract.json --strategy population \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint "http://127.0.0.1:11434/v1/chat/completions" \
  --agent-runtime-model "your-local-model" \
  --json --home .lunar-evolution
```

The available profiles are `mock`, `subprocess`, and `openai-compatible`. A runtime fills either
or both unconfigured roles, so an explicit `--evaluator-command` (or Agent evaluator) can be paired
with a runtime-backed solver, and vice versa. `--agent-runtime` cannot be combined with
`openevolve`, and supplying it when both roles are already explicit is rejected as ambiguous.
Each role gets a fresh runtime adapter, while the SQLite ledger and candidate archive remain the
durable authority. Runtime kind, endpoint/model, command identity, role, and capabilities are
stored only as credential-safe fingerprints. Detached runs pass non-secret settings as arguments
and an API key through `LUNAR_EVOLUTION_AGENT_RUNTIME_API_KEY`, never through argv or state.

For an OpenAI-compatible local model that needs to inspect a candidate, edit files, or run tests
before returning, keep the population strategy and opt into the bounded repository-owned runtime
loop:

```bash
lunar-evolution evolve contract.json --strategy population \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint http://127.0.0.1:11434/v1/chat/completions \
  --agent-runtime-model your-local-model \
  --agent-runtime-loop --agent-runtime-session-history \
  --agent-runtime-allow-exec --agent-runtime-max-steps 40 \
  --json --home .lunar-evolution
```

`--agent-runtime-loop` wraps each runtime invocation with the same confined `read_file`,
`write_file`, `list_dir`, and optional no-shell `run_command` tools used by normal Lunar Evolution
sessions. Each solver and evaluator role receives a fresh runtime and tool registry. The runtime
loop is bounded to at most 200 tool calls, and memory, transcripts, and command execution are all
explicit opt-ins. It does not reactivate the retired evolution strategy. Its text still crosses the
strict candidate/evaluation bridges, so a model cannot claim validity or bypass the evaluator.

### Reproducible strategy benchmark

Use `benchmark` to reproduce population search with a fixed contract, command-backed generator and
evaluator, and bounded budget. With no `--strategy`, the benchmark runs only `population` in a fresh
workspace and archive:

```bash
lunar-evolution benchmark contract.json \
  --generator-command "/absolute/path/to/generator" \
  --evaluator-command "/absolute/path/to/evaluator" \
  --max-rounds 3 --population-size 4 --seed 7 \
  --json --home .lunar-evolution
```

The JSON report contains per-strategy status, elapsed time, candidate counts, best score, and
relative archive paths. Generator/evaluator identities are stored as SHA-256 fingerprints; raw
commands and model credentials are not included. To compare the native population with the explicit
OpenEvolve adapter, select both and retain the local evaluator command:

```bash
lunar-evolution benchmark contract.json \
  --strategy population --strategy openevolve \
  --generator-command "/absolute/path/to/generator" \
  --openevolve-command "/absolute/path/to/openevolve-wrapper" \
  --evaluator-command "/absolute/path/to/local-exact-evaluator" \
  --max-rounds 3 --population-size 4 --seed 7 \
  --json --home .lunar-evolution
```

The wrapper receives a generated config and writes bounded candidate material. Its evaluation is
external provenance only; the displayed comparison score comes from the explicit local evaluator.
OpenEvolve remains an opt-in subprocess and is never installed or discovered by Lunar Evolution.

ShinkaEvolve and other program-search runners can use the same transport-free producer envelope
before a service adapter exists. The public `ProducerResultEnvelope` / `ProducerMaterial` API accepts
only a terminal status, producer identity, bounded budget, lineage, and already-written candidate
files with size and SHA-256; `admit_producer_result(...)` verifies those bytes and converts the
batch to one verified-seed manifest. Lunar Evolution assigns islands and identities only after the full batch
has passed the local exact evaluator. Producer metrics such as `combined_score`, `correct`, or
feedback are reduced to `{present, score_present, payload_sha256}` and cannot become Lunar Evolution scores.

Feature [150](specs/150-producer-bundle-bridge/) adds an explicit, provider-free grouping bridge for
producer outputs that contain several files per candidate. `BundleGroup` names the bundle ID,
entrypoint, and already-declared `candidate_source` paths; the bridge reuses the canonical source
bundle verifier and returns only a read-only verified bundle plus producer provenance. It never
guesses grouping from directories, lineage, ordering, or producer scores. This is a preparation
boundary only: it does not launch OpenEvolve/Shinka, import a population, evaluate a candidate, or
claim a real producer campaign result. Feature [151](specs/151-producer-bundle-population/) now
projects those verified groups into native multi-file `CandidateDraft` values, preserving the
entrypoint, source files, and provenance-only metadata without writing or evaluating anything.
Feature [152](specs/152-producer-bundle-admission-descriptor/) binds the drafts to local authority.
Feature [153](specs/153-producer-bundle-publication-transaction/quickstart.md) now connects imported
Shinka SQLite material to non-publishing native local evaluation, retained prepared intent and
receipts, and atomic stage/commit of the admitted subset. The transaction checks archive integrity
and active population read-back; offline coverage also verifies native resume and delivery through
the existing delivery APIs. Entry is limited to an initialized iteration-zero running population
with no offspring history, seed admission, or prior producer admission. The transaction supports
a caller-owned active deadline/cancellation control, durable all-rejected terminal journaling
with exact no-evaluation retry, and bounded publication-lock waiting. Cross-process deadline
restoration, full unknown/interruption recovery, and the external launcher/scheduler/remote
campaign connection remain open.

For a native Shinka result directory, `lunar_evolution.export_shinka_result(...)` is a read-only, offline
exporter. It opens `programs.sqlite` (with an explicit legacy `evolution_db.sqlite` fallback) in
immutable read-only mode when the database is quiescent (live `-wal`/`-shm`/rollback-journal
sidecars are rejected), and writes a fresh envelope plus bounded candidate copies under the
requested export root. The export-root leaf must be a new path, its existing parent must be a
regular directory without arbitrary symlink components, and a failed commit can report an
unknown parent-directory durability state after the complete tree becomes visible. Pass
`program_ids=[...]` to select an explicit ordered set and leave `top_k` omitted; this can include
rows that Shinka marked incorrect so Lunar Evolution can make the authoritative decision. If IDs are omitted, `top_k`
defaults to one convenience row and otherwise selects rows with `correct = 1`, ordered
deterministically by the producer's `combined_score`, generation, and ID. The exporter prefers
`gen_<generation>/main.<ext>` and uses `best/main.<ext>` only when that generation file is absent,
after checking exact UTF-8 bytes against the database row. The export can feed
`admit_producer_result(export_root, ...)` for the existing seed route, or explicit bundle grouping,
draft preparation and the Feature 153 Python transaction above. Shinka scores, correctness, metrics,
and SQLite/generation metadata remain bounded external evidence and never become Lunar Evolution
iteration, score, or rank authority. The exporter does not launch ShinkaEvolve, a model, a scheduler,
or a remote backend.

Feature [096](specs/096-producer-cli-warm-start/) exposes the existing seed warm-start route through
the CLI; the Feature 153 native bundle transaction has a separate Python integration entry point:

```bash
lunar-evolution export-shinka-result ./shinka-run --output ./shinka-export \
  --contract contract.json --producer-fingerprint "$SHINKA_FINGERPRINT" \
  --program-id program-1 --json

lunar-evolution evolve contract.json --producer-result ./shinka-export \
  --producer-fingerprint "$SHINKA_FINGERPRINT" --producer-id shinka \
  --generator-command "/absolute/path/to/generator" \
  --evaluator-command "/absolute/path/to/local-exact-evaluator" \
  --population-size 4 --json --home .lunar-evolution
```

`SHINKA_FINGERPRINT` is your pinned producer version/configuration SHA-256. Export copies material
without initializing a Lunar Evolution run or executing a producer. Use repeated `--program-id` values for
ordered selection, or `--top-k N` for producer-score selection (default one); export success does
not mean the candidate passed Lunar Evolution evaluation. `evolve --producer-result` prepares an unadmitted
manifest and sends it through the same local exact evaluator and seed receipt path as
`--seed-manifest`. It accepts any compatible completed producer export directory. Source-bundle
dependency and declared-protocol environment digests are derived by the existing adapter; explicit
seed dependency/environment overrides and `--seed-manifest` cannot be combined with this option.
The producer pin and local evaluator command are required; `--producer-id` is an optional name pin.

For resume, retain the export directory and pass the same flags with `--resume --run-id ID`; the
local evaluator runs fresh while seed identities remain stable. `--detach` forwards these options
to the background child. The public `prepare_producer_seed_manifest(...)` API performs only the
read/validation step when Python integration is preferred. See the
[operator guide](specs/096-producer-cli-warm-start/quickstart.md) for the complete workflow and limits.

Feature [097](specs/097-benchmark-task-envelope/) adds a static `lunar-benchmark-task-v1`
envelope for future SkyDiscover/LLM4AD comparisons:

```bash
lunar-evolution benchmark-task validate task.json --contract contract.json \
  --input-root ./public-input --model-profile-sha256 "$MODEL_PROFILE_SHA256" \
  --evaluator-fingerprint "$EVALUATOR_SHA256" --json
```

Validation rechecks confined input bytes and caller pins, emitting only bounded envelope and
comparison digests. It does not initialize Lunar Evolution storage or run an external framework, model or
evaluator; framework scores and generation IDs remain outside Lunar Evolution score and iteration authority.

Feature [098](specs/098-benchmark-comparison-plan/) freezes a multi-arm comparison plan on top of
these envelopes. Every arm must share the same task comparison digest, contract, model, exact
evaluator, candidate kind and physical budget. `BenchmarkComparisonPlan` and
`admit_benchmark_comparison_plan(...)` only validate those identities and local input bytes; they
do not run SkyDiscover, LLM4AD, Lunar Evolution or any evaluator, and they produce no effectiveness claim.

Feature [099](specs/099-benchmark-comparison-result/) adds a bounded result receipt for that plan.
It records per-arm status, counters, timing, finite score summaries and evidence digests, then
checks that every planned arm appears exactly once. It remains measurement evidence and never
updates Lunar Evolution candidate, score or iteration authority.

The static `benchmark-comparison validate-result` command validates a plan and result receipt with
the same local contract, input, model and evaluator pins. It runs before normal configuration
initialization and emits only comparison/result IDs and arm summaries.

Feature [100](specs/100-benchmark-evidence-binding/) also checks the actual per-arm evidence files:

```bash
lunar-evolution benchmark-comparison validate-result plan.json result.json \
  --contract contract.json --input-root ./public-input \
  --model-profile-sha256 "$MODEL_PROFILE_SHA256" \
  --evaluator-fingerprint "$EVALUATOR_SHA256" \
  --evidence-root ./evidence --json
```

Each result arm must then include `evidence_path` and `evidence_size` alongside `evidence_sha256`.
Paths are relative to `--evidence-root`; files and ancestor directories must not be symlinks.
The command reads bounded bytes and rejects observed replacement, size or digest changes, returning
`evidence_bound: true` only after all arms pass. Without the flag it checks the receipt with
`evidence_bound: false`. This verifies local bytes; it does not certify how they were produced or
turn external scores into Lunar Evolution scores.

Feature [101](specs/101-exact-comparison-plan-binding/) binds a result to the complete plan, including
each arm's benchmark name, release and publication digest. Create a new pinned receipt with
`BenchmarkComparisonResult.from_plan(plan, arms)`. Add `--plan-sha256 "$PLAN_SHA256"` to the command
above to require the independently saved canonical `plan.digest()`, the supplied plan and the receipt
to agree. A matching common comparison ID alone cannot satisfy this check. Output reports
`plan_bound` independently from `evidence_bound`; legacy receipts report `plan_bound: false` and
cannot satisfy a caller plan pin. The factory declares a binding and does not certify execution.

Feature [102](specs/102-candidate-source-bundle/) adds a standalone manifest for multiple source
files. Validate the declared files against their sizes, SHA-256 values and algorithm contract:

```bash
lunar-evolution candidate-bundle validate bundle.json --source-root ./source \
  --contract contract.json --bundle-sha256 "$BUNDLE_SHA256" --json
```

The optional bundle pin is the canonical `CandidateSourceBundle.digest()`, covering the entrypoint,
contract and sorted file descriptors. Output contains digests, file count and total bytes. This
static command does not initialize home/Store, execute source or admit an evolution candidate.
Files must be UTF-8 without NUL, at most 1 MiB each, with 1–64 declared files and at most 16 MiB
total. Manifest JSON is limited to 128 KiB. Paths must be canonical relative POSIX paths with no
links in the file or ancestor directories; use physical local paths instead of symlink aliases.
Unlisted files are ignored. The result covers declared bytes observed per file, not an atomic
repository snapshot or dependency/environment verification. See the
[offline quickstart](specs/102-candidate-source-bundle/quickstart.md) for manifest construction.

Feature [103](specs/103-candidate-workspace-materialization/) adds a separate materialization
boundary:

```bash
lunar-evolution candidate-bundle materialize bundle.json --source-root ./source \
  --contract contract.json --workspace-root ./workspaces \
  --command /usr/bin/python main.py --json
```

It copies only the already verified files into a fresh private directory, rechecks destination
bytes, and returns bundle/file-table metadata plus a path-free plan digest. It never starts the
command, imports the entrypoint, initializes home/Store, or creates a Candidate, receipt, or
archive. Runner, evaluator, dependency, environment, and recovery integration remain later work.

Feature [104](specs/104-candidate-execution-admission/) adds the static execution admission that
consumes this plan before a future runner is allowed to start. The implemented core API binds the
complete workspace-plan digest, bundle and contract identities, sorted logical input descriptors,
dependency/environment commitments, evaluator fingerprint, output-contract identity, and bounded
process budget into one path-free admission digest:

```python
from lunar_evolution import admit_candidate_execution, build_candidate_execution_admission
```

Structural parsing and validation perform no filesystem IO. When a caller supplies an input root,
the admission rechecks declared sizes and SHA-256 values with bounded descriptor-based no-follow
reads; all caller pins are checked before any input is opened. The result contains only identities,
counts, limits, and digests. It never starts the plan command, imports candidate code, installs
dependencies, calls an evaluator, initializes home/Store, or writes Candidate/receipt/archive
state. The corresponding `candidate-bundle admit-execution` CLI is dispatched before normal
configuration initialization and has an installed-CLI fixture covering no-home and no-execution
side effects.

Feature 105 prepares a separate private input directory from that declaration:

```bash
lunar-evolution candidate-bundle stage-inputs admission.json --plan plan.json \
  --input-root ./inputs --staging-root ./staging --json
```

Both roots must exist and be disjoint physical directories. Staging checks the complete admission
and plan before accessing either root, copies only declared inputs, then re-reads destination sizes
and SHA-256 values. It supports binary and empty files; directories use mode 0700 and files 0600.
The CLI returns `input_path` alongside digest/count metadata. The Python API
`lunar_evolution.stage_candidate_execution_inputs(...)` returns the path as a separate property and excludes
it from `to_dict()`. Each call creates a new directory owned by the caller. Failures clean only
identity-matched files created by the operation; an unsafe or failed cleanup has an explicit error.
Staging does not run the plan, merge inputs into candidate source files, or create an execution receipt.
The [offline quickstart](specs/105-candidate-input-staging/quickstart.md) exercises the installed CLI
and explains how to serialize an admission. Future runners must recheck the mutable staged bytes.

Feature 106 runs one already admitted multi-file candidate in that private workspace:

```bash
lunar-evolution candidate-bundle run admission.json --plan plan.json \
  --workspace ./workspace --input-root ./staged-inputs --json
```

The runner rechecks plan/admission pins, source and input bytes, no-follow directory identities and
root disjointness before starting. It passes an explicit argv plus the bundle entrypoint with
`shell=False`, a fixed cwd, an isolated process group and `LUNAR_CANDIDATE_INPUT_ROOT`; timeout and
output ceilings are enforced with bounded pipe reads. The static CLI runs before normal config/home/
Store initialization and returns path-free execution telemetry. A successful exit is only process
telemetry, not exact evaluator acceptance or a Lunar Evolution Candidate/score/receipt. Feature 106 does not
install dependencies, call models or evaluators, write execution evidence, or claim parity with
OpenEvolve, ShinkaEvolve or WebAgent.

Feature 107 retains launch intent and execution telemetry in a new caller-owned attempt:

```bash
lunar-evolution candidate-bundle run-recorded admission.json --plan plan.json \
  --workspace ./workspace --input-root ./staged-inputs --attempt ./attempt-001 --json
lunar-evolution candidate-bundle inspect-execution admission.json --plan plan.json \
  --attempt ./attempt-001 --json
```

The attempt parent must exist. The wrapper exclusively creates the attempt, syncs a launch intent
before entering the runner, then binds the returned metadata and file identities in a completion
record. An existing attempt is never reused. Inspection is read-only: valid incomplete evidence
returns `uncertain`; complete evidence returns `recorded` with the independent process status in
`runner_result.status`. Both paths check the intended plan/admission and optional caller pins.
Recording failure or timeout remains failure or timeout, and cannot authorize a score or Candidate.
No raw output or local path is stored in these execution records. Independent evaluation is
available below; native population integration is described after evaluation. See the runnable
[107 quickstart](specs/107-candidate-execution-evidence/quickstart.md).

Feature 108 independently evaluates a successful recorded multi-file candidate:

```bash
lunar-evolution candidate-bundle evaluate admission.json --plan plan.json --contract contract.json \
  --evaluator evaluator.json --harness harness.py --workspace ./workspace \
  --input-root ./staged-inputs --attempt ./attempt-001 --evaluation-root ./evaluations --json
lunar-evolution candidate-bundle inspect-evaluation ./evaluations/.candidate-evaluation-ID --json
```

The admission must pin `CandidateEvaluationSpec.pin()` and
`candidate_output_contract_sha256(contract.outputs)`. The evaluator fingerprint covers its
implementation bytes, command, explicit environment, identity and limits. Evaluation verifies
the execution record and original root identities, then saves the declared inputs and outputs in
a new private directory. The harness reads those snapshots without rerunning the candidate.
Missing or malformed required outputs produce an invalid zero-score report before harness launch.
Strict reports are captured in full up to 32 KiB; snapshots, raw report and a canonical manifest
remain available for read-only inspection. `evaluate` exits 1 for an invalid result, while
`inspect-evaluation` exits 0 for any complete consistent record, including an invalid result.

The output observation is explicitly at **evaluation time**, not proof of output bytes at process
exit. Inspection checks retained local consistency; a previously saved `--evaluation-sha256`
also pins the manifest. The host interpreter and dependency closure are not authenticated, and
this is not a sandbox.
See the complete [108 quickstart](specs/108-candidate-independent-evaluation/quickstart.md).

Feature 109 connects complete source bundles to native population search and delivery:

```bash
lunar-evolution evolve-bundle contract.json --profile bundle-profile.json \
  --generator-command '/absolute/python /absolute/generator.py' \
  --workspace ./bundle-run --destination-root ./deliveries --json
lunar-evolution candidate-bundle inspect-delivery ./deliveries/.bundle-delivery-ID \
  --delivery-sha256 SAVED_SHA256 --json
```

The existing delivery root must be outside the run's `evolution` evidence directory. The explicit
profile fixes candidate command, inputs, harness and evaluator limits. A command generator emits
`{"entrypoint":"solve/main.py","files":{"solve/main.py":"...","solve/helper.py":"..."}}`;
bundle parents provide a verified `parent_source_files` map. Python callers can use
`CandidateDraft.from_files(...)` and `MultiFileCandidatePipeline` with `LocalController.run_evolution`.

Every candidate receives its own execution and independent evaluation. Receipt v2 binds all source
files and retained evaluation evidence while v1 receipts keep their original hashes. Existing
population selection, lineage, islands, migration and checkpoints consume the local report; an
invalid candidate's claimed high score cannot win. Failed or uncertain attempts remain retained.
Resume uses the same command, profile and population options plus `--resume --run-id ID`; a terminal
resume validates saved results without generating or running candidates again.

Delivery contains the selected complete source, scored output snapshot, declared inputs, contract,
harness, evaluator spec and report. Its byte manifest supports copying and read-only inspection;
original inode-bound execution/evaluation evidence stays at its retained location. A delivery does
not rerun the candidate. Follow the standalone [109 quickstart](specs/109-bundle-population-integration/quickstart.md)
to run the complete path locally without a model or external framework.

Feature 110 lets the existing Agent worker generate the complete bundle. Select an Agent command
instead of a request-file generator, or use the native runtime directly:

```bash
lunar-evolution evolve-bundle contract.json --profile bundle-profile.json --workspace ./bundle-run \
  --agent-runtime openai-compatible --agent-runtime-endpoint YOUR_ENDPOINT \
  --agent-runtime-model YOUR_MODEL --agent-runtime-loop \
  --destination-root ./deliveries --json
```

The Agent receives the contract, verified input copies, complete parent source and independent
score feedback in a fresh workspace. Its bounded prompt points to full context files when source
does not fit inline. The evaluator implementation is not staged for the Agent. Bundle responses
must include every source file and the entrypoint; the shared Agent response limit is 1 MiB.
The fixed local pipeline still executes and scores each candidate independently.

`--agent-command` uses the existing JSON AgentRequest stdin interface; `--agent-runtime subprocess`
uses a native worker receiving the prompt on stdin. These are mutually exclusive with the original
`--generator-command`. Python callers select the same path with
`AgentCandidateGenerator(adapter, contract=contract, bundle_pipeline=pipeline)`. The standalone
[110 quickstart](specs/110-agent-bundle-generation/quickstart.md) validates native runtime generation,
helper-only improvement, complete delivery and terminal resume using local processes only.

Feature 111 also exposes this pipeline through ordinary conversational intake:

```bash
lunar-evolution solve 'Optimize the supplied data' --evolve --bundle-profile bundle-profile.json \
  --input ./data.csv=data.csv --runtime openai-compatible --endpoint YOUR_ENDPOINT \
  --model YOUR_MODEL --agent-loop --workspace ./mission --json
lunar-evolution solve --resume --run-id RUN_ID --bundle-profile bundle-profile.json \
  --runtime openai-compatible --endpoint YOUR_ENDPOINT --model YOUR_MODEL --agent-loop --json
lunar-evolution deliver RUN_ID --json
```

The profile's complete input set must match the parent's registered `data/raw/<target>` files by
size and SHA-256. Generation and execution use those staged copies. The selected scored output
appears in the parent's `output/`; complete source, inputs and evaluation materials are retained
under `.bundle-deliveries/`. Ordinary `deliver` verifies the package and published outputs. Resume
reuses the same child and prepared delivery without running the winner or Agent again. `answer`
and `resume` also accept `--bundle-profile`; continuation requires matching profile/runtime settings.

The profile loader still needs accessible matching input/harness resources. This mode requires
native population and a contract with declared outputs; it excludes detached solving and additional
evaluator commands. Parent outputs
retain the existing 256 KiB per-file cap; the complete package and outputs share the parent artifact
budget. See the standalone [111 quickstart](specs/111-conversational-bundle-delivery/quickstart.md).

Feature 112 prepares the evaluator and profile automatically:

```bash
lunar-evolution solve 'Optimize the supplied data' --evolve --multi-file \
  --input ./data.csv=data.csv --runtime openai-compatible --endpoint YOUR_ENDPOINT \
  --model YOUR_MODEL --agent-loop --workspace ./mission --json
```

The runtime compiles a snapshot evaluator, then a separate auditor supplies additional constraint
and score-order probes. Both probe suites must pass before the evaluator is frozen and candidates
are generated. `mission/evaluator-bundle/` and `mission/bundle-profile.json` retain the preparation;
answer/resume infer this mode and reuse those files without another evaluator compiler/auditor call.
Ordinary `deliver` also verifies the preparation evidence. The solver receives inputs and independent
feedback; evaluator source and probes are not staged in its context.

Feature [142](specs/142-automatic-solve-lifecycle/spec.md) adds a shared active-execution
budget for this automatic native multi-file path:

```bash
lunar-evolution solve 'Optimize the supplied data' --evolve --multi-file \
  --input ./data.csv=data.csv --runtime openai-compatible --endpoint YOUR_ENDPOINT \
  --model YOUR_MODEL --agent-loop --workspace ./mission \
  --timeout 600 --evaluator-preparation-timeout 900 \
  --evaluator-preparation-wall-timeout 1860 --solve-wall-timeout 3000 \
  --candidate-generation-max-steps 12 --home .lunar-evolution --json
```

These are example limits, not new defaults. `--solve-wall-timeout` accepts a finite positive number
of seconds up to 86400 and is optional. When supplied, one fixed deadline covers contract intake,
evaluator preparation, candidate generation, local execution, scoring, selection and parent
delivery. Requests use the smaller of their existing stage limit and the remaining solve time;
each candidate or phase does not receive a fresh solve budget. Preparation and candidate tool-step
limits continue to apply independently. Temporary timeouts do not change frozen evaluator/profile,
contract, plan or candidate receipt identities.

This is an **active execution** budget, not a lifetime limit accumulated across `resume` or `answer`.
Waiting for user input ends the current execution. A valid explicit continuation starts another
execution under the same persisted policy; omit the option to restore it, or repeat exactly the
same value. A legacy handoff cannot acquire this policy later, and an exhausted or otherwise
terminal run cannot replenish its budget through continuation.

```bash
lunar-evolution resume RUN_ID --runtime openai-compatible --endpoint YOUR_ENDPOINT \
  --model YOUR_MODEL --agent-loop --home .lunar-evolution --json
lunar-evolution status RUN_ID --home .lunar-evolution --json
```

The parent remains running through evolution and succeeds only after verified delivery. A durable
orchestration task is reused on continuation; terminal continuation creates no new candidates or
delivery copies. One parent has one active owner across local processes, and `answer` acquires the
same lock before recording the answer. `solve`, `answer` and read-only `status` expose a bounded
`solve_execution` object with execution ID, policy and origin, phase, state and stopping reason.
It does not report a live monotonic remainder or infer whether a remote request finished.

Add `--detach` to a new automatic solve, `solve --resume`, `resume`, or `answer` to run it in the
background. The command returns the same parent handle with `launch_status: accepted`; this means
the worker was admitted, while `status` continues to report durable progress and any previous
preparation diagnosis. Persisted evolution and budget policies are restored exactly. A worker
exits when input is needed, and an explicit answer starts a new execution. If launching fails
after an answer was accepted, the answer remains saved for explicit resume.

The launcher transfers the workspace lock to the child and records its process identity before
allowing work. Duplicate continuations are refused; registration is cleared only while the recorded
PID/PGID still match.
Parent cancellation follows the verified child link, and local candidate, evaluator, probe and
runtime processes register their process groups for cleanup. Failed cleanup retains its ownership
record and blocks later stages. See the [background quickstart](specs/142-automatic-solve-lifecycle/quickstart.md)
for commands and the offline test scenario using actual subprocesses. Legacy automatic runs
without a lifecycle marker remain outside background mode.

Offline coverage does not establish real-model delivery success;
Feature 139's real automatic multi-file result remains `0/1`. See the current
[release assessment](docs/system-readiness-20260916.md) for the remaining work.

Automatic preparation retains the existing compiler's input-format and probe capacity limits.
It requires all contract inputs to match registered `csv`, `json`, `jsonl` or `text` files and uses
local Python without installing dependencies. Probe success covers the tested cases and does not
prove full business correctness. See the local [112 quickstart](specs/112-automatic-bundle-evaluator/quickstart.md).

Normal solving remains the default. The first preregistered GLM-5.2 acceptance on `c977eb4`
completed **0/2** tasks: both failed at contract intake, before evaluator or candidate generation.
See the [113 report](docs/history-archive.md). Current-version reliability
still needs successful real-model validation; local fixtures do not establish effectiveness or
relative WebAgent performance. Active-process cancellation orchestration and the full OpenEvolve/
Shinka launcher, scheduler, remote and real-campaign connection remain future work. Features 150–152
supply verified grouping, native draft projection and the local-authority admission plan.
Feature 153 now covers the bounded offline imported-material transaction described above, including
native execution, retained intent/evidence, caller-owned active deadline/cancellation, durable
all-rejected terminal state, archive publication, population read-back/resume and existing delivery
API verification. Cross-process deadline restoration and full unknown-result recovery remain open.
No real producer campaign is implied.

Feature 114 fixes the confirmed intake integration problem: contract compilation uses a stateless
protocol call when supported and receives explicit JSON field/type guidance. Ordinary solving
retains its tools. Describe the required input schema and objective in the goal or answer intake
clarifications; the isolated compiler does not inspect staged files. Invalid responses still fail
without an automatic repair request. The repair has offline coverage; a new preregistered run is
required to measure its real-model effect. See [114 verification](specs/114-isolated-contract-intake/quickstart.md).
The separately registered [115 follow-up](docs/history-archive.md)
also completed 0/2: one accepted contract reached evaluator preparation, then timed out; the other
contract request timed out. Known usage is only a subtotal. Generated evaluator quality and
successful real multi-file delivery remain unverified.

Feature 116 makes automatic preparation failures visible in solve/answer/resume JSON and
`status` as `evolution.preparation`. A runtime failure retains the accepted contract and returns
nonzero; if the preparation is recoverable, use `resume RUN_ID` with the same home and runtime
settings to try again. There is no automatic retry. Status inspection is read-only. Existing frozen
evaluators are reused, and conflicting evidence is still rejected. Only an actual nonempty question
permits `answer`; dependency waits no longer appear as a user question. Interrupted preparation is
reported as unknown, without a claim about provider completion or usage. See the offline
[116 recovery checks](specs/116-preparation-recovery-state/quickstart.md).

Local evaluator preparation failures now expose optional `evolution.preparation.local_failure`.
It identifies compiler/auditor response admission or preflight, a fixed reason such as
`input_format_invalid`, `report_invalid` or `validity_mismatch`, and one-based probe/input/ordering
positions where known. These observations describe the failing local check without storing file
contents, paths, probe names or exception prose. They remain nonrecoverable validation failures;
runtime recovery rules and frozen evaluator reuse are unchanged. Older observations still load,
and invalid optional detail is omitted. See [127 diagnostics](specs/127-evaluator-preparation-diagnostics/quickstart.md).

The independently registered [117 run](docs/history-archive.md)
on Feature 116 extended request/process limits to 600 seconds and task limits to 3600 seconds,
retaining the other task/model/budget conditions. It still completed **0/2**: one evaluator request
timed out, and the other task's contract response was wrapped in a Markdown JSON fence and rejected.
Preparation failure now returns parent JSON and durable diagnostics; no recovery retry was used.
Known usage is a 11309-token subtotal, with timeout consumption unknown. There is still no real
multi-file delivery or generated-evaluator quality result from these acceptance campaigns.

Feature 118 adds explicit constraint `verification_scope`: `output`, `source`, or `execution`.
Generated evaluators support output checks. A source/execution requirement without a supported
independent checker stops preparation before a compiler/auditor request and appears in `evolution.preparation` with
category `unsupported_verification` and the affected IDs/scopes. The contract is retained; retrying
generation cannot supply the missing independent checker. No requirement is removed because it is
partial or has empty result fields. Older unscoped contracts keep their existing digests and probe
coverage. This does not prove helper imports, standard-library-only execution or actual input use.
See [118 capability and framing checks](specs/118-contract-protocol-capabilities/quickstart.md).

Feature 119 supports one hard source requirement: `verification_scope="source"` with
`source_check={"kind":"python_file_count","minimum":2}` (integer minimum 1–64). Lunar Evolution counts
distinct declared paths ending in lowercase `.py`, including empty files, against the verified
source bundle. The output evaluator checks the remaining output requirements. A source failure
forces an invalid result and skips the output harness; source success cannot override output failure.
Source-check evidence is retained and recomputed during inspection, ranking and portable delivery,
without rerunning the program. This proves the declared file count, not helper imports or behavior.
Unsupported source, soft source and execution requirements still stop before evaluator generation.
See [119 source verification](specs/119-source-file-verification/quickstart.md).

The separately registered [120 real acceptance](docs/history-archive.md)
completed **0/2** on the supported file-count scope. Both contracts compiled; both evaluator-generation
requests timed out at 600 seconds before any candidate or delivery. Known usage was 16,161 tokens;
timeout consumption and cost are unknown. This does not establish real multi-file reliability.

[121 protocol work](specs/121-evaluator-prompt-protocol/validation.md) supplies the compiler and
independent auditor with complete response/report shapes and the actual source restrictions.
Its offline diagnostic reproduces the old request hashes, and no model request was made for 121.
This fixes missing generation instructions; it has no measured latency or success-rate result.

[122 transport observations](specs/122-transport-milestone-observation/quickstart.md) add the last
local connection/write/header milestone, HTTP exchange index and elapsed milliseconds to bounded
transport results. Valid detailed model failures use subject diagnostic version5; versions1–4 keep
their existing meaning. `wait_response_headers` means the local request-write call returned,
not that the provider received it or began model execution. Connection includes DNS/TCP/proxy
CONNECT/TLS, and received headers may precede a redirect. Final status and coarse failure phase
remain separate. Only fixed names and integers enter this detail; request bytes, TLS, proxies,
redirects, deadlines and retries are unchanged. No new real model result is claimed.

The independently registered [123 small diagnostic](docs/history-archive.md)
finished **0/1** evaluator preparations. Its compiler request returned HTTP200 in243 seconds
(20,831 reported tokens), then local preparation rejected the evaluator; no auditor or holdout ran.
Static inspection found that generated code looked for input descriptor `path`, while the native
field is `target`. The snapshot prompt does not yet specify that nested input shape completely.
This identifies a concrete next repair, without establishing the cause of120's timeouts or real
multi-file delivery. No attempt was retried; historical denominators remain separate.

A completed observation from the transport-free remote lifecycle can use
`lunar_evolution.admit_remote_materials(material_root, state, contract, evaluator, ...)`. The bridge accepts
only a reconciled `completed` state with pinned producer identity and `candidate_source` references,
then routes every local file through the same exact evaluator and receipt path. Remote experiment
timestamps, attempts, raw state identity, and any external score-like observations are reduced to
provenance digests. A validated generic-safe experiment ID may remain as the opaque
`producer_run_id` provenance label; it never becomes a score or candidate identity. The bridge
never calls a backend or treats remote completion as a local result. The
transport-free lifecycle state currently does not carry the submit contract digest, so callers must
bind the completed observation to the intended contract themselves; the bridge binds the supplied
contract to local re-evaluation. Remote material references currently carry no parent lineage and
therefore enter the generic envelope with an empty lineage tuple. Missing, changed, symlinked, or
digest-mismatched files fail closed. If every local evaluation is unusable, the bridge preserves
the generic `SeedAdmissionError(code="no_usable_seeds")` result semantics. A supplied staging root
must be a sibling tree disjoint from the material root, including resolved filesystem aliases.

The same benchmark can use Lunar Evolution's repository-owned runtime instead of command adapters. A
one-shot comparison uses:

```bash
lunar-evolution benchmark contract.json \
  --agent-runtime openai-compatible \
  --agent-runtime-endpoint http://127.0.0.1:11434/v1/chat/completions \
  --agent-runtime-model your-local-model \
  --json --home .lunar-evolution
```

Run the identical command in a new workspace with `--agent-runtime-loop` to measure the bounded
tool-capable runtime profile. Runtime-loop settings are fingerprinted, and memory, transcripts, and
no-shell execution remain explicit opt-ins. Runtime-backed calls still use the population strategy
and strict candidate/evaluator bridges, so a model response cannot bypass validity checks.

Hermes, DeepSeek Harness, Codex, Claude Code, and OpenClaw remain useful optional adapters or parent
processes. They are execution-plane integrations; Lunar Evolution's local controller, evolution
strategy, evaluator authority, artifacts, and resume semantics stay repository-owned.

For higher-assurance algorithm work, configure two or more independent evaluator Agents. Every
member reads the same candidate in an isolated workspace; validity is accepted only when all
members agree, while valid scores and common detailed metrics are combined with a median. A member
failure, malformed report, or validity disagreement is represented as a controlled invalid report
and cannot become the best candidate:

```bash
lunar-evolution evolve contract.json --strategy population \
  --agent-command "/absolute/path/to/solver --json" \
  --evaluator-portfolio-command "/absolute/path/to/evaluator-a --json" \
  --evaluator-portfolio-command "/absolute/path/to/evaluator-b --json" \
  --json --home .lunar-evolution
```

The ordered evaluator command list and shared role/capability profile are included in the
credential-safe resume fingerprint. Use either this ensemble or one `--evaluator-command` /
`--evaluator-agent-command`; mixing evaluator modes is rejected before a run is created.

When an Agent is the solver, later generations receive execution-grounded refinement evidence for
their parent, population inspirations, and recent archive entries. The shared envelope combines a
bounded/redacted candidate source excerpt, source digest, controlled process/output-contract status,
verified output path/size/digest metadata, and the independent `evaluation_feedback` projection.
This lets native population search repair a real failed attempt instead of merely sampling again.
It is reconstructed from the candidate archive on resume; no second feedback database or
in-memory chat dependency is required.

Raw input rows, output contents, candidate stdout/stderr, model credentials, and evaluator adapter
exceptions are excluded. Unsafe or oversized source/execution/output evidence degrades to a stable
unavailable category, and the complete generation prompt remains bounded. Direct callback and
command generators retain their existing `GenerationRequest`; this evidence join is specific to
the repository Agent bridge. See
[`specs/039-execution-grounded-refinement/`](specs/039-execution-grounded-refinement/) for the SDD
contract.

`status --json` and `events --json` expose the evolution result, iteration events, candidate archive
events, Agent model/tool lifecycle events, and indexed `evolution/archive.jsonl`,
`evolution/state.json`, `evolution/result.json`, and redacted solver/evaluator transcript artifacts.
OpenEvolve remains optional and is invoked only when `--openevolve-command` points to an existing
absolute executable and `--evaluator-command` supplies local verification; no global installation
is discovered and an external evaluation never becomes the Lunar Evolution score.

An explicit Agent can generate candidates directly while the evaluator remains independent:

```bash
lunar-evolution evolve contract.json --strategy population \
  --agent-command "/absolute/path/to/agent-wrapper --json" \
  --agent-role solver --agent-capability read_files \
  --evaluator-command "/absolute/path/to/evaluator-wrapper" \
  --json --home .lunar-evolution
```

The Agent receives a bounded algorithm context and returns source text or a `{\"source\": ...}`
object. Lunar Evolution archives and evaluates that proposal through the same validity-first path as
command generators; an Agent claim is never treated as evaluation evidence. See
[`specs/015-agent-backed-evolution/`](specs/015-agent-backed-evolution/) for the SDD contract.

If a separate evaluator Agent is available, use `--evaluator-agent-command` instead of
`--evaluator-command`; it must return a strict JSON `EvaluationReport` and is validated by the same
schema before influencing selection:

```bash
lunar-evolution evolve contract.json --strategy population \
  --agent-command "/absolute/path/to/solver-wrapper --json" \
  --evaluator-agent-command "/absolute/path/to/evaluator-wrapper --json" \
  --json --home .lunar-evolution
```

Population search can also rotate multiple explicit solver Agents using repeatable
`--agent-portfolio-command` options:

```bash
lunar-evolution evolve contract.json --strategy population \
  --agent-portfolio-command "/absolute/path/to/solver-a --json" \
  --agent-portfolio-command "/absolute/path/to/solver-b --json" \
  --evaluator-agent-command "/absolute/path/to/evaluator --json" \
  --json --home .lunar-evolution
```

Calls use the ordered portfolio deterministically in round-robin order. Every proposal still goes
through the same archive and independent evaluator, and the ordered command list is covered by the
resume fingerprint. The single `--agent-command` form remains unchanged.

The JSON result includes `best_candidate_path` when a valid candidate was selected. It is relative
to the returned `workspace`, so a parent Agent can inspect the source without parsing the internal
candidate archive. Failed or all-invalid runs return `null` for both the best candidate ID and path.

### Three local invocation modes

Lunar Evolution is the same independent agent in each mode; a parent Agent is optional.

1. Run it directly as a standalone local Agent. The repository-owned SQLite ledger and workspace
   are enough; no Hermes/OpenCode/Codex installation is discovered or imported.
2. Call it from Codex, Hermes, OpenClaw, or a script as a child process. Use `--json` and pass the
   goal/plan on arguments or stdin; parse the bounded stdout payload and inspect the returned
   `run_id`, status, artifacts, and plan metadata.
3. For a long task, request a durable handle with `--detach`, let the caller exit, then invoke
   `resume <run-id>` later. The same plan revision, algorithm contract, workspace, and ledger are
   recovered; the parent does not need to keep a model session alive.

Examples:

```bash
# 1. Standalone
lunar-evolution plan routing-plan.json --runtime mock --home .lunar-evolution --json

# 2. Parent Agent child process (stdin/stdout JSON)
printf '%s' 'solve this routing problem' | lunar-evolution run - --runtime mock --json --home .lunar-evolution

# 3. Detached then resumed (general agent run)
lunar-evolution run "search for a feasible schedule" --runtime mock --detach --json --home .lunar-evolution
lunar-evolution resume <run-id> --runtime mock --json --home .lunar-evolution
```

These are process/interface choices, not different evolution algorithms. New evolution work uses
the population strategy behind the same Solver/Evaluator boundary, independent of whether Lunar Evolution is
called directly, by a parent Agent, or through a detached process. `--agent-loop` and
`--agent-runtime-loop` remain model/tool runtime choices inside that boundary.

If the session needs a decision, it can call `ask_user`. The run then becomes `awaiting_input` and
returns the question in JSON/status output. Answer the same durable run later; no duplicate task is
created:

```bash
lunar-evolution answer <run-id> "json" --runtime openai-compatible \
  --endpoint "$LUNAR_EVOLUTION_MODEL_ENDPOINT" --model "$LUNAR_EVOLUTION_MODEL" --agent-loop --memory --json
```

The answer is written as a bounded run artifact and included in the next task prompt. Use `-` as the
answer to read it from stdin.

For retries and `resume` to replay recent model/tool context, add `--session-history`. This writes a
bounded, redacted JSONL transcript under the run workspace and indexes one stable session artifact:

```bash
lunar-evolution run "Continue the migration" \
  --runtime openai-compatible --agent-loop --session-history --json
```

Session history is separate from durable memory. It is opt-in and retains only recent messages; use
`remember_memory` for concise facts that should outlive a session.

For loops using a model profile, each request includes a fresh advisory snapshot of remaining time,
tool calls, and configured cumulative token/cost allowances. It encourages preserving a complete
candidate before expensive refinement. This snapshot is not saved in session history, and isolated
protocol calls do not receive it. Command timeouts are tightened to the invocation's remaining time;
scripts should stop earlier to leave time to save their output. Cancellation remains cooperative.

The `write_file` tool publishes a complete single-file replacement atomically. Failed writes preserve
the previous file; existing permissions are retained and new files use owner-only permissions. Scripts
launched with `run_command` must implement their own incremental saving. Files left by a failed run
remain unverified: they do not create a completed receipt or authorize scoring.

### Optional durable memory

Memory is explicitly opt-in because recalled local notes may be sent to the configured model
endpoint. Enable it for a session with `--memory`:

```bash
lunar-evolution run "Continue the migration and remember the key decisions" \
  --runtime openai-compatible --agent-loop --memory --json
```

The model can call `recall_memory` and `remember_memory`. Entries are bounded and stored in the same
local SQLite database, with `global` and run-scoped namespaces. Notes are never injected into a
request silently; the model must explicitly request recall. No embeddings service or vector database
is required. Inspect notes locally with `lunar-evolution memory --json` or search global notes with
`lunar-evolution memory "deployment" --json`.

## Multi-step plans

For dependent work, provide a JSON plan. The controller validates the graph before creating a run,
executes ready tasks in order, and adds verified predecessor artifact paths/previews to each
dependent prompt:

```json
{
  "goal": "prepare a report",
  "tasks": [
    {"id": "research", "title": "Research", "prompt": "Collect facts"},
    {"id": "write", "title": "Write", "prompt": "Draft the report", "depends_on": ["research"]}
  ]
}
```

```bash
uv run lunar-evolution run --plan plan.json --runtime mock --json
```

Malformed plans (duplicate IDs, unknown dependencies, or cycles) are rejected without leaving a
partial run in SQLite. A failed or rejected prerequisite blocks downstream tasks and the run settles
as failed. Each evaluator decision is also written to `evaluation.json` within the attempt
workspace and emitted as a structured event.

### Artifact acceptance contracts

An acceptance value can now verify observable local output, rather than only asking whether a
Worker's result text contains a phrase. These rules are evaluated in-process after the selected
Evaluator Profile passes. They never call a model, shell command, plugin, or network endpoint, and
they can only inspect regular files in the current task attempt workspace.

```json
{
  "id": "report",
  "title": "Write report",
  "prompt": "Create report.json and summarize the result",
  "acceptance": {
    "all": [
      {"result_contains": "report written"},
      {"artifact_exists": "report.json"},
      {"artifact_text_contains": {"path": "report.json", "contains": "summary"}},
      {"json_has_keys": {"path": "report.json", "keys": ["summary", "sources"]}}
    ]
  }
}
```

Supported leaves are `result_contains`, `artifact_exists`, `artifact_text_contains`, `json_parse`,
`json_has_keys`, and `output_valid`; compose them with non-empty `all` or `any` arrays. A plain string and the
legacy `{ "contains": "..." }` form still mean result-text containment. Paths must be portable,
relative, and remain below the current attempt directory; rule count/depth, contract text, and
inspected artifact bytes are bounded. Invalid JSON, missing keys, binary/oversized content, or a
symlink escape fail closed and leave an auditable failure rather than reading outside the workspace.

`output_valid` is the structured-output check used by `AlgorithmProblemContract.outputs`; its
payload is `{ "path": "output/...", "format": "json|jsonl|csv|text", "fields": [...] }`.

The `task_evaluated` event and attempt `evaluation.json` contain a bounded rule-level decision tree.
`lunar-evolution status <run-id> --json` exposes the most recent evaluation summary under each task's
`evaluation` field, so a parent Agent can decide whether to patch or replan without scraping logs.
The complete v1 grammar and a runnable local example are in
[`specs/008-artifact-acceptance-contracts/contracts/acceptance-contract.md`](specs/008-artifact-acceptance-contracts/contracts/acceptance-contract.md)
and [`quickstart.md`](specs/008-artifact-acceptance-contracts/quickstart.md).

### Evidence-guided recovery proposals

After a failed verifier, exhausted runtime path, budget boundary, interruption, or input pause, ask
the local controller for an advisory next step:

```bash
lunar-evolution recover <run-id> --json
lunar-evolution status <run-id> --json
```

The deterministic local `RecoveryPolicy` returns one of `retry`, `ask_user`, `propose_patch`,
`propose_replan`, `stop`, or `none`. It reads only the durable ledger and does not call a model,
runtime, tool, shell, or network endpoint. Critically, it never resumes work, weakens acceptance,
changes a budget, or commits a plan revision itself: a parent Agent deliberately follows with the
existing `answer`, `resume`, `patch`, or `replan` command.

Each distinct proposal is written as a SHA-256-indexed
`recovery/proposals/<fingerprint>.json` audit artifact and an idempotent `recovery_proposed` event.
The latest proposal is available as the additive `recovery` field in `status --json`, alongside the
existing task evaluation. Proposal evidence uses only controlled IDs, statuses, rule kinds, and
budget names; it does not duplicate raw runtime errors, prompts, artifacts, answers, or model
content. The full contract and runnable fixture are in
[`specs/009-evidence-guided-recovery/contracts/recovery-proposal.md`](specs/009-evidence-guided-recovery/contracts/recovery-proposal.md)
and [`quickstart.md`](specs/009-evidence-guided-recovery/quickstart.md).

When a task is retried, the next attempt prompt keeps the immutable task request first and appends a
bounded feedback projection. A failed acceptance evaluation contributes only controlled rule names;
a runtime failure contributes generic recovery guidance. Raw provider errors, credentials, result
text, and artifact contents are never copied into retry prompts. The prompt is written and hashed
under the new attempt directory, so the correction loop remains inspectable without changing the
plan or acceptance contract. See
[`specs/011-verified-retry-feedback/`](specs/011-verified-retry-feedback/) for the contract.

## Called by another Agent

Codex or another local Agent can invoke the CLI as a child process. Use `--json` so stdout contains
one stable machine-readable value, and use the returned run ID as the durable handle:

```bash
result=$(uv run lunar-evolution run "Inspect this repository" --runtime mock --json)
run_id=$(printf '%s' "$result" | python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
uv run lunar-evolution status "$run_id" --json
```

For a long-running goal, return the handle immediately and let a local child process continue:

```bash
result=$(uv run lunar-evolution run "Inspect this repository" --runtime subprocess --detach --json)
run_id=$(printf '%s' "$result" | python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
uv run lunar-evolution status "$run_id" --json
```

The detached controller log is stored at `<run-workspace>/controller.log`.

`cancel` updates the ledger first, then terminates the detached controller's persisted process group.
If a runtime races with cancellation, its late result is discarded and recorded as
`task_result_discarded`; it cannot turn the run back to succeeded.

Long goals can be piped without shell escaping:

```bash
printf '%s' 'Analyze these three artifacts and produce a report' \
  | uv run lunar-evolution run - --runtime mock --json
```

The TUI, if added later, is for human observation and approvals; the CLI/JSON contract remains the
automation boundary for Codex, Hermes, OpenClaw, and scripts.

## Development

```bash
python -m pip install 'uv==0.11.8'
python -m venv .venv
uv pip install --python .venv/bin/python -e '.[dev,lint]'
.venv/bin/python tools/run_tests.py --junit-dir .lunar-evolution/test-results
.venv/bin/ruff check src tests tools
```

The full regression runner requires this uv version and its populated dependency cache; historical
environments install offline from that cache. See the [archive guide](docs/history-archive.md).

Full validation runs three separate phases: current product tests, archived historical tests at
`c6947fdfbf43d84e83cc29cc215e7bc0250db83a`, and the 24 original frozen registration tests at
`5560eb9f67463badc31fed17e309bb5dc1dabf8f`. Historical phases use temporary checkouts and separate
environments outside this repository; their original product bytes, registered hashes and exact
collection inventories remain unchanged. All three phases must pass, with separate JUnit reports
in `.lunar-evolution/test-results`. The runner needs local Git history and removes temporary
checkouts afterward. See the [historical archive](docs/history-archive.md) for the retained evidence.
Use `python -m pytest tests/<file>.py` for focused current-product tests. These regressions do not
run model campaigns or call providers.

For the focused native automatic multi-file end-to-end regression:

```bash
.venv/bin/python tools/run_tests.py --suite native-e2e \
  --junit-dir .lunar-evolution/test-results/native-e2e
```

This offline suite covers foreground/background delivery, input/answer/resume, cancellation,
deadline cleanup, killed-worker recovery and installation outside the checkout. It uses fixture
runtimes and local HTTP, retains `native-e2e.xml`, and does not load historical checkouts. It needs
`uv` and cached build dependencies for wheel installation. It does not replace all three release
regression phases or establish real-model success. See the
[automatic solve quickstart](specs/142-automatic-solve-lifecycle/quickstart.md).

See the [quickstart](specs/001-standalone-local-agent/quickstart.md) for the recovery scenario and
the [runtime contract](specs/001-standalone-local-agent/contracts/runtime-adapter.md) before adding
an adapter.

The effect-layer design and WebAgent branch comparison are documented in
[`docs/architecture.md`](docs/architecture.md), with the active SDD feature in
[`specs/062-fixed-budget-independent-measurement/`](specs/062-fixed-budget-independent-measurement/).

Model selection and local spend policy can be represented without provider credentials using
`lunar_evolution.ModelProfile`. Feed normalized runtime usage (`input_tokens`, `output_tokens`,
`total_tokens`) to `lunar_evolution.UsageLedger` to enforce a token ceiling; provide integer micro-USD rates
and a cost ceiling when a cost estimate is available. `AgentLoopRuntime` accepts the profile to
enforce its timeout, step, token, and cost limits while preserving the legacy no-profile behavior.
See
[`specs/054-model-profiles-cost-control/`](specs/054-model-profiles-cost-control/) for the bounded
contract and [`specs/055-runtime-model-profile-integration/`](specs/055-runtime-model-profile-integration/)
for runtime enforcement. The ordinary CLI loop can load the same policy from a bounded JSON file:

```bash
lunar-evolution run "continue the task" --runtime openai-compatible --agent-loop \
  --endpoint "$LUNAR_EVOLUTION_MODEL_ENDPOINT" --model-profile ./model-profile.json --json
```

The profile supplies the model when `--model` is omitted; changing it while resuming a
conversational `solve` run is rejected by the compiler fingerprint. See
[`specs/056-cli-runtime-model-profile-provenance/`](specs/056-cli-runtime-model-profile-provenance/).

Normal sessions and isolated compiler/audit calls each apply the profile's timeout and usage
policy. An explicit timeout can tighten the profile limit. If a token or cost ceiling is set,
every model response must include valid usage; missing usage stops the invocation before its
tools or a successful result. A final answer exactly at the ceiling succeeds, while a tool
continuation at the ceiling stops before executing tools or requesting another model turn.
Profiles without spend ceilings keep optional usage telemetry.

Usage accounting resets for each invocation, including each fresh deep-evolution subject round.
Provider usage is observed after a response, so the limit stops continuation but cannot undo
already billed tokens or guarantee that an in-flight call cannot overshoot. Deadline checks also
reject late responses and stop further tools; in-flight model/tool cancellation remains the
responsibility of that implementation. `thinking_budget` is recorded in the profile but is not
currently sent as a provider request parameter. See the
[execution contract](specs/059-model-profile-execution-boundaries/spec.md).
