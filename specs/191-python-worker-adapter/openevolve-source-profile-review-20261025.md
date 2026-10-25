# OpenEvolve v0.4.0 source-profile review

Status: source archive/tree and dependency **declarations** retained, statically
reviewed and independently rechecked on 2026-10-25. This completes only the
source/declaration portion of step 1 in
[project-runtime-profile.md](project-runtime-profile.md). Dependency bytes,
the finite executable profile, image, loader policy, actual project execution
and runtime acceptance remain open. `production_admission=false`.

## Frozen upstream source

The reviewed public release is
[OpenEvolve v0.4.0](https://github.com/algorithmicsuperintelligence/openevolve/releases/tag/v0.4.0),
published at `2026-09-28T03:29:34Z`. The observed lightweight tag resolves directly
to commit `f7b633986c0b3dbd0a171f6eb0cb0f0ba4fdfb0c`; the commit names Git tree
`3b969ae24962dd8aeb379d674d688824adc88508`.

The retained archive was fetched from
`https://api.github.com/repos/algorithmicsuperintelligence/openevolve/tarball/f7b633986c0b3dbd0a171f6eb0cb0f0ba4fdfb0c`.
Its identity is the retained bytes, rather than a promise that a later generated
GitHub archive has the same compression or wrapper directory.

| Retained item | Bytes | SHA-256 |
| --- | ---: | --- |
| `archive-second-download.tar.gz` | 3,240,457 | `1e461e7c231e45f7f1b0ce1446fac29ec27e415b3468f29079ec5d3c1826db63` |
| `archive-source-index.json` | 131,131 | `ae91ac343874dc62f2a4c8585861dd0459dcfd6cd654663b41c785b9f2b94bb6` |
| `git-tree.json` | 162,484 | `34c1f88cae7bbeb6f2fc4316f9a8dec1677bdd152ef20e28aa02387319b8ba7b` |
| `commit.json` | 9,380 | `a5d01aab6ac166bb410e1acd16b939ace3173304501bf06f6b7a3686077700a0` |
| `source-review.json` | 3,003 | `e9b2ad11843194dc897328b068d038d9c8b4f5064e97344a444180b1d68dba03` |
| `package-static-imports.json` | 29,021 | `d72ddd43d1078dc73131daf944ca0d301eb9fb9e9467ba496cea350e07b95633` |
| `static-review-recheck-v2.py` | 4,182 | `b3b4f27359f59ba245065af23d26e0cc41689084d260ccade20d32a056cc4c4a` |
| `static-review-recheck.json` | 1,232 | `4557fb7ccda61d7be30e63877a46fd223fe0130a21f5821decf996ba87931e57` |

The separate `root-independent-review.json` receipt has SHA-256
`1422986ca06658fad90278aea33e4f8867227f34499dba9e807bdf5a7d582b99`.
Its independent review verified every entry of `evidence-index.json`
(SHA-256 `78d8725e6ec69bca4b214a4c9bef810d39b06532821e41a45aafb73faa94c8aa`),
all 501 archive/API blobs and the reconstructed full Git tree, the 31 package
Python AST observations, 14 prompt resources, dependency declarations and script
entry. This accepts those source/declaration facts only; dependency byte closure,
executable profile and runtime acceptance are not established.

Raw evidence is ignored local material under
`.lunar-evolution/validation/feature191-20261025/openevolve-source-freeze-kpnc07mz/`
in the primary workspace. The archive index records every regular file's path,
size, mode, SHA-256 and Git blob SHA-1. Standard-library tar reading found exactly
501 regular files, 7,798,021 file-content bytes and modes `100644`/`100755`, with
no archive symlink, hard-link or special-file member. Every regular file matches
the independently fetched recursive API tree by path, mode, size and blob hash;
the API tree is not truncated. Rebuilding all directories from the archive file
bytes reproduces the commit's complete Git tree, `3b969ae…`.

GitHub's commit response reports `verification.verified=true` and `reason=valid`.
This is retained API metadata, not an independent signature verification or a
source trust guarantee. The archive and tree API also share a hosting authority.

The first codeload acquisition timed out before producing an archive. Its
failure remains in `first-archive-acquisition-failure.json` (SHA-256
`ddbcdeef764371f8fd48a17872cf3c31c5d90e5c73bb6acdba26c710cf4aba46`).
The subsequent API archive acquisition succeeded. The first saved recheck script
also failed on an incorrect assumption about the Git commit response's JSON
shape; that script and `static-review-recheck-v1-failure.txt` are retained. The
corrected `static-review-recheck-v2.py` completed successfully and created the
separate recheck result above. Neither failure was an upstream execution or
solver attempt.

## Declared dependencies and remaining byte closure

The pinned [`pyproject.toml`](https://github.com/algorithmicsuperintelligence/openevolve/blob/f7b633986c0b3dbd0a171f6eb0cb0f0ba4fdfb0c/pyproject.toml#L1)
declares Python `>=3.10`, build backend `setuptools.build_meta`, build requirements
`setuptools>=42` and `wheel`, and these direct runtime requirements:

| Declaration | Static observation in this source |
| --- | --- |
| `openai>=1.0.0` | Imported by `llm/openai.py:17` and `embedding.py:10`; both contain direct SDK calls. |
| `pyyaml>=6.0` | Imported as `yaml` by `config.py:12`. |
| `numpy>=1.22.0` | Imported by `database.py:22`, the controller's seeded branch at `controller.py:78`, and trace-export utilities. |
| `tqdm>=4.64.0` | Declared requirement; no `tqdm` import occurs in the AST observations of the 31 package Python files. |
| `flask` | Declared requirement; no `flask` import occurs in that same package AST observation. |
| `dacite>=1.9.2` | Imported by `config.py:11` for configuration conversion. |

The absent package imports for `tqdm` and `flask` do not authorize dropping those
declared dependencies. The dev extra separately declares `pytest>=7.0.0`,
`pytest-asyncio>=0.21.0`, `black>=22.0.0`, `isort>=5.10.0`, `mypy>=0.950`,
`requests>=2.28.0` and `pre-commit>=4.5.1`; it is not the runtime lock.
The project declares Apache-2.0 and retains the Apache 2.0 `LICENSE` bytes
(SHA-256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`).

No dependency resolver, package installation, package metadata execution or
project import was run. These lower bounds do not select exact dependency
versions, source archives, wheel tags, transitive dependencies, generated code,
licenses, NumPy/native-library closure, or build dependencies. No current host
package is accepted as a substitute. A later step must retain those actual
bytes for a chosen target/ABI and prove the static build and loader closure.
This review therefore does **not** complete step 1 as a whole.

## Actual entrypoints, imports and resources

All upstream line references below address commit `f7b6339…`. The package contains
31 `.py` files; their AST import/from observations are retained without executing
them. This is a source observation, not a complete transitive, conditional,
dynamic-import or native dependency inventory.

| Surface | Observed upstream behavior | Consequence for a Lunar profile |
| --- | --- | --- |
| Console entry | `pyproject.toml:49–50` maps `openevolve-run` to `openevolve.cli:main`; `openevolve-run.py:5–9` forwards to the same main. `cli.py:174–181` calls `asyncio.run(main_async())`. | The upstream console launcher is not the fixed Lunar RSI entrypoint. Do not enable arbitrary upstream argv. |
| CLI inputs | `cli.py:22–58` accepts initial-program/evaluator/config/output paths, iteration/score limits, checkpoint and provider/model overrides; `main_async:81–135` loads config, creates `OpenEvolve`, optionally loads a checkpoint and runs it. | These path and configuration freedoms need a finite, reviewed mapping from original request/memory grants. They cannot become a factory/module/command selector. |
| Package import | `openevolve/__init__.py:5–14` eagerly imports config, controller and API. `controller.py:15–25` imports database, evaluator, trace, ensemble, process parallelism, prompts and utilities. | Importing a narrowly named submodule still passes through the package initializer; a future profile cannot infer a tiny closure from one function name. |
| Library API | `api.py:35–46` exposes `run_evolution`; `api.py:118–225` prepares inputs, constructs the controller and may clean up temporary outputs. `_prepare_evaluator:309–391` supports source generation from a callable. | This is a second broad input surface, not a ready sealed entrypoint. Initial implementation should not accept callables or code/factory strings. |
| Controller | `controller.py:121–145` constructs generation and evaluator LLM ensembles, prompt samplers, database and evaluator. `run:232–400` evaluates the initial program and starts `ProcessParallelController`. | The full upstream loop has more behavior than proposing a single candidate; profile adaptation and host ownership must be reviewed before execution. |
| Evaluator import | `evaluator.py:75–107` inserts the evaluator directory into `sys.path` and uses `spec_from_file_location`/`exec_module`. `evaluate_program:140–178` writes generated code into temporary files; `_direct_evaluate:339–366` calls the supplied evaluator in a thread. Cascade evaluation loads the module again at `368–403`. | Caller-selected evaluator modules and unrestricted `sys.path` mutation are incompatible with the current frozen loader. Pin or replace that route; do not grant it publication authority. |
| Parallel workers | `process_parallel.py:46–103` reconstructs config and imports parent environment; `105–138` lazily creates fresh ensembles/evaluator. `start:526–554` copies `dict(os.environ)` into `ProcessPoolExecutor` initargs. `_run_iteration_worker:205–213` calls the LLM from a worker. | `parallel_evaluations=1` still uses a process pool. It does not establish a single-process, host-brokered profile. Worker startup, inheritance and pipe serialization remain unreviewed execution work. |
| Templates | `prompt/sampler.py:24–26` creates `TemplateManager`. `prompt/templates.py:178–215` derives defaults from `__file__`, reads `*.txt` and `fragments.json`, then allows a custom directory to override them. | Freeze the actual resource bytes and read mechanism. A frozen module without a suitable resource origin cannot be assumed to make these reads work. Custom templates must not introduce ambient paths. |

`pyproject.toml:62–63` and `MANIFEST.in:1–2` declare prompt package data. The
archive has these 14 non-Python package resources under
`openevolve/prompts/defaults/`:

```text
diff_user.txt
evaluation.txt
evaluator_system_message.txt
evolution_history.txt
fragments.json
full_rewrite_user.txt
inspiration_program.txt
inspirations_section.txt
previous_attempt.txt
system_message.txt
system_message_changes_description.txt
system_message_with_changes_description.txt
top_program.txt
user_message_with_changes_description.txt
```

The archive index pins each resource independently. No resource was omitted on
the assumption that its default is duplicated in Python. The eventual module
and resource inventory must also include the chosen dependency bytes, required
standard-library/codec modules and generated/static material; these 31 modules
and 14 resources are not that full closure.

## Broker, budget and result mapping

The existing host boundary is `ProducerBrokerConfig`/`serve_producer_broker` in
`src/lunar_evolution/producer_broker_ipc.py`, with controller-owned request ledger,
fixed destination, original absolute deadline and bounded anonymous-pipe frames.
Credentials stay in the host config. The target sends bounded request bodies;
the host journal and native lifecycle, rather than upstream counters, establish
request and terminal evidence. No second broker, protocol, DTO or ledger is
introduced by this review.

| Upstream route | Observed source | Required continuation before accepting a profile |
| --- | --- | --- |
| Generation/model selection | `llm/ensemble.py:34–41` accepts `init_client`, provider registry or default OpenAI; `83–97` delegates generation. `llm/base.py:9–22` defines the async generation interface. | A fixed, reviewed implementation may map that interface to existing broker frames. Do not expose `init_client` or registry selection through requests; do not claim a callback alone closes imports or worker inheritance. |
| Direct model HTTP | `llm/openai.py:84–91` constructs `openai.OpenAI`; `215–224` calls `client.chat.completions.create` from an executor. `config.py:21–47` resolves environment-key references; `521–532` can take provider settings from the environment. | Remove/disable direct SDK egress in the selected execution profile; host broker owns destination and credentials. Unmodified upstream OpenAI behavior is not accepted. |
| Retry and timeout | `llm/openai.py:183–212` has an outer retry loop, while `84–90` also passes retry settings into the SDK. Manual mode at `259–317` writes/polls answer files and can wait without a timeout. | Count every actual request against the existing host budget; preserve the original total deadline. Manual queues and unbounded polling stay disabled. Upstream retry/iteration counts cannot replenish Lunar budgets. |
| Embeddings and novelty | `database.py:229–237` imports `EmbeddingClient` and conditionally creates it. `embedding.py:48–80` selects OpenAI/Azure/Gemini clients from environment; `102–104` calls the embeddings endpoint. | For the first bounded profile, keep embedding-based novelty disabled unless its requests have an independently reviewed mapping to the existing host broker and budget. Removing environment keys alone does not implement that mapping. |
| Optional CLI providers | `llm/ensemble.py:20–31` registers local CLI providers. `llm/claude_code.py:67–82,115–123` builds `claude` argv and runs it; `llm/copilot_cli.py:115–156` similarly runs `copilot`, optionally with `--allow-all-tools`. | These executable/tool/authentication closures are outside the first profile. They must remain unreachable rather than being used as alternate broker clients. |
| Upstream evaluation | `evaluator.py:140–178,339–403` loads/runs the configured evaluator; optional LLM feedback is applied in `195–225`. | Any upstream search feedback is producer provenance. Existing Lunar local exact evaluation remains the only candidate acceptance path; no remote evaluator is added. Arbitrary evaluator execution is not authorized by a source pin. |
| Checkpoints and result | `controller.py:430–479` writes checkpoint best-program source/metadata; `523–570` writes `best/best_program<suffix>` and `best_program_info.json`. `database.py:724–844` saves/loads programs and metadata. | Pin retained output bytes and choose one candidate explicitly. An upstream checkpoint is not Lunar durable resume or an acknowledged native terminal. |

Lunar's existing `openevolve_handoff.py:_parse_result` expects a wrapper object
containing `candidate_path` and optionally `evaluation`. The upstream best-program
metadata is a different shape. A future fixed adapter must produce the existing
bounded wrapper/envelope from retained source and metadata, then reuse
`python_producer_export.py:read_python_producer_adapter_export`; it must not
pretend the upstream CLI already emits this wrapper. External metrics,
generation and rank remain untrusted provenance and cannot create a Lunar
evaluation receipt, runtime observation, terminal or publication claim.

## Finite entrypoint decision and open work

The reviewed material supports choosing OpenEvolve v0.4.0 as the **source
baseline to continue reviewing**. It does not support accepting the unmodified
CLI or `run_evolution` API as the sealed executable profile. The smallest useful
first profile should fix one entrypoint, consume the original bounded
request/memory grants, propose one bounded candidate through the existing host
broker, and emit the existing retained wrapper. It should disable upstream
arbitrary evaluator loading, custom factories, external CLI providers, manual
queues, embedding egress and unreviewed checkpoint inputs. This is an adaptation
direction, not a selected module list, implemented entrypoint or accepted image.

Before implementation can be accepted, the continuation still needs:

1. Exact direct/transitive/build dependency bytes for one chosen target/ABI,
   native-library/generated-code inventory, and reproducible build provenance.
2. A reviewed patch set against this exact source baseline, with old/new byte
   hashes, and the resulting finite import/resource/loader inventory. No patches
   to upstream source were made in this review.
3. Resolution of evaluator and process-pool routes, authoritative input reads,
   prompt-resource access, broker request/response parsing and result capture.
4. Accepted immutable build-input custody, same-source static image, startup
   observations and original executable ownership from Features 189/190/193.
5. Actual accepted-runtime lifecycle and interruption/recovery/drift tests, then
   runtime-gated RSI CLI composition. Neither static AST parsing nor a retained
   exporter is a substitute for this evidence.

No upstream command, `pip`, imported package, solver, model call, evaluator or
campaign was run. No existing fixture profile, pins, public API, tasks, backlog
or handoff state was changed. The current runtime and native CLI gates remain
in force.
