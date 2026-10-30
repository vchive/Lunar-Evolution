# Feature 193 successor: original VFS execution lifetime observation

Status: implemented on `codex/vfs-execution-lifetime`. Frozen `02347d68` passed
all 1,683 cases in 37 complete affected files on Linux/Python 3.12, with no
failure, error, skip or retry and unchanged source bytes/Git executable bits.
The independently reviewed fresh six-command inert runner/consumer attempt
passed in 17.175096 seconds under its original 600-second budget, without retry.
Its 486 original files bind all six five-phase histories, 108 lifetime raw and
102 original VFS raw records; all authority claims remain false. Review receipt:
`12865705e086d40d92b23a212144efd98510dd55fa5c69a545a5df0942b51743`.
The older `6b95e260` actual attempt remains failed after configure0: freeze0
refused inside original service verification before start, with its precise
historical branch unknown. The opt-in profile in
[vfs-service-connected-streams.md](vfs-service-connected-streams.md) addresses a
separately reproduced parser defect, without rewriting that failed history.
The independently
reviewed inert pre-start probe v3 established initialized PID/root/namespace
acquisition on 5090gpu: one 120-second budget, zero retries, remote duration
0.814724 seconds and 62 original files matched. Its review receipt is
`e97bdfc6f8233647d30df3869094c63cad5890e6899636b1adef345bc279dd31`.
That probe establishes feasibility only; it does not accept the implementation,
runtime or a historical build. This document does not authorize replay of an
old build.

## Purpose and limit

`PodmanCustody._vfs_selection` currently acquires the original `ServiceRoot`,
validates storage/OCI/workspace views, then closes its handles before returning
the pre-start policy. `run` later records original attach, wait/state and output
readback, but does not retain that service owner or acquire the original worker
before start. Retained raw VFS snapshots cannot reconstruct those missing live
objects after execution.

The successor keeps the original service and initialized worker handles through
the existing command and output-readback path. It records finite observations at
the named boundaries below. It neither continuously monitors every process or
mount mutation nor proves all driver reads, immutable input consumption, writer
exclusion or complete namespace disappearance. A successful observation remains
unaccepted build/runtime evidence.

## Explicit APIs and versions

Use the same `_run_pinned_build` loop, recipe-v4 bytes, source-data projection,
finite command graph, current/prior separation, original absolute deadline and
cancellation. Do not add a process executor, generic callback, CLI route,
environment switch or caller-supplied PID/root/owner.

| Item | New, explicit selection |
| --- | --- |
| Backend | `podman-snapshots-source-data-vfs-lifetime-v1` |
| Executor | `run_pinned_build_v4_vfs_lifetime` |
| Dependency consumer | `run_dependency_checked_build_v4_vfs_lifetime_source_directories` |
| Execution report | `lunar-static-python-build-execution-report-v7` |
| Command observation | `lunar-podman-build-command-observation-v5` |
| Dependency report | `lunar-actual-build-dependency-consumer-v6` |
| Lifetime manifest | `lunar-podman-vfs-execution-lifetime-v1` |
| Candidate readback | `prepare_lifetime_fixed_installation_description` |

The executor takes the same preparation, recipe/pin, roots, workspace, deadline,
interruption and monotonic arguments as `run_pinned_build_v4_vfs_retained`, with
only its exact new backend literal accepted. The consumer takes the same
arguments as `run_dependency_checked_build_v4_vfs_retained_source_directories`,
including the existing independent standalone/direct-linker profile pins. It
selects the already implemented `source-inventory-directories-v1` comparison,
with its unchanged finite spelling and original-inventory rules. No new path
normalization, discovery approval or selectable mapping is introduced.

