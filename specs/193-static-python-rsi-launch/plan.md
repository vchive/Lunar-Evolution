# Feature 193 implementation plan

Status: stage 1 implemented with local source-bound verification. The accepted
scope is `spec.md`; API `emit_rsi_launch_source_plan(destination)` and CLI
`python -m tools.static_python_rsi_fixture --destination /fresh/path` are fixed. No old installation profile is widened by this plan.

## Change surfaces

Add only a separate `tools/static_python_rsi_fixture` package, its two reviewed
launcher/frozen-main templates, focused tests and these SDD documents. The emitter
may read the fixed local Feature 189 template/profile/recipe/input files, but it
does not change them or run the old recipe. The new source manifest uses its own
source-preparation schema and sole `rsi-marker-launch-v1` version; it cannot be fed
to an installation parser as acceptance evidence.

The existing common asset inventory is exactly six names. Reuse the four unchanged
common source assets and substitute the two separately pinned new templates.
Maintain independent expected pins for all old templates, profile, recipe,
reviewed build inputs and new templates. Generated source hashes are output facts,
distinct from these independent input pins and from any future executable digest.

## Preparation flow

1. Validate the request and fixed sole version before filesystem effects. Reject
   an existing destination; do not provide a force/overwrite mode or host-runtime
   fallback.
2. Read the finite known source dependencies into bounded snapshots. Check all
   expected sizes and SHA256 values before making the output directory. Unknown
   input names or digest/size drift are errors, not a reason to regenerate pins.
3. Render the new frozen main only from the pinned encoder/profile facts and
   finite reviewed expectations. Generate no frozen bytecode, headers, compiler
   outputs or executable driver. Keep common asset source bytes unchanged.
4. Derive a deterministic manifest from the checked input snapshots and six output
   source payloads. Include source version, finite profile facts, fixed launch
   policy and all capability booleans false. Do not embed a current host Python
   executable, timestamp, locale, environment selector or inferred installation.
5. Exclusively create the destination, six source assets and source manifest.
   Read back every payload and validate the exact expected set, size and digest
   before reporting success. A refusal or write/readback failure cannot return a
   success receipt; retain any partial output as diagnostic evidence.

CLI output reports only source-preparation facts and the output location. CLI
validation and exception normalization must not emit build/runtime success claims.
Keep API and CLI code paths equivalent so one entry cannot skip source-pin or
readback gates.

## Fixed launcher and wrapper

The new C main checks `argc == 3`, exact marker and lowercase hexadecimal digest
before any PyPreConfig/PyConfig or module/pipe work. It has one fixed target module
and callable, `_lunar_static_main._rsi_launch`, and passes the digest as one Python
string argument. Preserve initialization/finalization error handling and the
existing profile functions. It never obtains a case from the environment or
copies OS metadata into `config.argv` or `config.orig_argv`.

The wrapper validates the exact built-in string and calls the unchanged
`_main("baseline")` once. It introduces no imports, file reads, environment reads,
result envelope or alternate fixture-case branch. The old encoder's wire and
baseline computation/broker exchange stay unchanged. Fake runtime tests must
establish that invalid digest input refuses before delegation and that valid
delegation retains actual encoder output under independently supplied inert
`sys`, loader and pipe facts.

## Evidence and compatibility

Freeze old asset/profile/recipe/build-input/parser bytes before editing. Verify
them unchanged after implementation; source preparation cannot silently amend
Feature 189 acceptance. Test the distinct launcher with inert C API stubs and the
wrapper with fake Python facts. These are source/behavior checks and must be
labeled as such; no compiled CPython or sealed image is involved.

Run focused tests, Ruff, compileall and `git diff --check` on the final source.
Retain initial failures and final source-bound results separately. Add a bounded
CI selection only after the implementation's focused module is known. Complete CI
and raw/source/tree verification remain the merge gate owned by the parent task.

## Follow-on stages

Stage 2 separately accepts a new installation profile and closes matching
source/toolchain/frozen-header/static-link/ELF evidence. Stage 3 verifies the real
sealed image, original executable owner, native lifecycle and marker-bearing OS
intent against fixed Python observations. Stage 4 consumes exactly the existing
request/memory grants and produces a bounded producer result with independently
verified input/output authority. Stage 5 composes runtime/post-execution handoff,
publication, budgets and durable interruption recovery, then actual local solver
and production CLI/Linux acceptance. None of these stages is implemented or
accepted by the stage 1 source emitter; each needs a separate contract and tests.

Remote evaluation, services, distributed scheduling, worker authentication and
multi-host ownership remain deferred P2 work.

## Controlled build-driver continuation

The next bounded slice consumes the canonical
`RSIProfilePreparation` produced by `prepare_rsi_installation_profile`; it does
not regenerate source assets or accept a user dictionary as a build plan. The
independent preparation digest and source-plan pins are checked first. The
candidate is copied into fresh built-in containers before each trusted mock
backend call. The graph is fixed as configure, freeze, compile and link, with
the unclosed-configuration gate before freeze and an exact nine-header gate.
Mock closure is labelled synthetic and cannot promote any actual build,
installation, runtime or production claim. A real backend requires a later SDD
after observed G1/G2 evidence.
