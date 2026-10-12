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

