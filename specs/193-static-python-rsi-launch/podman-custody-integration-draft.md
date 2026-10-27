# Podman custody on the original build path: integration draft

Status: **the default-off Podman backend is implemented on the original build
chain; focused tests and the original-consumer inert smoke remain pending
acceptance**. This is not permission to run a real build or a claim that complete
configured input closure is available. The earlier tiny two-stage environment
observation is recorded in
`../189-static-python-fixture/podman-inert-custody-observation-20261028.md`.

## Implemented contract and validation status

`run_dependency_checked_build(..., custody_backend="podman")` passes the explicit
selection through `run_pinned_build_v3` to the same `_run_pinned_build` loop. It
preserves the original finite command graph, absolute deadline, output readback
and report consumer; the default route and v1/v2 semantics are unchanged.
Every original command receives a separately copied image containing the complete
pinned `/source` and `/toolchain` inventories and all verified prior outputs at
read-only `/work`. Only that command's fresh current-output bind is writable at
`/out`; a target-only comparator root does not admit current files as inputs.

The first implementation refuses attempts above **32 commands** or **8 GiB of
cumulative imported image bytes**. It deliberately does not claim an aggregate
output-storage hard quota: the fresh host current-output bind has a per-file
`RLIMIT_FSIZE` and bounded post-exit validation. The host, existing rootless
Podman/crun/image custodian and pinned tools remain trusted. Effective OCI policy
is checked before start, including fixed resolver data and separated scratch;
original-container exit observations do not prove complete namespace cleanup.

The focused execution/consumer/comparator tests and a **four-stage, seven-command
static inert smoke through the original consumer** still require acceptance on
the frozen implementation. The smoke covers configure probe, actual generated
freezer/header, compile and archive/link without running real CPython, Zig, a
solver or a model. No result is claimed here before those checks complete.
All G1/custody, driver/configured closure, installation, production admission and
online-publication authority remains **false**. Complete reviewed configuration
and explicit support generation remain separate unfinished work.

## Historical design draft

The remainder preserves the initial design discussion verbatim as historical
context. Its future-tense and unimplemented-status statements describe that
earlier draft; the implemented contract and pending validation above supersede
them. They do not grant broader execution or acceptance authority.

## Existing APIs and exact integration surface

The original call chain is:

```text
build_dependency_consumer.run_dependency_checked_build
  validate_dependency_capture_plan
  validate_dependency_command_graph
  execution_backend.run_pinned_build_v3
    execution_backend._run_pinned_build(version3=True)
      _recipe / _preparation_wire / control and fresh-workspace checks
      _observe original input → ordinary copied snapshot
      expand reference → host source/toolchain/work path
      per-command _command
      _observe actual declared outputs → grant later generated executable
      create-only report.json / BuildExecutionReport
  _report_outputs verifies the exact original command/output graph and report
  _read_pin report + original/snapshot inputs + actual outputs
  compare_compiler_dependencies / compare_linker_dependencies
  create-only dependency comparison/output inventory/report
```

`run_pinned_build_v3` is not a replaceable backend today: it passes
`version3=True` into the same internal loop as v1/v2. `_command` launches one
host process and records local direct-child/log facts. The dependency consumer
accepts only the original `BuildExecutionReport` type and exact canonical v3
`report.json`; it does not accept a caller-produced output inventory or callback
receipt. Those constraints are useful and must remain.

A substantive integrated implementation would touch these files:

