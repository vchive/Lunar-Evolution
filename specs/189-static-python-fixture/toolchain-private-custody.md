# Complete toolchain private-copy setup and the open custody gate

Status: internal materializer implemented and independently reviewed. The
slice below is a real complete-tree materializer. It is **not** an
immutable-custody implementation, a new inventory DTO, or a build permission.
G1 custody, G2 configured build and G3 runtime acceptance remain open.

## Scope and environment decision

The intended custody interval remains: the same held Zig archive bytes supply a
complete private tmpfs copy, exact archive modes are installed, the input mount
is enforced read-only, capabilities and nested user namespaces are disabled,
the existing complete observer and one fixed inert reader consume that same
root, and the original process chain is fully drained before completion.
Archive members are data only; no Zig, CPython, configure, freezer, solver,
WebAgent or remote evaluator may run in this slice.

Two constraints prevent claiming that complete bubblewrap interval today;
they are not a conclusion that all read-only worker mechanisms are unavailable:

- Pinned bubblewrap 0.11.1 source has a cumulative `MAX_ARGS=9000`, including
  arguments read through `--args FD`. The complete Zig inventory has 19,546
  files; its `--file FD DEST` arguments alone would number 58,638. Multiple args
  files do not reset the counter. Keep legacy recipe-v1's 16,384 files and
  1 MiB limits unchanged; do not truncate the tree or modify bubblewrap.
- On 5090gpu, the tiny installed-bubblewrap setup copied files with `--file`
  into private tmpfs and used bubblewrap's own `--remount-ro` before reader
  execution successfully. The later **exec'ed child**, with effective
  `CAP_SYS_ADMIN` and `CAP_SETPCAP`, received `EPERM` on its read-only remount.
  A separate nested installed bwrap's `--unshare-user` also failed with `EPERM`.
  Those two later failures refuse their repair paths; they do not negate the
  earlier setup-time success. Preserve all three observations independently.

A separately scoped two-stage inert probe subsequently succeeded using the
already-running rootless Podman/crun/VFS service, read-only scratch-image inputs
and actual generated-output readback followed by a new protected image. See
`podman-inert-custody-observation-20261028.md` for first-failure preservation,
source/evidence pins and the exact trusted-custodian boundary. This is narrow
worker/transfer feasibility, not a full archive replay, integrated build backend
or G1 acceptance. No host policy, group or privilege change was required.

The selected executable binding for any future bwrap probe is the independently
pinned, root-owned, non-writable installation pathname `/usr/bin/bwrap`, with
held no-follow ancestry and source identity checks. This preserves the observed
AppArmor transition; executing a memfd copy is not assumed equivalent. The host
Python/helper installation is a diagnostic dependency, not a frozen build
helper closure. Do not modify AppArmor, raise privileges, add a mount service,
or invent a general supervisor to make this slice pass.

The rejected nested candidate would leave its inner bwrap monitor in the
outer writable mount namespace. Hiding that namespace from the reader would
not establish a globally immutable mount. Same-uid host `/proc` aliases and
the remaining monitor's authority would need their own proof; none exists.
An unsupported custody preflight must refuse before creating the copy or
starting a consumer. An ordinary host directory cannot serve as its fallback.

## Implement now: internal complete-tree materializer

Add `tools/static_python_rsi_fixture/toolchain_private_copy.py` with this private
entry point:

```python
def _materialize_toolchain_copy(
    snapshot: StaticPythonArchiveSnapshot,
    manifest: bytes,
    *,
    expected_manifest_sha256: str,
    destination_directory: str,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> StaticPythonToolchainObservation:
    ...
```

There is no profile-bypass entry point or runtime flag. Focused inert tests
explicitly replace the existing archive/manifest test profiles with fixed local
pins, acquire their snapshot through `snapshot_archive`, and exercise the same
complete production checks. Neither copied files nor a CLI/production launcher
are executed or connected in this slice.

The caller supplies one existing held snapshot, the complete canonical
extraction-manifest-v1 bytes and their independent SHA-256 pin. Use
`toolchain_tree_observation._manifest` / the existing manifest validator and
`archive_observation._observe_archive_snapshot(capture_all_files=True)`.
Validate the original deadline and checkpoint throughout. One bounded archive
walk supplies every regular-file payload; never reopen an original extracted
tree or obtain file bytes from caller paths. Its manifest bytes and digest
must equal the separately supplied complete canonical manifest exactly.

The destination is a new leaf, corresponding to the manifest root member,
under an existing caller-owned private parent. Require an absolute normalized
path, no-follow acquisition of every ancestor, and an effective-uid-owned
direct parent with exact mode 0700. Refuse an existing leaf of every kind,
including empty directories and symlinks. Do not follow or replace it. Hold
original ancestor, parent and new-root identities through copying and final
observation; a replaced directory entry must not redirect writes or the
observer. This is a setup boundary under a trusted controller, not resistance
to arbitrary concurrent descriptor-table rebinding or a privileged host.

