# Fixed OpenEvolve source profile

Status: implementation of a source preparation slice. This is a continuation of
[project-runtime-profile.md](project-runtime-profile.md), not runtime admission.
The host runtime, broker protocol, two original RSI input grants and native
publication authority remain unchanged. `production_admission=false` and
`online_publication=false`.

## Deliverable

Prepare a finite, reviewable OpenEvolve source tree from the already retained
v0.4.0 archive. The command must neither download nor install packages, import
the prepared project, execute a candidate, invoke a model or run an evaluator.
This work can be completed while the separate P0 release CI is running and does
not depend on KVM access. Building and accepting its executable runtime does.

The upstream identity is commit
`f7b633986c0b3dbd0a171f6eb0cb0f0ba4fdfb0c`, tree
`3b969ae24962dd8aeb379d674d688824adc88508`, retained archive SHA-256
`1e461e7c231e45f7f1b0ce1446fac29ec27e415b3468f29079ec5d3c1826db63`
(3,240,457 bytes). See the original
[source review](openevolve-source-profile-review-20261025.md) for the full
archive/tree review and dependency declaration limits.

The prepared project contains exactly these seven Python modules, the unaltered
upstream Apache-2.0 license and Lunar's original MIT permission notice:

```text
openevolve/__init__.py
openevolve/lunar_fixed.py
openevolve/lunar_fixed_broker.py
openevolve/prompt/__init__.py
openevolve/prompt/templates.py
openevolve/utils/__init__.py
openevolve/utils/code_utils.py
LICENSE
LICENSE.lunar
```

The three package initializers are fixed inert replacements. The template and
code-utility modules retain their exact upstream bytes; the new entrypoint uses
the literal templates and the upstream diff extraction/application and evolve
block protection. The source preparation record distinguishes upstream,
replaced and added files with original/resulting byte identities. `LICENSE`
retains upstream bytes; `LICENSE.lunar` retains the repository's MIT notice for
the added Lunar entrypoint and generated broker source. This finite
project list is not the complete standard-library/native/build closure, nor a
decision to drop upstream distribution dependency or license obligations.

## Existing request and result boundary

The fixed entrypoint consumes only the existing `request.json` and `memory.json`
under `../.rsi-input`. The native host still validates their original manifest,
marker and launch binding. The marker's digest syntax alone does not prove
custody, and the target receives no new manifest/config grant.

The original `SolverRequest.solver_settings` has exactly three supported keys:
`model`, `initial_program` and `task`. The language is Python. No user-selected
module, factory, evaluator, command, provider, template path or checkpoint path
is supported. Only approved, compatible memory contributes bounded prompt
context; the controller retains memory admission authority.

One non-streaming Chat Completions body passes through the existing host broker,
with no retry or tool calls. The host retains destination, credentials, request
ledger and the earlier parent deadline. The target reads only the two existing
anonymous-pipe descriptor handoffs. The body/response mapping is a fixed profile
choice; source tests cannot establish compatibility with a configured endpoint.

The profile caps source at 32 KiB/2,048 lines, task at 8 KiB, memory prompt at
16 KiB/eight records, prompt and reply at 64 KiB, and diff count at 16. Its local
work cap is at most 60 seconds and never extends the original deadline. A
proposal must produce a changed bounded candidate with every diff applied and
the original protected regions preserved. It writes `candidate.py` create-only
and commits the existing `{"candidate_path":"candidate.py"}` wrapper to
`result.json` last. It never executes the candidate.

That wrapper is not `ProducerResultEnvelope`. Independently pinned producer
identity, execution/result observation, original terminal evidence and retained
export/handoff are still required. No timestamps, runtime observations,
evaluation receipts or publication claims may be synthesized from the two input
grants or a successful source-preparation report.

## Broker source and preparation

Generate the target broker module from an explicitly pinned subset of the
current `producer_broker_ipc.py` source. Use fixed standard-library imports,
reviewed constants and the exact reviewed function/class source. Do not import
the Lunar package to obtain the client and do not maintain an unchecked copied
implementation. Changes to the source pin, selected definitions or their global
dependencies require review; arbitrary supplied source is not an accepted
replacement merely because the output records its hash.

The preparation API consumes archive, broker and transport source bytes plus
fixed pinned repository assets; it performs no filesystem writes.
The transport source pin binds the original request/result size constants used
by the generated client. The separate local
CLI reads those files and writes a new output directory create-only. It records
canonical source identities and explicit unaccepted-runtime flags. It rejects
the wrong archive, unsafe/duplicate/special archive members, source drift and
existing output. It does not extract arbitrary archive paths to the filesystem.

From the repository root, prepare a new local directory using the retained
archive; substitute its actual path and an output directory that does not exist:

```sh
python -m tools.openevolve_fixed_profile \
  --archive /path/to/archive-second-download.tar.gz \
  --destination /path/to/new-source-profile
```

The output is source material for subsequent review/build, not an installation
or a runnable accepted Lunar producer. A failed command's partial directory must
not be adopted as a successful source preparation.

## Validation and remaining acceptance

Run one focused selection for the preparer, entrypoint boundary fixtures and
existing broker client behavior. Use synthetic malformed archives and source
mutations for refusal cases; inspect the real retained archive once without
importing it. Entrypoint fixtures may execute Lunar's new adapter with literal
template data and call-forbidden upstream sentinels. Such tests must explicitly
state that they do not test actual upstream diff semantics or runtime startup.
Run Ruff, compileall and `git diff --check` after the final changes; do not repeat
the previous large regression union for this isolated source preparation tool.

The 2026-10-27 focused selection passed 158 unique cases, zero failures/errors/
skips and raw pytest rc0. A read-only metadata check of the retained archive
found 485 regular members at `0664`, 16 at `0775`, and 92 directories at `0775`;
these are raw tar modes, while the previous Git inventory projects executable
bits as `100644`/`100755`. After supporting those original regular modes and
adding two corresponding cases, only the affected preparation file was rerun:
37 cases passed, raw rc0. The two reports cover 160 distinct cases; the 35
repeated preparation cases are not additional coverage. The initial Ruff run
reported three style issues; after fixing them, full Ruff, compileall and diff
checks passed without repeating the full selection.

One actual CLI preparation of the original retained archive succeeded without
importing or executing upstream code. Its canonical source manifest SHA-256 is
`03266224f20d99aaef794cb8c9d8688f9ba8c1d44faf8c46b207c3780d4a6b06`.
Original results and output are ignored local material under the primary
workspace's `.lunar-evolution/validation/feature191-20261027/`
`openevolve-fixed-source-h4y64e03/`. Independent review verified the ten output
files, original archive bytes, all 17 generated broker segments, missing-global
absence and the exact JUnit overlap/union. This establishes source preparation
only; it is not runtime acceptance.

The remaining runtime work is the complete import/native/resource/build closure,
accepted source custody and static image, sealed startup, actual upstream diff
semantics under that runtime, original execution observation and export/handoff,
interruption/recovery and finally runtime-gated production CLI composition.
The existing KVM/isolation limitation remains open; this slice neither bypasses
it nor enables a host-interpreter fallback. P2 distributed ownership and worker
authentication remain deferred.
