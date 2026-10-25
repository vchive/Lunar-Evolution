# ShinkaEvolve v0.0.7 source-profile review

Status: public source archive/tree and dependency **declarations** retained and
statically reviewed on 2026-10-25; root independently verified the source and
declaration facts with result `PASS_WITH_MODE_DISTINCTION`. This completes
only a source/declaration subitem of step 1 in
[project-runtime-profile.md](project-runtime-profile.md). Dependency bytes,
finite executable profile, image, loader policy, actual execution and runtime
acceptance remain open. `production_admission=false`.

## Selection and frozen source

No prior real Shinka release/commit pin was found in the reviewed Lunar source,
Feature191 documents or retained upstream material; producer fingerprint
placeholders are not release pins. This is a **new source-baseline selection**,
not a claim that a version was already accepted. The retained public release/tag
listing names seven releases, `v0.0.1` through `v0.0.7`. This review selects the
explicit non-prerelease
[v0.0.7 release](https://github.com/SakanaAI/ShinkaEvolve/releases/tag/v0.0.7),
published `2026-06-02T16:44:18Z`, then checks its source against the existing Lunar
exporter schema and layout. Neither a moving `latest` endpoint nor a default
branch is an execution pin.

The annotated tag object is `414e9d48fce1942e58086ab9136db04f7465072c`, resolving
to commit `c4568adde253cacf185be3a8412c3c2142761ebe`, whose complete Git tree is
`02eeb82bf432c312f0c87d9379a4d96c65870b08`. `shinka/__init__.py:5` declares
`__version__ = "0.0.7"`. The retained archive URL is
`https://api.github.com/repos/SakanaAI/ShinkaEvolve/tarball/c4568adde253cacf185be3a8412c3c2142761ebe`.

| Retained item | Bytes | SHA-256 |
| --- | ---: | --- |
| `archive.tar.gz` | 9,450,712 | `4a9c242de0b2b316013ed7ee1b3ebc8a94a6bf6098e7e370fadd5b94201e1d67` |
| `archive-source-index.json` | 70,213 | `e8b1d89a5d6f3a352c16c9c4df77d00c4d94dc5b37a117c035135ae25a8677cf` |
| `git-tree.json` | 99,369 | `138c5959ff60f93531d7615d0b5d68ee05de6cbd0db1578d5a4aa97b4c6ee041` |
| `commit.json` | 1,294 | `dc6e78c4f96c949e631b1694c1bceae669cf937290c66598144fe94c7bb46424` |
| `tag-object.json` | 784 | `18561be55859e2599d8fc063d6be714b76003e0c27e7a583637d206279b44f52` |
| `source-review.json` | 8,789 | `f65fde6a004921527d4afab264b847765ced93a3a949b481638287cb19474d07` |
| `package-static-imports.json` | 109,373 | `9e5ba001bc7ce160e4dcde26d166c4aa0959f996ced3ea116453144ff86e39ab` |
| `static-source-review.py` | 5,899 | `4966851e5649cb000e3810432b9ed16b494a049391fc7ca73b158038e9353dd0` |

Raw material is create-only ignored evidence under
`.lunar-evolution/validation/feature191-20261025/shinka-source-freeze-igo1sdkj/`
in the primary workspace. It includes the release/tag lists, tag reference and
object, commit/tree responses, acquisition headers, archive, per-file index,
AST import observations and static schema-selection record.

The independently produced `root-independent-review.json` in that raw directory
has SHA-256 `30f28bdaaf72631e7abf2629464fa1e1901dc7162b119f34ca5a06dd7fc5ea18`.
Its retained verifier independently checked all blobs, sizes, executable-bit
projections, the reconstructed Git tree, tag/commit, AST parsing, dependency
declarations and seven required SQLite columns. The first review refusal
(`root-independent-initial-refusal.json`) records the mistaken assumption that
full tar permissions must equal Git modes. The second reviewer attempt's naive
comma-separated SQL parsing encountered a comma in a comment; the receipt
records its correction to declaration-per-line parsing. Both corrections are
reviewer changes, without changing raw source. This independent result accepts
only the source/declaration facts; dependency bytes and runtime remain unaccepted.

Standard-library tar reading found 287 regular files with 12,837,527 content
bytes; archive symlink, hard-link and special-file members are absent. The full
tar permission modes are 283 files with `0664`, four files with `0775`, and 49
directories with `0775`. These are distinct from Git's file mode representation.
Every file matches the separately fetched, nontruncated recursive API tree by
path, size, Git blob hash and executable-bit projection (`100644`/`100755`).
`archive-source-index.json` retains only this `git_mode` projection, and
`source-review.json`'s `regular_modes` field also contains projected Git modes,
not full tar permissions; the original archive retains the latter. Reconstructing
the full Git tree from archive bytes reproduces `02eeb82…`. There are 103 package `.py`
files, all parsed as AST without importing them, and 26 other package records.
The API commit response reports `verified=false`, `reason=unsigned`; no
independent signature verification was performed. GitHub's archive and API tree
are distinct retained observations from the same hosting authority.

## Dependency declarations and resource observations

The pinned [`pyproject.toml`](https://github.com/SakanaAI/ShinkaEvolve/blob/c4568adde253cacf185be3a8412c3c2142761ebe/pyproject.toml#L24)
declares Python `>=3.10`, backend `setuptools.build_meta`, build requirements
`setuptools>=61.0` and `wheel`, and these 26 runtime requirements:

```text
openai                  numpy                   pandas
anthropic               requests                boto3
pydantic                backoff                 python-dotenv
instructor              python-Levenshtein      radon
unidiff                 dill                    hydra-core==1.3.2
matplotlib              networkx                seaborn
moviepy                 scikit-learn            adjustText
markdown                aiofiles                google-genai
psutil                  httpx==0.27
```

Dev/docs dependency groups at `pyproject.toml:81–96` separately declare test,
formatting, typing and documentation tools; they are not a runtime lock.
The project declares Apache-2.0 and retains `LICENSE` (SHA-256
`c3e5b1c26607caf7208d5a105c113fe240630bb873fdb8ca5b4c2e32c721ddaf`).
No resolver, `pip`, build backend, project import or executable was run. Even the
two equality constraints do not identify wheel/source bytes, platform tags,
transitive requirements, generated code or native libraries. The eventual
closure must account for NumPy/pandas/scientific and other native dependencies,
plus build dependencies and required standard-library/codec modules. Host
packages cannot fill missing entries.

The AST observation also includes names not independently selected by those
direct declarations, such as `rich`, `yaml`, `omegaconf`, `scipy`, `PIL`,
`pygments`, `tiktoken` and `umap`. Some are conditional or may be supplied by
transitive distributions. This review does not infer their versions,
availability or necessity from import spelling. For example,
`embed/embedding.py:83–98` imports `tiktoken` in token counting, while
`core/async_runner.py:20–22` eagerly imports `rich`. A package AST inventory is
not a finite runtime import/native closure.

The 26 non-`.py` records are three extensionless CLI scripts, 15 YAML config
files, two pricing CSVs, three HTML files, two PNGs and one JPG. Their exact paths
and bytes are retained in the archive index and `source-review.json`.
`pyproject.toml:69–79` declares config, pricing and UI package-data globs; no wheel
was built, so source presence does not prove installed package contents.

| Resource route | Observed source behavior | Required profile decision |
| --- | --- | --- |
| Hydra config tree | `launch_hydra.py:33` uses `config_path="configs"`; `configs/config.yaml` selects composed groups. | Pin selected config bytes and fixed composition; do not admit arbitrary Hydra factories or overrides. |
| Model pricing | `llm/providers/pricing.py:12–19,69–70` reads sibling `pricing.csv` through pandas at module import. | Freeze the CSV and access mechanism, even if no pricing UI is exposed. |
| Embedding pricing | `embed/providers/pricing.py:10–17,41–42` similarly loads its CSV at import. | Disabling embedding requests does not itself remove this eager import/resource dependency. |
| Prompts | `core/sampler.py` imports the `shinka.prompts` Python modules; prompts are source constants in this release. | Include the selected prompt source bytes; do not assume OpenEvolve's text-template layout. |
| UI/CLI records | The archive retains UI assets and executable wrappers under `shinka/cli/`; public scripts are separately declared. | Their presence grants no execution. The first finite profile should leave the UI, model-discovery and general CLI surfaces unreachable. |

## Actual entrypoints and initialization

All upstream line references address commit `c4568ad…`.

| Surface | Observed source | Lunar continuation |
| --- | --- | --- |
| Declared scripts | `pyproject.toml:53–57`: `shinka_launch = shinka.cli.launch:main`, `shinka_run = shinka.cli.run:main`, `shinka_models = shinka.cli.models:main`, `shinka_visualize = shinka.webui.visualization:main`. | None is currently a sealed RSI entrypoint. No upstream CLI was executed, including `--help`. |
| Package startup | `shinka/__init__.py:3–7` imports and calls `load_shinka_dotenv`; `env.py:11–26` searches the package parent and launch directory for `.env` and loads them with `override=True`. `llm/client.py:12` calls it again. | Disable ambient dotenv discovery in the eventual profile; endpoint and credential material stays host-only. Merely clearing inherited variables does not close this source route. No user's `.env` was read in this review. |
| Simple run CLI | `cli/run.py:396–405` discovers `evaluate.py` and `initial.*`; `436–498` resolves paths, loads optional YAML and namespace overrides, reads source strings and constructs the runner; `502` calls `runner.run()`. | Replace broad filesystem/config selection with fixed bounded original request/memory grants. A task directory path is not an authoritative RSI input mapping. |
| Hydra launcher | `cli/launch.py:25–28` forwards rewritten argv; `launch_hydra.py:14–16` uses `hydra.utils.instantiate` for job/database/evolution config and runs a runner at `21–30`. | Caller-controlled factories/config targets are outside the finite profile. Do not enable this as an alternate launcher. |
| Eager core imports | `core/__init__.py:1–12` imports runner, sampler, summaries, novelty, evaluator wrapper and prompt evolution. `core/async_runner.py:24–65` imports database, models, embedding, scheduler and edit utilities. | Importing one runner name still crosses this package initializer. Small function selection alone does not establish a small frozen module set. |
| Async run | `core/async_runner.py:955–999` enters `asyncio.run`, creates setup, job-monitor and proposal tasks, and waits for finalization. `_setup_async:1133–1202` creates/loads the database and may generate initial code through an LLM. | Bound all startup, proposal, search and settlement under the original host budget/deadline. Do not silently resume or generate from absent original inputs. |
| Local evaluation | `launch/scheduler.py:125–176` chooses an interpreter, evaluator and arguments, with optional conda or shell activation; `launch/local.py:97–113` copies the environment and starts `Popen`. `core/wrap_eval.py:27–58` dynamically loads candidate code in evaluator work. | These broad interpreter/command/code-loading routes are not the current static loader. Retain Lunar's existing exact evaluator and host process ownership; do not inherit upstream evaluation authority. |

## Request, budget, cancellation and result mapping

Reuse Lunar's existing `producer_broker_ipc.py:ProducerBrokerConfig` and
`serve_producer_broker`, controller request ledger, native owner/terminal,
absolute deadline and bounded anonymous-pipe protocol. This document adds no
DTO, service, broker, transport or public launch seam.

| Route | Actual upstream behavior | Remaining integration gap |
| --- | --- | --- |
| Generation | `llm/query.py:24–60,64–101` creates a provider client and dispatches a query. `llm/client.py:24–107,110–189` constructs synchronous/asynchronous OpenAI, Anthropic/Bedrock, Azure, DeepSeek, Google, OpenRouter or local clients. | A fixed reviewed adapter must build bounded bodies and parse responses through the existing host broker. Do not instantiate direct SDK clients or expose provider selection/credentials inside the target. |
| Protocol differences | `llm/providers/openai.py:171–199` calls Responses create/parse; `providers/local_openai.py:132–138` calls chat completions. `providers/result.py:4–59` produces `QueryResult` with content, history, tokens and estimated cost. | Model protocol and bounded result parsing need an explicit mapping to the host-configured endpoint. A raw broker frame is not automatically a valid `QueryResult`; upstream usage/cost is not host request-count authority. |
| Dynamic destinations | `llm/providers/model_resolver.py:67–75` accepts local model URLs; `local_openai_config.py:22–69,73–84` parses endpoints and selects a key variable. Google helpers also choose API-key/Vertex authentication. | The request must not select a target destination or ambient credential. Keep destination/headers fixed in host configuration. |
| Retry and deadline | `llm/constants.py:1–5` sets 1,200-second SDK timeout, up to 20 backoff tries and a 6,000-second backoff window; `llm/llm.py:14,622–700` adds three outer attempts. | Every actual request/retry must be host-admitted under the original request and total-wall limits. Upstream retry loops cannot create a new budget or extend the deadline. |
| Auxiliary model calls | `core/config.py:35–48` enables meta summaries by interval and defaults embeddings to `text-embedding-3-small`; `embed/embedding.py:420–449` uses a thread for Google embeddings or calls an async embeddings SDK. Novelty, prompt evolution and final summaries are additional source routes. | Disable unreviewed auxiliary routes in the first profile or map each actual request to the same host ledger. Embedding cancellation cannot be inferred from cancelling its awaiting thread task. |
| Headless provider | `llm/providers/headless.py:22–43` defaults to an `npx` command with an environment override; `239–268` runs shell/exec subprocesses and handles its own timeout. | Unpinned package installation, external tools/authentication and alternate commands are outside the first profile; keep this route unreachable. |
| Cost accounting | `core/async_runner.py:816–839` estimates in-flight costs; `2175–2206` stops scheduling at a cost limit while waiting for active work. `1133–1178` restores upstream costs/progress from existing database state. | Keep cost estimates as provenance. Generation counts, cost estimates and upstream resume are not Lunar reservations, original grants or durable recovery; none can refresh host request/deadline limits. |
| Cancellation | `core/async_runner.py:1120–1128,5440–5486` cancels/gathers tasks and cleans up wrappers. `launch/scheduler.py:415–441` returns success after local `kill()` without a child wait/group settlement there; `443–445` shuts down its executor. `launch/local.py:171–191` kills on timeout then loads result files. | These observations do not establish host-acknowledged request cancellation, descendant cleanup or a known native terminal. Reuse Lunar's native lifecycle; missing/uncertain cleanup stays unknown and requires read-only reconcile. |

## SQLite/export compatibility and recovery gap

There is a concrete source-level reason to retain this baseline for review:
`database/dbase.py:420–445` declares all seven fields required by Lunar's
`shinka_handoff.py:_check_schema`: `id`, `code`, `language`, `parent_id`,
`generation`, `combined_score` and `correct`. The static AST-extracted schema
comparison is retained in `selection-and-schema-review.json`. The runner uses
`programs.sqlite` at `core/async_runner.py:1136`, `FOLDER_PREFIX="gen"` at
`core/config.py:16`, `gen_N/main.<ext>` at `async_runner.py:2533–2535`, and copies
the selected generation directory into `best` at `5766–5804`. These observations
match the existing exporter's names; no real SQLite output was generated or
imported in this review, and full executed compatibility is not claimed.

Live snapshot and recovery behavior still need deliberate adaptation:

- `database/dbase.py:406–415` enables WAL. Lunar refuses WAL/SHM/rollback-journal
  sidecars and reads only a quiescent immutable snapshot. A profile must prove
  database/file completion and retain matching source bytes before export; it
  cannot delete a sidecar merely to satisfy that gate.
- `_cleanup_async:5480–5484` closes the async wrapper and scheduler.
  `database/async_dbase.py:1030–1066` cancels monitoring/recomputation and shuts
  down executors; that method does not call `ProgramDatabase.close` on the
  wrapped connection. Therefore the reviewed cleanup call alone is not evidence
  that all SQLite writers/connections have closed or checkpointed WAL.
- `database/dbase.py:309–326,1916–1933` may delete WAL/SHM when the main database
  exists with zero bytes. Lunar unknown reconcile must not invoke those mutable
  recovery routes or discard interrupted evidence. Preserve original evidence
  and use the existing read-only reconciliation policy.
- The `best` tree is removed/replaced during upstream updates at
  `core/async_runner.py:5798–5804`. Read only after settled output; compare the
  chosen source bytes against the selected database row rather than trusting a
  directory name or high producer score.

Retained output should reuse `shinka_handoff.py` and
`python_producer_export.py:read_python_producer_adapter_export`: explicit ordered
program IDs retain selection order; convenience top-k is external search
provenance. Generation, `correct`, score, cost, SQLite IDs and ancestry cannot
create Lunar iteration, evaluation receipt, runtime observation, terminal or
publication authority. Local exact evaluation and existing prepared/publication
boundaries still decide acceptance.

## Remaining acceptance work

This source baseline is useful for an explicit future adapter, while the
unmodified `shinka_run`/Hydra launcher remains unaccepted. Continue by retaining
exact dependency/build bytes and target/ABI, then reviewing a fixed patch set
and its finite import/resource inventory. That profile must consume original
request/memory input, use only the existing host broker, bound output, disable
ambient dotenv/factory/headless/auxiliary egress routes, and establish SQLite
snapshot and cancellation behavior without adopting upstream scores or resume.

Accepted immutable build inputs, same-source static image/startup, original
executable ownership and actual lifecycle/interruption/recovery/drift tests are
still required before native RSI CLI acceptance. No current fixture pins or
loader inventory were changed. No project, model, solver, WebAgent, remote or
company evaluator was run. No shared tasks, backlog or handoff file was changed.