Before the first destination mutation, validate the full canonical pin,
archive/snapshot/profile binding, explicit parent-directory inventory, supported
modes and all complete payload/count/size/hash matches. Keep the current
32 MiB manifest, 65,536 members, 256 MiB per-file, 1 GiB file-total, archive
decode/path/depth ceilings. Initial supported modes are directories 0755 and
files 0644 or 0755, matching the complete real Zig archive. Reject other valid
manifest modes explicitly rather than normalizing them or promising unreadable
mode profiles. Preserve every explicit directory, including empty ones.

Create the root/directories privately as 0700 and files with no-follow,
create-exclusive regular-file opens at 0600. Use held directory-relative opens;
bound each write by its checked payload and handle partial writes. Owner access
must remain available under the process umask (077 is supported); an extreme
umask removing owner traversal may safely refuse after mkdir and retain that
partial directory. Do not change the process-global umask or chmod a reopened
path to manufacture access. Verify
regular kind, original identity, nlink 1 and complete size/hash. Install exact
file modes, then exact directory modes deepest first, with the root last.
Neither chmod 0444/0555 nor executable-bit projection is equivalent to the
archive modes. UID/GID equality with tar metadata is not claimed.

Close every writer before calling the existing
`observe_extracted_toolchain_tree` against the actual newly created root and
the original manifest pin. Compare its observed root identity with the held
new root, recheck held path edges, and return its existing observation only
after all owned-descriptor cleanup succeeds. After the final caller-clock
callback, recheck every original file identity and each directory's complete
metadata and exact child inventory. Bound this final sweep and cleanup with
the last original-clock value plus elapsed internal monotonic time, without
another caller callback or a new deadline. This remains a sequential check.
The result's manifest bytes and
digest remain unchanged, and **every existing observer claim remains false**,
including immutable custody, future consumption, build, runtime and admission.
The path is a caller-owned partial/setup artifact; the observation does not
make it a live custody capability or authorize a later build.

Preflight available descriptor capacity against held ancestors, a bounded
directory traversal and one current file plus the existing observer's maximum
simultaneous descriptors. Never keep one FD per archive file or raise OS
limits. Count compressed, decode, captured payload and manifest allocations
under their existing individual ceilings; this does not implement a total RSS
hard limit. No growing-host-file read or unbounded helper output is introduced.
This primitive has no argv transport, process or log
budget because it spawns nothing.

## Failure and partial-directory policy

Raise `StaticPythonToolchainCopyError`, exposing a fixed `.reason` beginning
`static_python_toolchain_copy_`, without paths or archive bytes. Minimum
distinctions are invalid deadline/clock/destination/manifest or snapshot,
unsupported mode, resource refusal, destination exists, path/identity drift,
copy failure, observer failure, wall timeout and `cleanup_unknown`.

Invalid input/preflight refusal must leave the destination absent. Once a root
has been created, retain its partial tree on every failure. Never overwrite,
roll back, recursively delete or chmod an unknown path during error handling.
The caller may inspect the retained partial evidence under its original parent;
it cannot be reused as a completed copy or custody authorization. This is a
sequential create-and-observe primitive; it does not resist arbitrary same-uid
concurrent rename/write access, establish durable persistence, or enforce
immutability after the observation.

Every owned FD is registered immediately on acquisition with its original
identity. Cleanup attempts every role even after `BaseException`, timeout or
KeyboardInterrupt, without requiring an unexpired execution budget. Clear
private ownership before a close attempt; do not retry an uncertain numeric
close. Skip a known foreign reused FD and mark cleanup unknown. Preserve the
first failure and add the cleanup-unknown note; if no primary failure exists,
unknown cleanup is itself a refusal. Reuse the existing executable owner's
release semantics where applicable, without reclassifying data as executable.

## Changed files and validation

Implementation changes are limited to this spec, the new private copy module
and focused tests. A short follow-up in `tasks.md` / `plan.md` may distinguish
the completed copy primitive from the still-open enforcement gate. Leave
legacy execution backend, public source-placement DTOs, native-v1/v2 FD ABI,
observer claims and Feature189 scripts' exit-78 refusals unchanged.

| Area | Required validation |
| --- | --- |
| Real copying | Inert archive with 0644/0755 files, nested and empty directories; actual complete tree equals pinned manifest and existing full observer result. |
| Complete inventory | Inert 16,385-file archive is fully copied/observed; no recipe-v1 fallback, role split or truncation. |
| Early refusal | Wrong/missing/noncanonical pin, archive mismatch, missing explicit parent, unsupported mode, low FD allowance, invalid/expired clock; destination stays absent. |
| Placement | Existing file/directory/symlink leaf; nonprivate/foreign-owned parent; ancestor/root/name replacement and symlink/hardlink substitution fail closed. |
| Partial failures | Short/zero writes, disk/open/chmod/hash/observer failure, timeout and KeyboardInterrupt preserve first failure and partial tree while attempting all owned closes. |
| Ownership | Failure immediately after open, unknown close and foreign FD reuse never close another owner's descriptor or return a successful observation. |
| No claims | Existing observation has all false claims; ordinary host copy does not pass custody preflight; no archive member or subprocess executes. |
| Regression | Existing archive, verified-input, toolchain observation/tree and legacy backend suites; focused pytest, Ruff, compileall and `git diff --check`. |

