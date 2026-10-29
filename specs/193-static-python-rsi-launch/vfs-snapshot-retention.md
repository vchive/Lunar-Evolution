# Feature 193 successor: retained VFS acquisition snapshots

Status: implemented; affected software and finite inert Linux mechanism passed.
Full CI, installation and configured runtime acceptance remain open.
Baseline: 91187d8bb00d1b12afba0b04e4d8970a3555bec4.

## Problem and explicit route

The original VFS attempt retained metadata hashes and identities, but not the
original store, OCI and mountinfo bodies. Its successful finite inert run cannot
support independent replay of those bodies. Keep its evidence and APIs unchanged.

Add `run_pinned_build_v4_vfs_retained` and
`run_dependency_checked_build_v4_vfs_retained`, accepting only
`podman-snapshots-source-data-vfs-retained-v1`. Reuse recipe-v4 and the original
single-attempt loop, absolute deadline, cancellation and output promotion. Bind
execution-report-v6, command-observation-v4 and dependency-consumer-v4 to this
backend; the root-acquisition-v1 proof stays unchanged. Older entry points never
select or accept this backend. No retries or additional cleanup budget.

## Original read capture

An internal attempt-owned store captures the exact byte buffers at the original
read sites, before advancing the gate. It never re-queries a historical source
to fill missing evidence. Capture selected info/inspect control stdout; containers
and layers before/after; OCI; service/client mountinfo at acquire-before,
acquire-after and final-view; both service and host ancillary observations.
Distinct observations remain distinct records even when bytes deduplicate.

The command manifest lives at `custody/<stage>-<index>/vfs-raw/manifest.json`;
blobs live at `custody/vfs-raw/blobs/<sha256>.bin`. The command manifest binds
recipe SHA, stage, index, original container/image IDs and root-proof SHA.
Its size and SHA are included in the original observation before container start.
Files use create-only nofollow writes, fsync, readback and original inode/name
checks. Directories are private 0700 and files 0600. Existing unowned names refuse;
only blobs created and still pinned by the same store may be reused.

Retain each source's existing ceiling (2 MiB store files, 1 MiB OCI/mountinfo,
fixed ancillary limits), at most 24 fixed-role events/command, a 64 KiB manifest
and a 512 MiB cumulative stored-byte ceiling for the attempt. Retention shares
the original checkpoint; write, deadline, cancellation and capacity failures
refuse start and preserve partial files. There is no automatic upload/publication:
raw store metadata can mention other local containers, and OCI contains the
runner-authored guest arguments/environment. Do not inspect live argv/environment.
The cumulative ceiling is enforced by the original trusted store's write ledger,
including unique blobs, receipts and manifests; failed write reservations are
not refunded. Detached verification checks bounded individual artifacts and
commands, and does not independently recount the entire attempt or establish a
filesystem quota.

## Detached consumption

Require the exact schema/profile/backend and deterministic command path. Read
only bounded nofollow regular files, validate fixed record inventory, source
identities, sizes/hashes, CAS locations, and binding to the same proof and command.
Reparse original raw containers/layers/OCI and all six mount tables; compare the
container-image-layer-root join, metadata rechecks, protected subtree mount
exclusion, ancillary identities/bytes and the original info/inspect control logs.
Then run unchanged v3/v2 observation, resource, workspace and output checks.
The consumer does not query a service or reacquire execution authority.

This is local evidence retention and software validation. All existing false
claims remain false, including immutable custody, complete driver/config closure,
installation acceptance, runtime execution, production admission and online
publication. Full CPython/freezer/static ELF, sealed startup, production CLI,
exclusive fixed-U/writer acquisition and installed-account acceptance stay open.

## Verification plan

Implement the coherent slice in parallel, then consolidate affected tests.
Cover valid capture/replay; missing, duplicate, extra and malformed roles; backend,
schema and cross-command substitution; file/symlink/inode/mode substitution;
same-hash unowned blob adoption; bounded read/write failures and cumulative caps;
metadata, OCI, mount and ancillary drift even after coordinated hash updates;
deadline/cancellation and retained partial failure with no start or new budget.
Preserve all original failures/skips. Fixture checks grant no actual-mechanism or
installation acceptance. A separately identified new-source inert Linux check
may follow software validation; consumed original mixed HEADs are never replayed.

## Verification — 2026-10-29

Frozen tree 1ea11ecd4985a245ebea569371e2fff645be48c2 ran 25 complete files on
Linux: 936 unique, 933 pass/3 failure/0 error/skip in 24.192139 seconds. The three
failures were two new test assertions missing the original error-code prefix.
Only those assertions changed in 69d13f21bb2cc8e89724f7fc8bfc318bc68bf6cf;
all product bytes/modes remain identical. Its one affected complete file passed
21/21 in 1.486206 seconds. Current applicable passing coverage is 936 unique,
including 159 new nodes, across these preserved batches; not one complete CI run.
Both frozen archives contain 2731 source files, unchanged before/after execution.
The original three failures remain recorded. Manifest: 83 groups/65 zero-skip,
expected sum 7299. The earlier pre-fix 113-case development check has no XML and
is not substituted for these final frozen results.

One separately reserved actual Linux inert mechanism run on the new frozen
source passed all six commands with one original 600-second deadline, zero retry:
receipt elapsed 7.987877 seconds, wrapper 8.248112 seconds. Raw snapshots and
event receipts are retained, with source and report/input/output cross-pins.
It exercises finite static-C helpers and dependency/report consumption only;
complete CPython, solver/runtime, immutable custody and installation remain open.
All original failed runs and root prerequisite skips remain retained.
