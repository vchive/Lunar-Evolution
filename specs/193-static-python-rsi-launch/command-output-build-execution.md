# Command-output recipe v2 continuation

This continuation adds an explicit version of the trusted local process recipe
in `execution-backend.md`. It closes a mechanism limitation: recipe v1 admits
generated executables only after a complete stage, so a natural freeze stage
cannot build a helper and then invoke that helper in the same stage. The v2
mechanism observes each command's output group before later commands may use
its executable outputs.

This document supplies no CPython build recipe, real freezer, toolchain closure,
installation, sealed runtime or production admission. A successful inert helper
run is process-mechanism evidence only. The source-preparation scripts keep
their exit-78 refusal, and the controlled build driver remains mock-only.

## Explicit wire and compatibility

`lunar-static-python-pinned-execution-recipe-v1` retains its original schema,
stage-output interpretation and limits. It does not accept dictionary commands
or implicitly allow same-stage generated executables.

The new schema is `lunar-static-python-pinned-execution-recipe-v2`. Its top-level
fields remain exactly `schema`, `preparation_sha256`, `inputs`, `environment`
and `stages`. It uses the same independent recipe/preparation pins, canonical
ASCII JSON plus LF, source/toolchain manifests, explicit environment and original
absolute deadline. The ordered stages remain `configure`, `freeze`, `compile`
and `link`.

Each v2 stage has exactly `stage` and `commands`. Each command has exactly
`argv` and `outputs`; stage-level `outputs` are not accepted. Each output has
the existing exact `path`, `max_size` and `executable` fields. For example:

```json
{
  "stage": "freeze",
  "commands": [
    {
      "argv": ["@toolchain/reviewed-builder", "@work/tools/freezer"],
      "outputs": [{"path": "tools/freezer", "max_size": 8388608, "executable": true}]
    },
    {
      "argv": ["@work/tools/freezer", "@source/reviewed-input", "@work/generated/tiny.h"],
      "outputs": [{"path": "generated/tiny.h", "max_size": 128, "executable": false}]
    }
  ]
}
```

The example illustrates only the dependency wire; it is not an executable
CPython recipe. Actual tool arguments and inputs require their own review.

Limits remain explicit: recipe at most 1 MiB; each role at most 16,384 input
records; aggregate input bytes at most 4 GiB; one input file at most 4 GiB;
at most 256 commands per stage and 512 commands overall; at most 256 argv
strings per command. V2 requires 1–256 outputs per command and at most 256
outputs in aggregate per stage. Each output keeps its declared bound and the
128 MiB ceiling. Combined stdout/stderr stays at most 1 MiB per command.
No input limit is lifted to fit a complete Zig distribution.

## Complete dependency preflight

The complete recipe is checked before workspace creation, copying or child
startup. Output paths are globally unique and cannot overlap as file and
ancestor paths. In every command:

- `argv[0]` names an executable pinned source/toolchain input or an executable
  output declared by an earlier command, including an earlier command in the
  same stage. Its own output cannot authorize its executable.
- Every explicit `@source/path` and `@toolchain/path` argument names a declared
  input. Every explicit `@work/path` argument names an earlier output or the
  current command's declared output destination. Undefined or forward references
  refuse even when their first occurrence is in the last stage.
- Environment references cannot name `@work/path`, because the environment is
  installed before any command output exists.

The preflight executable graph is prospective validation only. It grants no
runtime authority by itself. Literal arguments retain the existing trusted-tool
semantics: the mechanism does not interpret compiler flags or claim that every
path a tool can access appears as an explicit reference. It is not a sandbox.

## Per-command output observation and dispatch

The runner retains its existing snapshots, input-pin verification, process
launcher, shared deadline, bounded logs and direct-child cleanup. No second
executor is introduced. Before a v2 command starts, the runner verifies original
inputs, snapshots and all previously observed outputs. Its executable must also
be present in the runtime set of actually observed executable files.

The runner creates only declared output parent directories using directory
descriptors without following symlinks. Every declared output leaf must be
absent before dispatch; existing files, symlinks or directories refuse without
deletion or replacement. This prepares the fresh trusted-tool workspace and
does not introduce a general custody or ownership mechanism.

After a zero exit, the command remains partial until all declared outputs pass
bounded regular-file byte, digest and executable-mode observation. The runner
then rechecks the entire output group, all prior outputs and original inputs.
Only after those checks does it grant the group's executable outputs to later
commands and mark the command complete. A valid executable followed by a
missing, oversized or incorrectly executable sibling cannot authorize a later
consumer. Source, snapshot or earlier-output drift stops the graph before a
later command dispatches.

The same absolute deadline and interruption callback apply throughout. A stop
between helper generation and its consumer retains the generated bytes and
partial evidence. A stop while a generated child is running uses the existing
kill/reap path. Direct-child reap is recorded separately;
`descendant_cleanup_verified` remains false.

## Retained evidence and validation boundary

V2 terminal reports use `lunar-static-python-build-execution-report-v2`.
Successful command evidence contains its observed `outputs`, and successful
groups also appear in aggregate stage `outputs`. Partial per-command readback
remains visible when a later output fails. A partial command/group does not
complete its stage; no later command or stage runs. Attempt files, snapshots,
logs and partial outputs remain create-only and retained on failure.

All reports keep `configured_closure_verified=false`,
`installation_accepted=false`, `runtime_execution_performed=false` and
`production_admission=false`. Neither a v2 wire nor successful process evidence
is eligible for F01/F02/F03 installation/runtime acceptance.

The independent test file `tests/test_static_python_rsi_execution_backend_v2.py`
uses one compiler-built helper owned by this repository. It copies itself into
an executable output and then emits nine tiny literal header fixtures. These
are not CPython marshal/frozen headers. Tests cover real inert process ordering,
complete preflight, full output-group failure, original/snapshot/output drift,
deadline/cancellation, direct-child reap, fresh-output refusal and v1/schema
limit compatibility. Validation does not acquire, import, build or execute
CPython, Zig, OpenEvolve, Shinka, models or remote evaluators.

Actual configured closure, same-source CPython freezer execution, complete
toolchain inventory, static image/ELF observation, sealed startup and production
CLI remain separately open. Final validation results belong in the central
source-bound validation record after they have actually run.
