# Driver input custody: next implementation prerequisites

Status: design only. No tracer, runtime, execution entry point or receipt schema
is added. No build, solver, model or evaluator was run. Existing consumer defaults
and acceptance claims are unchanged.

## Why production composition cannot yet be connected

`PythonProducerRSIExecutionConfig` in `src/lunar_evolution/rsi_producer_gateway.py`
requires the original `PythonRSISchedulerInputContext`, the controller's same
ledger, native failure ledger and late execution handoff. It does not construct
an accepted runtime from a directory or detached installation descriptor.
`require_fixture_rsi_cli` rejects `native-producer` before contract/ledger I/O;
`cli.py::_rsi_run_payload` constructs the explicit fixture gateway.
`trusted_bootstrap_runtime.py` uses `sys.executable` for a provider-free fixture,
which cannot supply the missing accepted static runtime. Feature193 F02c and
actual F03–F06 remain open. Another configuration DTO would not close them.

## Selected implementation order and custody requirements

This document selects no new environment. The existing enforced Linux input-view
boundary must become available and be independently accepted first. The
unselected VM alternative in `../189-static-python-fixture/build-vm-custody.md`
remains design only; installed QEMU or TCG availability is insufficient.

The required custody mechanism must bind the complete original archive bytes to
one protected input view before the first consumer starts, and preserve both
contents and namespace through all driver/helper/descendant lifetimes. It must
prevent source replacement, writable aliases, alternative mounts/views and
external input access. Original held identities remain live until the complete
original chain is drained; hashes before/after or chmod on ordinary copies are
insufficient. Writable generated outputs need a distinct bounded view and an
explicit publish/protect transition before any later command consumes them.

Before execution, independently freeze the complete configured input universe:
source, compiler and linker executables, their loaders/libraries if any, helper
executables, build resource tree, target headers, config/response files, implicit
CRT/support libraries, linker scripts and generated output dependencies. Unknown
paths and unapproved cache products refuse; discovery cannot approve its own
current digests.

`run_dependency_checked_build` already executes the original v3 runner once,
reads its original persisted report and outputs, and compares actual C/LLD
depfiles against source/toolchain and earlier-work inventories. It supplies real
process/byte comparison. It does not enumerate every driver input or prove the
bytes consumed before post-execution readback.

A pinned static `strace -f` wrapper could reveal omitted config, helper, CRT and
cache paths, but file-named syscall logs do not establish complete consumed
inputs. Inherited/transferred FDs, fd-based reads/mappings, metadata effects,
io_uring/ABI coverage, unfinished events and namespace changes require explicit
semantics. Tracing also cannot make a mutable input view immutable. Therefore
this continuation does not add a diagnostic-only parser and label it custody.

If an observer is needed for the accepted mechanism, its contract must cover
original task/exec/fork/exit identity, cwd and inherited FDs, descriptor-relative
paths, mappings, metadata effects and every supported input route. Missing or
unsupported events, unresolved references, unknown children and exhausted bounds
must refuse. Its actual execution must use the original absolute deadline,
cancellation and create-only partial evidence; no retry or extra allowance.

The existing executor and dependency comparators also require exact original
command/output graphs. A wrapper changes executable argv and adds artifacts;
a reviewed successor must independently bind both original and executed recipes
and complete input/output groups before dispatch. An unpinned callback,
monkeypatch or unversioned argv rewrite cannot retain the old manifest as if it
described the executed commands. Original v1/v2/v3 defaults remain unchanged.

## Evidence needed before the CLI loader

First accept the protected input view and complete inventory with an actual
finite inert build. Exercise undeclared config/helper/response/cache input,
FD/cwd alias, same-byte replacement, mutation during use, observer truncation,
unsupported input routes, cancellation, timeout and incomplete descendant drain.
Then run the full actual CPython/freezer/static-link and ELF/image acceptance
under that mechanism. A tiny success cannot approve the larger closure.

Only after accepted build/image and actual startup/lifecycle exist can the
per-episode loader create original request/memory/intent-bound contexts for the
controller and gateway. Unknown recovery must remain read-only and cannot
relaunch a replacement attempt. Complete observational inventory, immutable
consumption, startup, solver correctness and publication are separate gates.

Retained 5090gpu observations deny the selected read-only mount/user-namespace
operations and supported KVM access. This work changes no host privileges,
policy, groups or accelerator. Those environment prerequisites do not erase the
software work above: complete configured input closure, enforced custody,
observer/executor integration and accepted runtime construction are still open.

`driver_inputs_verified`, `immutable_custody_verified`,
`implicit_link_inputs_verified`, `installation_accepted`,
`production_admission` and `online_publication` remain false. No tasks or shared
status document is changed by this design, and no mixed/CI/merge acceptance is
claimed.
