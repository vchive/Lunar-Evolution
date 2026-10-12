# Feature 193 — Static Python RSI marker launch source preparation

Status: stage 1 implemented and locally validated, 2026-10-12; final-source CI and
independent audit pending before merge.
Priority P0 prerequisite. This slice prepares reviewed source assets only. It does
not build or launch CPython, complete an installation, consume RSI inputs, or
admit a Python worker.

## Problem and result

Feature 189's current C launcher accepts `argc == 1`. Native RSI input authority
requires the original OS intent argv to end in `--lunar-rsi-input-v1` and the
input-manifest SHA256. Feature 191 now compares actual Python runtime observations
against an independently pinned installation profile, but that comparison cannot
make the existing argc-one launcher accept the native marker.

Add a separate `tools/static_python_rsi_fixture` source-preparation emitter and
CLI, with exactly one version: `rsi-marker-launch-v1`. It emits a finite source
asset set and manifest for later reviewed installation work. Its distinct source
assets make the marker-bearing OS launch shape explicit while retaining the old
fixed Python computation and observation encoder.

## Fixed launch contract

The new C source accepts exactly three OS arguments: the executable argv[0], the
literal `--lunar-rsi-input-v1`, and one 64-character lowercase hexadecimal digest.
Missing, duplicate, reordered, extra, uppercase, malformed or option-like metadata
refuses before Python initialization. No `-c`, `-m`, module, path, program or
fixture-case selector is accepted. The new launcher does not consult
`LUNAR_STATIC_FIXTURE_CASE` or another environment selector.

Keep the existing fixed isolated PyPreConfig/PyConfig source and values. In
particular, observed Python `argv` and `orig_argv` remain
`["lunar-static-python-fixture"]`; OS metadata does not become a Python program
selector or either observed Python vector.

The new fixed frozen entry point is `_rsi_launch(manifest_sha256)`. It independently
requires an exact built-in `str` containing 64 lowercase hexadecimal characters,
then delegates once to the unchanged baseline encoder as `_main("baseline")`.
Invalid metadata refuses before the baseline computation or broker exchange.
The wrapper does not read request, memory, manifest or launch-record files, and
does not emit an RSI result envelope. Digest syntax validation establishes only
the wrapper's argument shape; it does not establish correspondence to input bytes,
launch authority or a consumed request.

## Source preparation contract

Emit exactly six source assets: `launcher.c`, `pipe.c`, `profile.c`, `getpath.c`,
`lunar_fixture_profile.h` and `frozen_main.py`. The launcher and frozen main use
separately reviewed new templates. Other asset bytes come from the unchanged
Feature 189 common templates. Any existing expected frozen-main placeholders may
be filled only from the unchanged finite reviewed profile, never host imports,
filesystem discovery or caller-selected module inventories.

Preparation must first verify fixed SHA256 and size pins for every original common
template, the old launcher and encoder templates, `profile.py`, `recipe.py` and
`reviewed-build-inputs.json`, plus both new source templates. These pins are
reviewed constants independent of the bytes being checked. Refuse drift or missing
source before creating output. A source manifest retains each template/profile/
recipe/input-file pin and each emitted asset's observed size and SHA256. It records
the fixed profile and OS launch policy as source facts.

The CLI uses an explicit local output directory and create-only writes. It refuses
an existing destination instead of replacing it. It verifies the complete written
asset set and manifest by readback. Partial output after an error remains diagnostic
and cannot be reported as completed source preparation. The emitter does not
produce executable build, configure, compile, freezer or runtime drivers, and its
manifest is not an installation descriptor or accepted build-input manifest.

Keep configured closure, build execution, runtime execution, installation acceptance,
input consumption and production admission false in all successful preparation
results. Runtime-load and general-code-origin protection remain false. A digest
of generated C/Python source is not an artifact, frozen bytecode, executable or
runtime observation digest.

## Compatibility and scope

Do not change existing Feature 189 assets, recipe, reviewed build inputs, source
preparation behavior, installation parser or accepted profile. Do not change the
Feature 191 runtime policy, native marker validation, intent/attestation formats,
v2 FD manifest, broker protocol or frame wires. The existing parent-owned native
attempt retains its two read-only request/memory grants; this slice adds none.
Old argc-one fixture behavior remains independently inspectable.

Only local inert source fixtures and fake C/Python API observations are permitted
for this stage. No CPython/toolchain acquisition or real build, static image
execution, model/solver campaign, WebAgent, remote/company evaluator or credentials
are involved.

## Stages and acceptance

Stage 1 is complete only when the create-only source emitter/CLI, independent
source pins, six-asset readback, launcher refusal ordering, wrapper behavior and
unchanged old assets are verified by focused tests, Ruff, compileall and diff
checks. Local fake API tests do not establish runtime success. The final committed
source still requires its own complete CI and independent source/raw evidence
audit before merge.

Later stages remain unimplemented: acceptance of a separately versioned installation
profile; verified source/toolchain/build/frozen-header/ELF closure; actual sealed
image and original owner/native lifecycle acceptance; authoritative marker-to-input
binding and real input consumption; bounded RSI result generation; runtime/post-
execution handoff, publication and durable interruption recovery; actual local
OpenEvolve/Shinka and production RSI CLI/Linux acceptance. Source preparation may
unblock that work but cannot mark it complete. P2 services, authentication,
multi-host ownership and remote evaluation remain outside this feature.