| File/API | Required change and preserved meaning |
| --- | --- |
| `execution_backend.py::run_pinned_build_v3` and `_run_pinned_build` | Explicit default-off custody selection for v3 only; the same validation, absolute deadline, cancellation, workspace, ordered command graph and returned report continue to own the attempt. v1/v2 and default v3 remain unchanged. Selection cannot authorize a build or supply a new deadline. |
| `execution_backend.py` private command/snapshot dispatch, or a private `podman_custody.py` called only by that loop | Actually construct and verify complete immutable input layers; create exact-ID containers with fixed runtime policy; collect original command logs/status/outputs; protect each completed output group before the next command; stop/wait only original container IDs on failure. This is actual execution code, not a second `run_*build` entry point. |
| `build_dependency_consumer.py::run_dependency_checked_build` | Pass explicit selection through the original call and retain original report/readback checks. Any guest-path mapping must be derived from that original execution's fixed policy and bound in original retained evidence, never accepted from the caller as authority. |
| `dependency_capture.py::_roots`, `compare_compiler_dependencies` | Support and verify the precise guest source/toolchain/prior/current path mapping without rewriting depfile bytes or silently relabeling the old single-work-root comparison. Preserve prior-output ordering and original canonical target identity. |
| `link_dependency_capture.py::compare_linker_dependencies` | Match the same executed guest mapping and exact actual target; retain refusal of unknown support/cache/script/implicit paths. No learning of current digests. |
| `command_input_graph.py::validate_dependency_command_graph` | Reuse the same finite original compile/link/archive/freezer input/output classification for safe lowering. A claimed `validated=True` capability or caller callback must not bypass it. The selected executor must validate, rather than trust, its lowering input. |
| Focused execution/consumer/depfile tests | Exercise actual original-loop integration, immutable prior/current separation, effective argv/path mapping, original reports, controlled refusals and original-container cleanup; parser-only or mocked DTO round trips are insufficient. |

There is no `BuildBackend` plug-in seam suitable for this work.
`build_driver.py::BuildBackend` belongs to the separate mock-only driver;
connecting a Podman backend there would bypass the actual consumer and would
not implement this feature.

## Required input and output interval

Before dispatch, the selected route must consume every file in the independently
pinned source/toolchain inventories through no-follow bounded original FDs and
bind the full resulting image to those records. It cannot use an arbitrary host
source bind, truncate the complete Zig tree, run a Dockerfile/build helper,
replace unknown files with observed current hashes, or substitute a caller's
image name/tag. Preserve exact archive metadata/explicit directories if claiming
the stronger existing archive custody contract; the current recipe's regular
file/execute-bit projection alone does not encode that whole contract.

At every original command boundary:

1. The complete original source/toolchain and **all earlier declared generated
   groups** are in protected read-only layers. Only current declared outputs and
   separately bounded scratch may be writable. No shared writable work mount can
   contain an earlier generated header/object/archive/freezer executable.
2. Lower the original finite argv/environment into fixed guest paths. Retain
   both the original recipe binding and the exact executed argv/environment and
   image/layer/container identities; changing the execution layout must not
   silently retain old host-path report semantics.
3. Run only the original command for that graph position. No shell, generic
   container command, helper selected from ambient PATH, host fallback, network,
   automatic image pull, daemon replacement or repair/retry is allowed.
4. Confirm original container completion and retain actual logs, status and
   partial evidence. Read only declared actual outputs through no-follow FDs;
   reject symlinks/special files, excess size/counts, identity drift, undeclared
   retained inputs or output groups and uncertain cleanup.
5. Construct and verify a new protected layer from those actual read-back output
   bytes before any later original command can consume them. Grant a generated
   executable only after the whole group passes, exactly as the current runner
   does. Failed/partial bytes must never enter a later consumer image.

The narrow probe used a static waiting helper because output tmpfs contents had
to be read while that helper remained alive. Reusing that helper would add a new
production executable/protocol and complete source/compiler/runtime closure
obligation. A host diagnostic compiler/hash does not close it.

A possible helper-free route is a fresh, bounded writable **current-output-only**
bind owned by the trusted controller, with all previous outputs kept in the
image. Its bytes can be read after the original container exits and then
protected for the next command. This remains a design candidate: it must not
expand to a writable shared work tree, expose a host input/store/control path,
permit a surviving writer, or change the stated trusted-host TCB. The process,
mount-alias, readback and full deadline contracts still need implementation and
adversarial verification before selecting it.

Re-importing the entire 358 MB Zig tree for every original command would be
wasteful and can exhaust the original deadline. A layered representation must
bind every base/generated layer and complete effective tree, disallow arbitrary
parents/whiteouts/symlinks, and reuse only exact original base content. A manual
OCI-layer route would add an actual encoder/verifier to the private module;
`podman build` or an unreviewed helper chain is not a free shortcut. No extra
execution allowance or old-case retry can hide transport cost.

## Unresolved path and report contract

The original runner expands every `@work/file` into one host `workspace/work`
root. Compiler `-MQ` targets and linker depfile targets use that root; generated
include directories, objects, archives and the freezer executable are also
compared under it. The compiler/linker comparators currently receive exactly
`source_root`, `toolchain_root` and **one** `work_root`.

An immutable layout needs distinct fixed guest roots, for example:

