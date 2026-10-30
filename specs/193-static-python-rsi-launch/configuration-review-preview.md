# Complete CPython configuration review preview

## Problem and scope

An independent v2 configuration reviewer needs the actual RSI source overlays,
compile roles, frozen-module jobs and all command outputs before approving the
configuration manifest. The previous diagnostic graph described only the
baseline configuration. The actual generator already constructed the complete
graph, but exposed it only after the independent review binder succeeded.

This change exposes that observation through a pure, explicit v2 entry point.
It does not produce approval, execute tools or widen any build/runtime gate.
The native support exporter and all execution backends remain separate.

## API and data contract

`concrete_recipe.preview_cpython_build_review_v2` accepts the preparation,
source inventory bytes and their expected pin, full pinned Zig manifest,
configuration header bytes and their expected pin, the exact eight original
configuration output byte pairs, and the existing optional runtime closure and
producer lifecycle profile. It accepts no review manifest, expected approval
pin, arbitrary callback, compiler override or review-bypass selector. Its v2
include policy is fixed by the entry point.

The result is a frozen `CPythonBuildReviewPreview` containing only
`preview_bytes`. It has no executable recipe, staged source bytes, manifest or
approval-pin property. Its canonical JSON schema is
`lunar-cpython-build-review-preview-v1`, distinct from every execution recipe.
The JSON contains:

- Complete effective `source_inputs` after the actual RSI overlays and the
  eight observed originals, plus separate `generated_sources` byte pins.
- Complete `toolchain_inputs` and the source inventory, preparation,
  configuration header, Zig manifest and runtime closure input pins.
- Exact `configuration_outputs` byte pins, the full four-stage command graph
  with actual output bounds and executable bits, `compile_roles` and
  `freeze_tasks`.
- The solver and selected lifecycle profile, and an
  `observed_concrete_stages_sha256` comparison digest.
- `missing_approval_artifacts: ["configuration/review.json"]` and explicit
  false claims for review approval, review binding, returned executable recipe,
  build, configured closure, installation, runtime, production, immutable
  custody and online publication.

The stage digest describes observations. It is not an independently approved
pin. The preview neither authors nor accepts an approval manifest. The missing
`configuration/review.json` distinguishes its source set from a subsequently
approved recipe. A caller cannot reuse preexisting review metadata or collide
with any of the original-output paths.

Each output pair must use an exact tuple, exact string key and exact nonempty
bytes within the existing output limits. The order and names must be the fixed
eight-output set; `pyconfig.h` must equal the separately pinned header. Key type
checks precede comparisons so user-defined equality methods are not invoked.
Other input pins, source units, runtime overlays and finite lifecycle profiles
go through the same checks used by preparation. The full prospective graph
also goes through the existing dependency validator internally; those
executable-schema bytes are not returned.

## Shared generation and compatibility

The private `_prepare_cpython_graph` mechanically contains the original source
validation, overlay selection and graph generation. Both preview and real
preparation call this one path. The compile-role map is produced alongside the
graph, rather than reconstructed from command output or captured by replacing
the binder.

`prepare_cpython_build_recipe` retains its public signature and original review
selection order. It still selects v2 only from the independently pinned review
schema, runs the original binder, adds its original artifacts and serializes
the recipe and manifest exactly as before. Default, v1 and v2 behavior has no
new opt-in fallback or approval route. The v4 wrapper continues through the
same preparation API.

## Validation and remaining boundaries

Before refactoring, direct pure calls to the existing fixture factories captured
the default/v1/v2 recipe bytes, manifest bytes and every ordered source byte
pin from tree `5ea6210d3587fbe7a58568baeabc47d45fe1a6b5`. The test goldens
fix the hashes of those three byte domains. The fixtures use an explicit inert
Zig identity and synthetic configuration/source records; their v1/v2 binders
run normally. These observations do not approve actual configuration files.

Focused tests compare the preview with an independently bound v2 fixture,
including its actual RSI overlays, native roles and freezer outputs. They also
check all eight originals, input pins, metadata collisions, malformed key
objects, rejection by the execution recipe parser and the unchanged independent
review gate. No binder interception creates a positive review.

Actual OpenEvolve/Shinka previews can now supply a complete human review
packet. Independent review approval, complete driver input closure, a full
CPython build, installed runtime acceptance and solver cases remain subsequent
work and are not established by generating a preview.

## Final affected regression

Frozen `01112fd5` includes all product/test changes before execution. The combined
37-file Linux3.12 batch passed 1,492 unique cases, including the 29 new preview
cases and 83 native-export cases, in 44.113545 seconds including the wrapper.
There were no failures, errors, skips or retries. All 2,760 source files and Git
executable-bit projections matched before/after; Ruff/compileall/diff passed.
The existing CI layout keeps 83 groups and 65 zero-skip groups, with source961
and expected sum7700. Complete source CI and real build/runtime acceptance remain
separate. Evidence lives in primary ignored
`validation/native-support-export-20261030/combined-final/`.