Independent inert tests and review precede any complete real-Zig data-only
materializer replay. Such a replay would prove copying/observation only. A
future custody mechanism still needs a supported AppArmor-compatible binding,
actual read-only enforcement, alias/FD handoff checks and an original lifecycle
chain that drains setsid/double-fork descendants with `__WALL` until `ECHILD`.
Popen wait, an FD owner or a process-group probe cannot replace that proof.

## Inert validation (2026-10-24)

The final combined selection passed 433 tests with zero failures, errors or
skips, using one fresh external pytest basetemp. It includes 39 materializer
tests and 15 independent ownership/observer counterexamples; the independent
15-test run overlaps and is not additive. The actual 16,385-file inert copy
exceeds both legacy file-count and recipe-wire bounds without changing them.
Whole-repository Ruff, src/tools/tests compileall and diff checks pass.

Independent review first reproduced two refusals missing from the initial
implementation: an observer omitting a false claim, and a final clock callback
adding or deleting nested inventory. Both now refuse. The final sweep uses
the original budget with an internal elapsed-time anchor and no further caller
clock callback. This remains a sequential observation, not concurrent atomic
custody. Complete real-Zig copying and the unsupported custody interval have
separate acceptance status.

## Complete real-Zig data-only replay (2026-10-24)

One replay on 5090gpu uses exact source commit
`a9b75116c3de6475785153eeb787d80985b94447`, tree
`7c72cd8b122308a77bc6f5a66494035f287b0530`, and CPython 3.11.15 with `-I -S`
and no optimization. It creates and observes all 19,546 files and 1,286
directories (20,832 members; 357,913,169 file bytes). Snapshot acquisition plus
materialization takes 11.002850472927094 seconds. The original 120-second
deadline also covers the independent remote complete walk/hash, loaded-module
checks and source-after comparison: 11.696064406074584 seconds. Runner elapsed
is 11.891156604979187 seconds, exit code is zero, stderr is empty, and the
exclusive launch marker records exactly one launch. No archive member runs.

The independent review compares all 2,327 source files to the exact Git commit
and source archive, checks all eleven loaded modules, and verifies transferred
types, modes, sizes and hashes for thirteen indexed root files plus the index
itself. The copied Zig tree is not transferred for a second local walk; local
review verifies the remote complete-walk receipts bound to the independently
reviewed runner and input pins. All ten observation claims remain false. This
closes the data-copy replay only, with no immutable interval, build-consumption,
compiler, runtime, solver or production acceptance.

Evidence is retained under this worktree's ignored
`.lunar-evolution/validation/feature189-20261024/real-zig-copy-a9b75116-u3wmfaf9/`;
the remote disposable directory is
`5090gpu:/home/qinzhiqing/vchive/lunar-feature189-data-copy-a9b75116-p4ys47mv`.

| Evidence | SHA-256 |
| --- | --- |
| Original Zig archive | `70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00` |
| Complete extraction manifest (3,926,082 bytes) | `b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90` |
| Exact source archive | `d403c6dbf2b70da836e7819908f36150054643ded3850eab9f4a40d1bd2889bf` |
| Source-file index | `48dde5ed4e916bdd03381fc962ce91329f47bc89e34c1035def6069670ca9ed5` |
| Fixed replay runner | `94929af6a15d23ae7ccc9a20e28235be96655a8e6e3cf220aeec0bef23fb5857` |
| Tree observation | `5bfeda0e4ad59e5078fd5d2e1de7acc955d4306fb1cf300f5608e10abd0b381a` |
| Transferred bundle | `787c11242486fc7cf1302a16a7b9195e8770fcdba801c9b25e411cdca04cd69a` |
| Root evidence index | `3abd7f53f31c3030fd17bf55b20a8993d9da7238b9e95815abc87e95df80ac73` |
| Independent review JSON | `7c0f997f4fb32b0d81864452178cfd99379652bcb2be41887666f9206931a68a` |

The same source's Linux focused selection separately passes all 54 cases with
zero failures, errors or skips (pytest 4.09 seconds). Its command, log, XML and
summary transfers match their four pins under ignored
`feature189-20261024/lunar-feature189-focused54-a9b75116-lop0bqmg/`.
JUnit XML SHA-256 is
`8cabd0f6554fb4c2fbdfd9750bc186ad17b11bfedc2a732f153fcad4fd12b398`.
This is focused coverage, not complete three-version CI or G1/G2/G3 acceptance.