```text
/lunar/source     complete pinned source, read-only
/lunar/toolchain  complete pinned toolchain, read-only
/lunar/prior      all earlier declared output groups, read-only
/lunar/output     this command's bounded writable outputs/scratch
```

`@work` input references must lower to `/lunar/prior`; current output operands
must lower to `/lunar/output`. Source/toolchain directory references remain
pinned. `-MQ` is target metadata, not an ordinary file input; link depfile target
semantics also need exact binding. A generated include directory can contain
only earlier groups, never a current unobserved output. Merely replacing
`_command` or doing string substitution on depfiles loses this distinction.

Before code, select an explicit retained successor contract that binds original
recipe, exact executed argv/environment, fixed guest roots, original output
identity and original runner-owned observations. It must be versioned where the
canonical persisted evidence meaning changes. Keep existing v3 report bytes and
`_report_outputs` checks unchanged for default execution. Add a separately
validated selected-path report only if needed, while still produced/consumed by
the same original runner/consumer; do not accept a caller's guest mapping,
receipt, arbitrary roots or success booleans. This draft does not choose or
introduce such a schema.

## Runtime and driver closure remain fail-closed

The existing runtime policy must be enforced and independently checked on the
original containers: no network or host shares beyond an explicitly reviewed
current-output route, private PID/IPC/UTS, read-only inputs, capabilities zero,
no-new-privileges, supported syscall/namespace restrictions and bounded output,
logs, process count, memory and lifecycle. The effective policy matters, not
only argv switches. Check Podman-generated hosts/resolver/hostname/container
metadata, `/proc`/`/dev`, executable interpreters/loaders and any configured
seccomp/runtime helpers; unknown input/control paths cannot be declared closed
by a successful `podman create`.

Use the original absolute deadline through layer construction, load/create,
start, execution, output readback, protection, stop/wait and final evidence.
Blocking CLI/log operations need bounds from that same deadline and create-only
partial evidence. Cleanup cannot mint an independent allowance. Container names,
new PIDs or replacement processes cannot substitute for the original returned
container IDs. Missing/unknown original-chain exit remains unknown/failed.
The tiny probe's PID 1 and original PID exit do not independently prove complete
namespace disappearance or all supported descendant escape behavior.

The actual pinned Zig archive has bundled musl/CRT/compiler_rt **sources**, not
prebuilt `libc.a`, `libcompiler_rt.a`, `crt1.o` or `Scrt1.o`. The concrete recipe
currently lets Zig generate support inside its attempt-local cache; these
products are not earlier declared/protected groups. This is a genuine recipe
and support-generation gap. Do not import a cache directory as approved input,
auto-learn cache digests, ignore unknown linker dependencies, or mark the image
accepted because its root was read-only. Explicit reviewed support generation,
readback/protection and later consumption must be represented by the original
graph before a full build can pass.

The complete independently reviewed Linux/x86-64/musl `pyconfig.h` also remains
required. `concrete_recipe.py` receives it; its configure stage only compiles a
limited target/version/shared-mode probe. The CPython archive's iOS header and
`pyconfig.h.in` are not substitutes. No environment backend supplies the missing
configuration semantics.

## Completion and validation gates

The integration is not independently landable as a small `_command` adapter:
the same change must close the guest-path/report contract, actual immutable
prior/current transfer, original deadline/lifecycle, finite effective runtime
inputs and original consumer readback. Producing an off-by-default empty backend
would hide those coupled requirements, so no product backend is added here.

A later complete patch should validate through the original consumer using a
finite inert compile/link/archive/generated-freezer graph and actual isolated
processes, then exercise same-byte path replacement, writable aliases, mutation
throughout consumption, unknown helper/config/cache/response files, symlink and
extra outputs, missing loader, namespace attempts, source/output drift,
cancellation, original deadline, log exhaustion, partial readback, invalid image
identity and incomplete original-container exit. Preserve first failures and
never rerun a timed-out real build without explicit authorization.

After that mechanism is reviewed, close complete configured-header/support
source generation and actual full CPython/static-link dependencies under the
same path. Installation/image/startup/RSI acceptance remain later gates. All
existing `immutable_custody_verified`, `driver_inputs_verified`,
`implicit_link_inputs_verified`, `configured_closure_verified`,
`installation_accepted`, `production_admission` and `online_publication` claims
remain false in current product behavior. No P0 performance, CI or merge status
is changed by this design.