The internal lifetime mode requires version4, VFS acquisition and raw retention;
reject invalid or partially selected combinations before preflight, workspace
creation or dispatch. Every older entry point, backend/report schema, default
value, omitted/None behavior, command vector, monkeypatch seam and canonical
report byte string remains unchanged. Older readers refuse new observations;
the new reader refuses old or mixed observations. Do not silently extend
`prepare_retained_fixed_installation_description`, which accepts the older
retained history only. A separate
`prepare_lifetime_fixed_installation_description` accepts only report-v7 and
dependency-v6 through the same strict original report validator. It reuses the
existing two-round input/output/history FD readback, ELF and expanded closure
checks, and returns the same non-authoritative candidate DTO. Cross-version or
mixed histories refuse. Neither entry point creates accepted custody or a
runtime installation, and old candidate bytes remain unchanged.

## Original acquisition and ownership

Only the original `PodmanCustody.run`, immediately after its successful `init`
for the returned original container ID, constructs a private
`_VfsExecutionLifetime`. It owns the existing selected `ServiceRoot` rather than
closing it and constructing a replacement later. The original service PID,
pidfd, start ticks, root/mount-namespace handles and socket ownership checks
remain in force. Existing VFS metadata, OCI policy, seccomp and cross-view checks
must all pass before any start gate.

Acquire a fresh original state through the fixed `inspect State` control path.
Require an exact positive integer `Pid` (not bool), a supported initialized
non-running state, `OOMKilled=false` and no runtime error. The probe must establish
the supported installed state spelling before implementation is selected; a
missing/zero PID, unsupported state or inaccessible kernel object refuses before
start. Do not start first to discover a PID, use an old ready-state PID, scan for
a matching task or accept a caller-selected replacement.

For this finite profile, hold and compare the service and client PID namespace
identities and require them equal before interpreting the service's numeric
`State.Pid` in client `/proc`. A different PID view refuses; no PID translation or
namespace-entry helper is added. From that original PID, hold its pidfd, root
directory, mount namespace and PID namespace. Read bounded stat/start ticks and
revalidate the named original process and held handles before returning. Require
the worker's private PID namespace to differ from the service/client namespace
and match the original OCI private-namespace policy.

The controlled `/proc/PID/{root,ns/mnt,ns/pid}` kernel magic links are deliberate
exceptions. All data paths beneath held roots use nofollow directory components,
bounded regular-file reads where applicable, and original object/name checks.
Bind the held worker root to the same acquired VFS root object. Open and hold
the four worker-view directory objects at `/source`, `/toolchain`, `/work` and
`/out`; match them to the original source, toolchain, prior and current roles
already selected through the service and client views. Bind original recipe,
stage/index, container/image, OCI/root proof and retained VFS-manifest pins.
Process-local FD numbers are never persisted as detached authority.

Use one private owner per original command. It cannot be serialized, adopted,
shared across commands, supplied by a factory or restored from a manifest. A
failure while acquiring any handle closes every handle acquired so far. Named
reopens validate the still-held original objects; they never substitute new
objects for the owner. The old `_vfs_selection` close-on-return behavior remains
unchanged when the new mode is not selected.

## Fixed phases and normal exit

The owner enforces this exact ordered phase machine; omission, repetition,
reordering, reuse or completion after close refuses:

1. `initialized`: original init/control state and service/worker acquisition;
   original worker pidfd is live, and root/ns/role identities agree.
2. `before-start`: after original policy/seccomp and retained VFS start gates,
   repeat live original PID/start/root/ns and service/role checks, then dispatch
   the existing single `start --attach ORIGINAL_ID` command exactly once.
3. `original-exit`: after that original attach client returns, require its
   existing successful return/reap/log evidence, original Podman `wait` zero,
   terminal state with non-running/PID zero/zero exit/no OOM/error, and readiness
   of the held original worker pidfd. Revalidate held service and directory/ns
   objects. Cross-bind the exact wait/state control logs and attach operation.
4. `before-readback`: repeat held service/root/role checks before `_scan_outputs`
   and the existing declared-output `_observe`/promotion loop.
