# Feature 193: explicit VFS source-data root acquisition

Status: software regression and finite inert VFS mechanism passed; installation
and full configured CPython/runtime acceptance remain open.
Baseline: 13d8a7d5756e202cd08504a2ef159eb275bad797.

## Problem and contract

The original source-data v4 backend requires an independently selected
`GraphDriver.Data.MergedDir`. The installed VFS service does not establish that
field. An absent value must continue to refuse that backend. Add an explicit
VFS route, never an automatic fallback or a caller-supplied root.

`run_pinned_build_v4_vfs` and `run_dependency_checked_build_v4_vfs` reuse the exact
recipe-v4 bytes, projection, finite tool graph and original execution loop. Their
only backend is `podman-snapshots-source-data-vfs-v1`. Use execution-report-v5,
command-observation-v3 and dependency-consumer-v3, each bound to that backend.
Original APIs, defaults, schemas, MergedDir gate and monkeypatch seams retain
their behavior. All control, root acquisition, readbacks and cleanup use the
original absolute deadline and cancellation, without another attempt or budget.

## Root acquisition

Select fresh `vfs`, GraphRoot and RunRoot from the same original local service.
Bind exact original container ID/image and initialized OCI config path. Read
bounded original VFS container/layer metadata through nofollow directory handles;
reject duplicate identities, missing/ambiguous links, invalid IDs and unsupported
layouts. Select the sole container's layer and exact GraphRoot/vfs/dir/layer.
Its directory identity and the actual OCI root must agree. Record original raw
metadata pins separately from selected fields. Historical paths and OCI root
alone do not acquire authority.

Bind the fixed service MainPID, process start identity and held mount namespace.
Different client/service namespaces must either be explicitly acquired through
the held original service root or refused. For service-root acquisition, walk
metadata, OCI/root and the four workspace roles beneath its held proc root with
nofollow components; require their actual directory objects to match the
original client-side objects. The deliberate proc root/namespace magic links
are the only exceptions to normal nofollow path traversal. Recheck service
identity and namespace before returning the pre-start observation. Do not read
live argv/environment or accept arbitrary host helpers/root callbacks.

Directory identity alone cannot exclude a different nested bind mount in the
service namespace. This finite VFS profile also reads bounded client/service
mountinfo and refuses mountpoints at or below storage/run roots, the VFS root
and the four workspace roots. Pin the original mount tables and refuse drift
during acquisition; tables need not be equal across namespaces. For fixed
resolver and runtime account/container metadata mounts, compare the actual
nofollow file identity and bounded bytes through both roots while the service
is held. Record those cross-view observations with the root proof. Unsupported
storage submount layouts refuse explicitly; no general namespace-entry helper
or whole-host mount policy is introduced.

The detached consumer checks exact version/backend, proof structure and pins,
container/image/root/view bindings, original workspace identities and false
claims before the existing observation/resource/state checks. It consumes a
persisted observation; it does not restart a service or reacquire live execution
authority. The original trusted Podman/crun/host boundary remains explicit.

## Development and acceptance

Develop this complete slice, then consolidate affected regression. Cover valid
VFS linkage, malformed/duplicate JSON and IDs, symlink/path/inode substitution,
container/image/layer/root mismatch, namespace/process drift, workspace aliases,
exact new report readback, old/new backend rejection, absolute budget and partial
report retention. Fixture observations prove software checks only. A separately
identified inert actual-mechanism attempt may follow; no original failed smoke
or consumed mixed HEAD is replayed. Preserve original errors and skips.

Full compiler/config/resource closure, CPython/freezer/static ELF, sealed startup,
production CLI, fixed-U/writable-object acquisition and installed-account
acceptance remain open. `production_admission=false`, `online_publication=false`.
No model, WebAgent, remote evaluator or solver campaign is part of this slice.

## Verification — 2026-10-29

Frozen 54ce88e5: 775 unique cases, 767 pass/8 old failures, zero error/skip,
13.002223 seconds. All 114 then-new VFS cases passed. The eight original failures
were retained and only those eight passed with the same 2724-file source on
serial Linux (7.100710 seconds). The copied-shell failures had raw returncode -9;
its underlying cause is not established. The two deadline failures retain their
original reason/cleanup observations.

One original finite inert smoke passed import/create/init and refused service
acquisition before start. A later read-only different-PID reproduction identified
`_proc_bytes` rejecting a legal short procfs read: 4070 initial bytes, 150986 total
bytes in 38 chunks, below the existing 1 MiB ceiling. Its failure is not rewritten.
The corrected reader accumulates to EOF within that same cumulative ceiling and
closes the descriptor on refusal. Frozen 80c3f930 changes only that module, its
two new real-file tests and CI count files; 142/142 affected cases pass in
1.931005 seconds. Current applicable unique passing coverage is 777, including
116 new cases, across these retained batches; it is not one complete green run.
Both archives, full source bytes/Git modes, before/after inventories and original
XML were independently audited. Manifest: 83 groups, 65 zero-skip, sum 7140.

The corrected frozen source then passed one separate actual Linux inert VFS
mechanism attempt: six commands, about ten seconds, one original 600-second
absolute budget, zero retry, with 2724 source records unchanged. This validates
only the finite inert helper/view/report chain. Original failures and root
prerequisite skips remain retained. Full CI, configured compiler/driver inputs,
CPython, installed authority and production CLI remain unaccepted. Evidence is
under the primary workspace ignored `validation/vfs-root-20261029/` directory.

The successful original receipt elapsed 9.424226 seconds. Actual store/OCI/
mountinfo snapshot bodies were not separately retained: the report retains their
pins and identities, while original info/inspect control logs are available.
Independent review can verify artifacts, source and cross-bindings, and cannot
replay unretained raw snapshots or establish installed authority from them.
