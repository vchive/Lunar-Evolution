# Project lifecycle profile preflight (P1)

This slice defines the input contract for a future single-project OpenEvolve or Shinka
lifecycle. It is deliberately provider-free: `ProjectLifecycleProfile` only validates a
canonical detached JSON declaration and `rsi project-preflight` only reads that file.
Neither path imports project code, starts a producer, invokes an evaluator, opens an RSI
ledger, creates a process registration, or publishes a candidate.

## Profile contract

The profile uses protocol `lunar-rsi-project-lifecycle-profile-v1` and contains exactly:

- `producer_id`: `openevolve` or `shinka`;
- `project_id` and relative `entrypoint` identifiers;
- SHA-256 pins for source, runtime, toolchain, request schema and result schema;
- fixed lifecycle modes: `native_bootstrap`, `owner_group`, and `retained_read_only`.

The mode fields are intentionally closed. A future launcher cannot smuggle a shell command,
ambient interpreter, cooperative-only cancellation, or automatic retry semantics through this
profile. The digests identify bytes but are not evidence that those bytes were executed.

## CLI

```bash
lunar-evolution rsi project-preflight PROFILE.json --json
```

An independently retained digest can be supplied with `--profile-sha256`. A valid declaration
returns `status=blocked`, `reason=runtime_acceptance_required`, the four missing gates, and
`execution_performed=false`, `evaluator_invoked=false`, `production_admission=false`, and
`online_publication=false`. The non-zero status is intentional: profile shape is necessary but
cannot authorize a launch.

The remaining gates are an accepted runtime profile, a trusted project entrypoint, a runtime
lifecycle interruption matrix, and Linux acceptance. Once those are independently accepted, a
later P1 slice may consume this profile in the existing native scheduler and receipt mapper.
Until then, `rsi run|resume --solver-execution native-producer` keeps its existing pre-I/O
refusal and the provider-free fixture remains the only executable CLI path.

Focused coverage is in `tests/test_rsi_project_lifecycle.py`. It checks strict shape and path
validation, digest drift, non-admission markers, and that the CLI preflight does not initialize a
home or SQLite ledger. With `--diagnostics`, the report also contains a fixed `lifecycle_matrix`
for startup, normal completion, cancellation, deadline, parent loss, missing terminal, callback
failure, cleanup uncertainty, restart/recovery, source drift and result drift. Each row is a
blocked requirement rather than an observed runtime result, and keeps
`execution_performed`, `evaluator_invoked`, `production_admission` and `online_publication`
false.

## Provider-free entrypoint composition

`lunar_evolution.project_entrypoint_descriptor` adds a detached descriptor seam for that future
launcher. `build_project_entrypoint_descriptor()` binds the canonical profile digest to its
producer/project IDs, exact relative entrypoint, one-element no-shell `argv`, working/output
directories, and distinct request/result filenames. Absolute paths, parent/dot path segments,
nested request/result filenames, arbitrary command arguments and lifecycle-mode drift are
rejected. The descriptor is content-addressed and reparsed before use.

`compose_project_entrypoint_lifecycle()` then binds the descriptor back to the complete profile
and a parsed retained lifecycle diagnostic. Its adapter report carries profile, descriptor, and
lifecycle-report digests, while remaining `status=blocked` with
`reason=runtime_acceptance_required`, `production_admission=false`, and
`online_publication=false`. An `offline_verified` lifecycle diagnostic only removes the
provider-free lifecycle-evidence gap; it does not prove accepted CPython, trusted entrypoint
bytes, authoritative input/result mapping, Linux acceptance, or producer admission. This is an
API contract and evidence-composition slice only: it does not load project code, launch/cancel a
producer, inspect a workspace, or initialize controller state. Regression coverage is in
`tests/test_project_entrypoint_descriptor.py`.