5. `after-readback`: repeat checks after all declared outputs and promoted-copy
   comparisons, bind the exact original ordered readback-output vector, and
   complete the lifetime record while the original handles are still held.

`start --attach` can return only after a very short command has exited. Therefore
there is no mandatory sampled `running` phase and no new target gate/helper or
background executor. Holding the original handles spans that execution; sampled
boundary checks do not claim continuous namespace or writer surveillance.

After original exit, do not require `/proc/ORIGINAL_PID` to remain present and do
not follow a reused numeric PID. Its held pidfd is the exit identity. The held
root/ns/role FDs remain comparison objects until readback finishes; their
continued existence does not mean the worker is alive or its namespace has
disappeared. A live pidfd at the terminal gate, service death/replacement, wait
or state disagreement, or changed held/name/root/role bindings refuses.

Release handles in an outer `finally` on every outcome. A completion artifact
may survive a later close/report failure, but a command is successful only when
the original complete command/report and all gates succeed; file existence is
not success. Failure cleanup targets only the original container ID using the
existing stop/state handling and the same original remaining budget. Preserve
first failure and unknown cleanup. No reacquisition, retry, new command,
replacement consumer or refreshed cleanup allowance is permitted.

## Original retention and detached validation

Keep the original `podman-vfs-raw-snapshots-v1` manifest, fixed roles and verifier
unchanged. It still completes before start. Add a separate create-only
`custody/<stage>-<index>/vfs-lifetime/manifest.json`, bound to that exact VFS
manifest and root proof. Capture buffers at their original observation sites;
never query historical `/proc`, state, storage or mount paths to fill gaps.

The lifetime capture uses the same attempt-owned CAS and original write ledger
as `VfsSnapshotStore`: retain the 512 MiB cumulative ceiling, no reservation
refund, no adoption of pre-existing same-hash blobs, private 0700 directories,
0600 files, bounded nofollow FD readback/fsync/name checks and original checkpoint.
Its separate fixed roles cannot be accepted by the old raw-snapshot verifier.
Limit each command to five ordered phase records and at most 32 raw references,
a 64 KiB manifest, 4 KiB per raw-record receipt, 64 KiB per kernel stat body,
32 KiB per selected state body and the existing 1 MiB mountinfo ceilings. Keep
the existing maximum 512 commands. Capacity exhaustion preserves partial
evidence and refuses without increasing any budget or cap.

Each phase records its fixed ordinal, original owner identities, live/exited
pidfd result, held root/ns/role observations and exact relevant control/raw
pins. The terminal and readback records additionally bind original attach,
wait/state and output inventory. Retain service/client mount topology at the
original checks and reapply the existing protected-subtree exclusion; unrelated
mount rows are not evidence of a changed protected object. Do not treat a mount
namespace inode alone as proof that its mount table never changed. Records have
exact key sets and contain only bounded original observations and false claims.

`validate_custody_observation_v5` first checks the exact new schema/backend and
lifetime-profile binding, then verifies original raw VFS bytes and all existing
runtime/resource/argv/environment/input/prior/output checks. It reads the new
lifetime manifest/raw references only through bounded nofollow regular FDs,
rejecting missing/extra/duplicate phases, roles, keys and cross-command records.
Replay original stat parsing, PID/start/root/ns/role equality, live-to-exited
pidfd phase meaning, operation ordering and exact original log/output bindings.
Compare raw metadata/control records rather than trusting re-signed selected
fields. Enforce exact original report-v7 reconstruction and persisted bytes.
Detached validation never opens live `/proc`, contacts Podman, reacquires an
owner or proves that recorded observations exclude unobserved events.

The lifetime manifest completes only after `after-readback`. A partial manifest,
failed/unknown command, substituted original owner, truthy authority claim or
old report relabelled as v7 is refused. Every existing authority claim remains
false, including immutable custody, complete driver/implicit inputs, configured
closure, installation/runtime acceptance, complete namespace disappearance,
descendant cleanup, production admission and online publication.

