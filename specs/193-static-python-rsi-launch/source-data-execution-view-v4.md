# Feature 193 continuation: source-data execution view v4

Status: implementation, independent review and affected software regression complete;
actual rootless smoke failed before container creation, installation acceptance remains open.
Baseline: 1810f2dfcce55b00d4817add6366fc58a4632495. This continuation does not alter
that frozen PR #190 acceptance source, its consumed mixed, or its running CI.

## Problem and intended behavior

The finite v3 Podman helper gate correctly refuses all executable source scripts.
The complete CPython source inventory contains 116 such files, although the finite
native recipe reads those files as data. A new explicit contract must distinguish
original execute-bit observations from permission to execute within the guest.

The v4 view preserves every original source record, byte digest and executable bit.
It mounts source read-only/noexec and allows only the finite native toolchain and
completed generated executable outputs to serve as tools. It does not delete
records or rewrite original executable bits to pass the old gate. The original
v1/v2/v3 APIs, schemas, reports and backend selections retain their behavior.

## Fixed interfaces

- RECIPE_V4_SCHEMA = lunar-static-python-pinned-execution-recipe-v4.
- Exact top-level fields: existing v3 schema/preparation_sha256/inputs/environment/
  stages plus input_projection, which must equal source-data-static-tools-v1.
- run_pinned_build_v4 uses the original runner loop and the one original absolute
  deadline/cancellation/readback/protection/report lifecycle. Its sole backend is
  podman-snapshots-source-data-v2. No host, copied-image, old-backend or retry fallback.
- New execution report schema: lunar-static-python-build-execution-report-v4.
- New per-command custody observation schema: lunar-podman-build-command-observation-v2.
- New run_dependency_checked_build_v4 invokes that same runner and consumes its
  actual persisted report/observations; consumer evidence schema is
  lunar-actual-build-dependency-consumer-v2.
- New capture manifest schema: lunar-cpython-data-source-dependency-recipe-v1,
  binding the exact v4 recipe and complete input inventories, the fixed projection,
  complete compiler/linker capture plan, and any standalone linker profile.
  The original pre-overlay source inventory and base-manifest digests are emitter
  provenance assertions protected by the independently pinned capture manifest;
  consumers do not reconstruct those original bytes or acquire origin authority.
  Final source/toolchain/combined inventories and the prior v3 recipe are
  independently reconstructed from the supplied recipe and strictly compared.
- Explicit successor emitters may share private generator/comparator code but must
  not silently rewrite or accept a legacy recipe under the old public APIs.

## Actual view and finite command graph

/source is ro,noexec,nosuid,nodev; /toolchain and completed /work snapshots are
ro,exec,nosuid,nodev; /out and scratch remain rw,noexec,nosuid,nodev. Preserve the
original snapshot 0555/0444 projection. Match actual OCI root/mount identities and
options before starting the container; merely adding noexec to argv is insufficient.
Reject overlap, wrong source root, exec alias, unknown mounts and role substitution.
Bind original full input inventory hashes and actual per-command OCI/view evidence
separately. Observations are detached evidence, not reusable authority tokens.

Every command freshly validates all toolchain and prior executable helper files
through the existing supported static ELF/full hash/original FD+name identity gate.
Source is data only in this explicit profile with its actual view check; old gates
still inspect and refuse executable source scripts. Source can never be argv[0].

The exact existing Zig/C/archive/standalone-linker/native-freezer grammar remains.
In the v4 graph a source data reference does not require original executable=false;
executable-tool checks remain strict, and generated inputs still require an entire
previously completed output group. No shell, host Python, PATH discovery, generic
interpreter, -c/-m script execution or shebang route is added. noexec cannot prevent
a trusted native tool from interpreting bytes; this remains a finite trusted-tool
contract, not a kernel exec-event allowlist or a complete implicit-read observer.

## Regression and boundaries

Develop the full slice, freeze it, then run one consolidated affected suite. Cover
legacy script refusal and byte compatibility, v4 full source pin preservation,
source data xbit=true vs source execution refusal, malformed/mixed schema/backend,
actual OCI mount mismatch and exec aliases, implicit helper scripts/static ELF drift,
partial/current output promotion, persisted observation replacement, and original
budget/cancellation/error/report cleanup. A real rootless finite inert build is a
separate actual mechanism check; mocked OCI metadata cannot replace it. No model,
WebAgent, remote/company evaluator, full solver campaign, secret or original
benchmark mutation is authorized by this slice.

Full CPython/freezer/static-link/input custody and accepted runtime/per-episode CLI
remain separate work. Whole-interval fixed-U/writer acquisition and installed root/
account acceptance are not acquired here. configured_closure_verified,
immutable_custody_verified, driver_inputs_verified, implicit_link_inputs_verified,
installation_accepted, production_admission and online_publication remain false.

## Actual verification — 2026-10-29

Frozen a6015796: 18 complete affected files, 649 unique = 645 pass /4 fail /0
error/skip, 9.133003400 seconds. Only two test files then changed: update the CI
manifest sum assertion and instrument linker depfiles in three runner fixtures.
No product bytes/modes changed. Frozen a743ea7d: two complete affected files,
147/147 pass, 4.084723906 seconds, all 16 workers exit0 and 254 module origins.
Archive/Git modes/full source before-after/collection/unique execution/JUnit were
independently audited. Current applicable unique software cases: 649 with passing
results, including all 120 new cases; this is not a single final-tree full rerun.
The original failures remain retained. CI stays 83 groups/65 zero-skip groups,
expected count sum 7008. Ruff, compileall and both diff checks pass.

One real inert rootless smoke compiled the static native test tool and dispatched
the original consumer under one 600-second deadline, without retries. It failed
at the first Podman image import (rc125): `/var/tmp` temporary archive write
reported disk quota exceeded. Elapsed 2.045555122 seconds; no container was
created or started. A real execution view and full build were not accepted. The
v4 partial report, actual error/logs, source inventories and failed receipt are
retained. Existing service reports vfs, 0 running/17 stopped containers, and a
stopped-container GraphDriver.Data=null; no MergedDir availability was proven.
Neither host free-space readings nor fixture views close these real gates.
No old containers were deleted and no service was restarted or replaced.
