# Fixed Shinka source profile

Status: source preparation continuation of Feature191. This slice does not
admit a runtime, run an upstream project or enable production CLI composition.
It builds on the retained v0.0.7
[source review](shinka-source-profile-review-20261025.md) and the existing
read-only Shinka exporter. It does not start Hydra, the async runner or a provider
SDK. `production_admission=false` and `online_publication=false`.

## Contract and useful behavior

Prepare ten Python modules from the exact retained v0.0.7 archive, commit
`c4568adde253cacf185be3a8412c3c2142761ebe`, tree
`02eeb82bf432c312f0c87d9379a4d96c65870b08`, archive SHA-256
`4a9c242de0b2b316013ed7ee1b3ebc8a94a6bf6098e7e370fadd5b94201e1d67`
(9,450,712 bytes):

```text
shinka/__init__.py
shinka/edit/__init__.py
shinka/edit/apply_diff.py
shinka/edit/marker_validation.py
shinka/lunar_fixed.py
shinka/lunar_fixed_broker.py
shinka/prompts/__init__.py
shinka/prompts/prompts_diff.py
shinka/utils/__init__.py
shinka/utils/languages.py
LICENSE
LICENSE.lunar
```

The four original package initializers become inert, preventing ambient dotenv,
scientific/database/runner imports and general upstream routes. The four other
upstream modules retain their exact original bytes. The fixed entrypoint uses
Shinka's actual diff prompt, `PATCH_PATTERN`, `apply_search_replace(...,
strict=True)` and `validate_evolve_markers`. It does not use the broad
`apply_diff_patch` filesystem wrapper, whose whitespace normalization could alter
immutable text. Only one well-formed Python evolve block is accepted; the
candidate must preserve its original immutable prefix/suffix bytes exactly.

The entrypoint reads only the existing `../.rsi-input/request.json` and
`memory.json` grants. The request has solver `shinka` and exactly the existing
settings `model`, `initial_program`, `task`. Approved compatible memory supplies
bounded untrusted prompt context. Preparation compares its shared input,
memory and descriptor-file validation ASTs to the pinned OpenEvolve boundary
asset; only the fixed solver/error labels and added single-region check may
differ. A second unchecked boundary implementation is not accepted. No evaluator, endpoint, provider, factory,
checkpoint, template path or extra grant is selectable. The original host still
owns custody/marker/manifest/launch binding, deadline and request ledger.

Make at most one non-streaming Chat Completions request through the existing
host broker. Reuse `tools.openevolve_fixed_profile.prepare.generate_target_broker`
and its exact current Lunar source pins; do not duplicate the client or import
the Lunar package inside the target. All source, prompt, reply, JSON, memory,
diff and local time bounds match the fixed OpenEvolve profile: 32 KiB/2,048 source
lines, 8 KiB task, 16 KiB/eight memory entries, 64 KiB prompt/reply, sixteen diff
blocks, at most sixty seconds without extending the original parent deadline.

## Actual existing Shinka output boundary

A valid changed proposal writes `gen_0/main.py` create-only. The target then
creates a small in-memory SQLite database with the existing seven `programs`
columns, serializes it, closes its only connection and writes `programs.sqlite`
create-only last. No WAL, SHM or rollback sidecar is created or deleted.
The database row is fixed `id='proposal'`, `language='python'`, `parent_id=NULL`,
`generation=0`, `combined_score=NULL`, `correct=0`. Its `code` bytes must equal
the retained generation source exactly. The zero correctness flag asserts no
successful evaluation; no evaluator has run and no score is invented. A local
schema-generation label is not a Lunar iteration, accepted lineage or producer
identity.

The existing exporter already supports explicit ordered program IDs even when
`correct=0`. Consumers must use `program_ids=['proposal']`, `top_k=None`; its
convenience top-k path deliberately does not select this unevaluated proposal.
No new solver-result DTO is introduced, and source preparation itself produces
no SQLite/candidate output. Independently retained producer fingerprint,
original terminal/runtime observations, existing generic envelope, source
custody, exact evaluation and export/handoff remain necessary for admission.
This source profile never invents those records from grants or source output.

## Preparation interface

`prepare_shinka_sources(archive_bytes, *, broker_source_bytes,
transport_source_bytes)` consumes explicit bytes and fixed pinned assets,
returns immutable source records plus canonical manifest bytes, and writes
nothing. Verify the full archive SHA/size before bounded all-member inspection;
reject unsafe, duplicate, special or out-of-bounds members, mismatching original
source pins and Lunar broker source drift. Record all old/new source identities,
the generated broker segment records, original Apache license, Lunar MIT notice
and explicit unaccepted-runtime flags. Full standard-library/native/build
closure is unverified; in particular SQLite availability/serialization and
native dependencies need the later sealed build/runtime acceptance.

```bash
python -m tools.shinka_fixed_profile \
  --archive /path/to/retained/archive.tar.gz \
  --destination /path/to/new-shinka-source-profile
```

The separate source-only CLI does bounded nofollow regular-file reads, creates
a new output tree without overwriting caller files, writes its source manifest
last and emits fixed error codes without raw paths/content. It has no download,
install, run, model, build or evaluator option. Failed partial output is retained.

## Validation and remaining work

The 2026-10-27 centralized twelve-file batch covers 366 distinct cases, all latest
outcomes pass after affected-only synthetic-test/style checks. A final asset EOF
normalization preserves its AST and updates its pin; only the three Shinka test
files are rechecked (91 pass). Final Ruff, compileall and staged diff checks pass.
The actual retained archive's final asset-version CLI preparation produces all
thirteen source/notice/manifest files, manifest SHA
`5a6e716142cf71d944adbc7e1622cb1a147f7ef9eaba556e9bb1f707680ecffa`.
See [batch validation](../197-external-worker-coordination/validation.md) for the
original failure retention, exact report identities and acceptance limits.

Before final integration, use synthetic tar/member/source mutations and
source-only adapter tests with synthetic prompt data, forbidden upstream
sentinels or explicitly artificial diff doubles. Tests may execute the new
adapter and existing Lunar client with local inert data, never actual upstream
functions. Exercise changed-candidate orchestration, immutable boundaries,
request/refusal/deadline behavior, original current/legacy memory wires,
create-only generation/database order, serialized SQLite schema/content,
quiescent snapshot reads through the existing exporter and default top-k refusal.
Inspect the actual retained archive once without importing it. Root performs the
final focused test union, Ruff, compileall and `git diff --check` after parallel
slices finish.

The remaining work is sealed closure/build/startup, actual upstream diff
semantics and broker protocol compatibility under that runtime, original
execution observation and unknown/reconcile behavior, interruption/recovery,
export/handoff and runtime-gated production CLI composition. The current KVM
limitation remains open. No host-interpreter fallback, remote evaluator or
multi-machine ownership/authentication work is added here.