## Planned implementation and concentrated verification

Only after the separately reviewed inert pre-start probe establishes the
required initialized PID/root/ns acquisition may implementation proceed:

| File / function | Planned change |
| --- | --- |
| New `podman_vfs_lifetime.py` | Private original owner, five-phase machine, bounded lifetime capture/replay and context-free refusal codes. Proposed methods: `acquire`, `before_start`, `observe_original_exit`, `before_readback`, `finish_readback`, `close`; all evidence comes from original custody call sites. |
| `podman_custody.py::_vfs_selection`, `_runtime_policy`, `PodmanCustody.run` | Preserve old selector seam and close behavior; add an explicitly selected private ownership-transfer path, acquire original state after init, call the five phase gates around existing attach/wait/readback, release once in finally, and emit command observation-v5. Add `validate_custody_observation_v5`. |
| `podman_vfs_root.py::ServiceRoot` | Reuse existing original service acquisition/verification. Add no caller PID mapping or new default behavior; any shared helpers must preserve old contracts. |
| `podman_vfs_snapshots.py::VfsSnapshotStore` | Private new lifetime-capture access to the same CAS/ledger; preserve old `_Capture`, roles, limits and verifier bytes/meaning. |
| `execution_backend.py::_run_pinned_build` and new explicit entry point | Guard the new mode/backend before effects, pass it only through the original custody object, emit report-v7, preserve old paths and original report on refusal. |
| `build_dependency_consumer.py::_run_dependency_checked_build`, `_report_outputs` and new entry point | Select that one original runner and validator, consume exact report-v7 and original lifetime records, retain current finite source-directory/compiler/linker comparisons and emit dependency report-v6. |
| `retained_installation.py` and separate candidate tests | Add an explicit lifetime-history entry point, bind report-v7/dependency-v6, preserve the existing retained-history API and candidate format, and reuse all original readback/schema/ELF checks without granting authority. |

Develop the coherent slice, then run its focused files together with affected
old execution, dependency-consumer, VFS root/custody/raw-retention tests and
required Ruff, compileall and diff checks. Do not launch per-agent pytest
campaigns. Add short explicit parameter IDs for large malformed bodies.

Required cases cover actual bounded file/FD readback and original call ordering;
bad/missing/zero/bool initialized PID; unsupported PID views or unavailable
pidfd/root/ns; PID reuse and service/socket replacement; closed/replaced owners;
root/role symlink, mount or same-byte object substitution; every phase omitted,
repeated/reordered or crossed with another command; early/fast normal exit;
live pidfd plus reported terminal, exited pidfd plus reported running, nonzero
wait/exit/OOM/error; attach client not reaped; output drift before/during/after
readback; partial constructor and descriptor cleanup; missing/re-signed raw or
control evidence; storage bounds/write failures; original deadline/cancellation
at acquisition/start/exit/readback; no start after acquisition refusal and no
fallback/retry/new budget. Test all old default bytes and old/new version
rejection. Fixtures must label doubled kernel/runtime boundaries; parser or
DTO success is not an actual original-owner observation.

A new frozen-source finite inert attempt can then exercise the implemented
original runner/consumer and retained lifetime records once under one reserved
deadline. The earlier probe only establishes feasibility and cannot replace
that test. Any later full CPython execution requires its own source-bound
original attempt and independent review; no old full-build report can gain
these missing observations retroactively.

Immutable input custody, complete configured driver closure, accepted static
image/runtime root, sealed startup, original solver lifecycle, the first
scheduler-context loader, production RSI CLI and copied local cases remain
separate unfinished work. Fixed-U interval exclusivity, external-writer
acquisition and real root/account/ACL/cgroup prerequisites remain separate too.
No remote evaluator, model, WebAgent or solver campaign is introduced here.
