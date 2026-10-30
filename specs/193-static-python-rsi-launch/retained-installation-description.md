# Retained build to expanded installation candidate

Status: implementation prepared; concentrated regression is pending.

This slice removes manual transcription of the generated frozen headers and
native objects into the existing expanded installation description. It creates
no build-consumption receipt, accepted installation, runtime authority or CLI
entry point. Feature189's immutable-custody and complete-driver-input conditions
remain open. Existing runners, comparison formats, admission gates and the
original nine-module installation path are unchanged.

## Explicit API

`tools.static_python_rsi_fixture.retained_installation` exports
`prepare_retained_fixed_installation_description(build, *, recipe_bytes,
expected_recipe_sha256, expected_manifest_sha256,
expected_dependency_report_sha256, runtime_closure,
expected_runtime_closure_sha256, expected_cpython_inventory_sha256,
expected_augmented_source_inventory_sha256, installation_version, workspace,
deadline, monotonic=time.monotonic, interrupted=None)`.

`build` is exactly the existing `DependencyCheckedBuild`, with its original
complete `BuildExecutionReport` and every existing authority claim false. The
only accepted history is the explicit source-directory comparator and retained
VFS consumer: dependency-report v5, compiler comparison v3 with
`source-inventory-directories-v1`, linker comparison v2 and execution report v6.
Older paths are not upgraded or selected as fallbacks. All caller pins are exact
lowercase non-sentinel SHA256 strings; bytes, version and controls are bounded
before hashing, parsing or filesystem access. No callback supplies evidence.

The source inventory pins have separate meanings. The CPython pin equals the
original closure's `cpython_inventory_sha256`. The augmented pin equals the
canonical ASCII-with-LF recipe `inputs.source` vector, which also contains
generated configuration, runtime and producer source inputs. They are never
substituted for each other.

## Readback and projection

The existing v4 recipe parser validates the complete supplied recipe. The
existing `_report_outputs` reconstructs report v6 and validates every original
retained custody observation. Its exact bytes and complete ordered output
inventory are compared against the persisted report and inventory. The original
consumer's independently pinned dependency report binds that report, recipe,
manifest, inventory and both comparison files; all false claims and fixed
profiles must match. The original compiler/linker comparison bytes are pinned
historical attachments, not proof of immutable input consumption. They are
checked for matching recipe/manifest/input/output bindings and complete recorded
comparison counts; no compiler, linker, Podman process or comparison rerun is
dispatched.

Read every recipe source/toolchain member and every reported output using the
original bounded no-follow FD reader, including repeated path/inode checks.
Repeat these reads and the original evidence reads before returning. Source
records from the runtime closure must be present with exactly matching bytes in
the source inventory. The retained `runtime/closure.json` must equal the pinned
closure. A successful current readback does not prove that the build previously
read those bytes or excluded outside writers.

Map each closure frozen unit's original `output` to its positive generated
record, and each native unit's original `object` to `objects/<object>`, preserving
the original vectors and all source/module/package/flag identities. Require
non-executable headers and objects. Read configuration from
`source/configuration/pyconfig.h` and the image from `work/bin/lunar-<solver>`.
Read the actual image mode through a held no-follow FD while checking the same
size, digest, identity and path binding; never turn an executable boolean into
an inferred0755 mode. Refuse zero-sized required output, source/header or
source/object reuse, incomplete output sets, profile mixing and invalid ELF.

Construct the existing canonical UTF-8-without-LF expanded installation schema
with the fixed original initialization profile and all nine claims false. Run
its unchanged parser and ELF inspector for **self-consistency only**, using
explicitly derived comparison pins. These internal hashes are not independent
approval. The immutable return value contains candidate bytes, closure bytes,
the original recipe/dependency-report/output pins and both distinct source
inventory pins. It is not a `FixedPythonInstallation` or an accepted-root handle.
An independent reviewer must retain approved candidate/inventory/image pins
before a later caller uses the existing installation parser as a comparison.

## Control, effects and failures

All work stays under the caller's one absolute deadline. Monotonic and optional
interruption callbacks are checked before and after synchronous operations;
blocking syscalls cannot be preempted. Failure is a fixed context-free
`RetainedInstallationDescriptionError` code. No refreshed deadline, retry,
fallback, output write, execution, environment read or runtime selection occurs.
Original failed/unknown reports remain refused. Candidate construction grants
no custody or live ownership. `production_admission=false` and
`online_publication=false` throughout.

Focused fixtures use labelled synthetic source/build/report/custody histories
and inert ELF bytes. Only the original custody observation boundary is doubled;
all candidate mapping, recipe checks and real bounded filesystem readback remain
active. Tests cover both solvers, complete frozen/native vectors, distinct source
pins, historical-file/field disagreement, all-false claims, profile separation,
missing/duplicate/wrong-mode outputs, source drift, symlinks, image mode and
identity drift, deadline/interruption, immutable/detached results and absent
execution/writes. They do not establish a real CPython build or runtime.
