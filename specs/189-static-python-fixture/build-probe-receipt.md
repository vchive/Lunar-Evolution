# Detached real build probe receipt

Feature189 now has a small parser for the host-side build probe envelope:
`lunar_evolution.static_python_build_probe.parse_static_python_build_probe`.
It accepts one canonical `lunar-static-python-build-probe-v1` JSON receipt and
returns only detached observations:

- independently supplied source archive, source tree, toolchain and recipe
  pins;
- configure and target status, including an explicit optional-module closure
  state and fixed blocker label;
- an optional static ELF format observation bounded by the existing 128 MiB
  image ceiling; and
- runtime `not-run`, `succeeded`, or `failed` status with a fixed failure label.

A runtime `succeeded` observation requires an attempted process, exit code zero,
and no failure label. A `failed` observation requires an attempted process and a
fixed failure label; exit code zero remains allowed because probe validation
can fail after a process exits normally.

The parser rejects duplicate keys, noncanonical bytes, unknown fields, mutable
mapping subclasses, malformed pins, invalid ELF claims, inconsistent blocked or
not-run states, and any true capability claim. It performs no filesystem read,
process launch, compiler invocation, signature check or producer/evaluator
call. The returned receipt therefore cannot authorize installation, runtime,
solver execution, memory promotion, publication or production admission.

The current 5090gpu continuation can be represented as a receipt with
`target_status=succeeded`, `optional_module_closure=open`, an artifact ELF
observation, and `runtime.status=failed` with
`failure=encodings_not_found`. The parser keeps that successful core link and
the startup failure as separate facts; it does not turn the stock image into a
sealed runtime. A future real runtime receipt must still pass the independent
installation descriptor, frozen inventory, loader, target-owner and lifecycle
gates before any acceptance result is produced.
