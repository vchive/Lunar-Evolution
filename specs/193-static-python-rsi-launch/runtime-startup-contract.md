# F03 runtime startup and loader-negative contract

This contract is the provider-free boundary for the next static-Python RSI
stage. It compares caller-owned canonical JSON bytes; it does not start a
process, inspect an ELF file, read `/proc`, access a filesystem, or establish
installation, owner, input, or production authority.

The schema is `lunar-static-python-runtime-startup-v1`. It binds the runtime
observation to the F02 build-closure, the installation binding, and the launch
intent through three SHA-256 pins. The wire contains the exact argv and native
marker shape, a fixed startup observation, loader-negative fields, executable
device/inode/mode metadata, bounded lifecycle events, and capability claims.
Every claim is required to remain `false` in this stage.

The OS argv must match the reviewed launcher: exactly the relative executable
path, `--lunar-rsi-input-v1`, and the marker's 64 lowercase hexadecimal digits.
The fixed entry point is `_lunar_static_main._rsi_launch`; no alternate program,
module or callable is permitted. The executable record must name argv[0] and
have an executable permission bit. Baseline exits with code zero; loader refusal
has a nonzero code. The two lifecycle events must be `started` followed by the
case's terminal event. These are consistency gates, not process observations.

Two synthetic cases are supported:

- `baseline` requires an `exited` terminal, no `PT_INTERP`, no `DT_NEEDED`, and
  an empty dependency list.
- `loader-negative` requires a `loader_refused` terminal and at least one
  loader violation (`PT_INTERP` or `DT_NEEDED`).

The comparator rejects non-canonical JSON, duplicate keys, non-finite values,
absolute or traversal paths, duplicate/unsorted dependencies, invalid owner
integers, pin drift, lifecycle mismatch, and any claim set to `true`. Returned
data is an immutable DTO containing the original canonical bytes. This slice is
not evidence that a sealed image was built or that either fixture was executed.

The module also exposes a separate `lunar-static-python-runtime-startup-
diagnostic-v1` helper for controlled-build failure triage. It accepts only
bounded stderr bytes plus an independently supplied SHA-256 pin and emits the
stderr digest/size, a fixed failure code, and `phase="startup"`. The fixed
codes include `missing_encodings`, `missing_import_bootstrap`,
`getpath_configuration`, `unknown_startup_failure`, and `no_stderr`; no raw
stderr is retained. Its claims explicitly keep
`runtime_execution_performed=false` and `production_admission=false`. This
diagnostic explains a failed build probe such as CPython's missing `encodings`
bootstrap, but it does not convert that failure into startup, owner, lifecycle,
or production evidence.
