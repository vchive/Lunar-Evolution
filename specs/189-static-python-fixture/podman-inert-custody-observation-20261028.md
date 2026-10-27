# Rootless Podman: narrow inert custody observation

Status: **the tiny read-only worker and generated-output transfer were actually
observed; the complete build backend and G1 acceptance are not implemented or
accepted**. This investigation used ignored diagnostic sources and artifacts.
It did not modify product sources, run CPython/Zig/configure/freezer/solver,
call a model/evaluator, start a VM, pull an image, or change host policy,
privileges, groups or AppArmor. No test/CI/merge result is inferred from it.

## Corrected environment conclusion

5090gpu is not generally unable to provide a read-only worker view. Its existing
rootless Podman service accepted the finite scratch-image probe below. The
trusted host, Podman/crun and rootless VFS custodian are the stated TCB; the
probe does not protect against a hostile same-uid host process changing that
custodian or image store. A trusted image custodian's retained write authority
does not erase the worker's observed read-only boundary, and the observation
must not be promoted to stronger hostile-custodian protection.

The earlier bubblewrap results also need their exact scopes retained:

- The tiny setup that copied files with `--file` into private tmpfs and used
  bubblewrap's own `--remount-ro` before executing the reader succeeded. The
  reader observed `EROFS`, zero capability sets and `no_new_privileges=1`.
- A later **exec'ed child** attempting a read-only remount received `EPERM`.
  A separate nested installed-bubblewrap user-namespace creation also received
  `EPERM`. These refuse those later repair paths; they do not negate the earlier
  setup-time success.
- Pinned bubblewrap 0.11.1 has cumulative `MAX_ARGS=9000`, including `--args FD`.
  The complete Zig inventory contains 19,546 files and needs 58,638 `--file`
  tokens before directories/modes. This remains a real full-inventory transport
  limitation; the tiny successful setup cannot replace that inventory.

The QEMU/KVM/TCG findings in `build-vm-custody.md` remain separate. No supported
accelerator was made available or VM started by this investigation.

## Existing service and fixed probe

The probe used the already-running service through exactly:

```text
/usr/bin/podman --remote --url unix:///run/user/2110/podman/podman.sock
```

Read-only service inventory reported Linux/amd64, rootless mode, VFS storage,
seccomp enabled and `/usr/bin/crun` 1.21. The installed Podman CLI's help was
checked for all remaining `create`, `import`, `start` and `wait` flags before the
corrected execution. No replacement daemon or generic executor was introduced.

One purpose-built native C diagnostic was compiled statically with the existing
`/usr/bin/cc`; this helper is a **diagnostic dependency**, not an independently
accepted build helper. ELF inspection required x86-64 and rejected `PT_INTERP`
and `PT_DYNAMIC`. The helper's source SHA-256 was
`ee1c917c46970afa6d75a773021a143ca93f55154322a0c097dcb17ebe74c8bb`;
its executable was 964,688 bytes with SHA-256
`1805947f9b29abfacd2c1c0ab339a805430dfad0d5ee6c1d421e68a62b33c4bb`.
The compiler executable SHA-256 was
`b5f1b773a7c733738352000c92a077dc5852a1a2fc6d836b1e411be1e9ec5f88`.
These are retained observations, not new production authority.

One original 120-second monotonic budget covered both phases, collection and
failure cleanup. The last eight seconds were reserved for failure cleanup.
Container/image identities were retained; no failure triggered automatic retry
or a replacement consumer. Scratch imports needed no image pull. Containers
used `--pull=never`, `--network=none`, private PID/IPC/UTS namespaces,
`--read-only --read-only-tmpfs=false`, a separate one-MiB writable output tmpfs,
`--cap-drop=ALL`, `--security-opt=no-new-privileges`, explicit entrypoint/cwd and
fixed locale. `--http-proxy=false` and `--no-hosts` were retained. This records
the supplied runtime configuration; it does not claim an exhaustive audit of
every Podman-generated metadata file or network syscall.

## Preserved first failure

The original driver specified both `--network=none` and `--dns=none`.
Compilation and the first scratch-image import succeeded, but `podman create`
returned 125 with:

```text
Error: conflicting options: dns and the network mode: none
```

No container was created and no consumer ran in that attempt. It is a CLI
configuration refusal, not evidence against read-only container isolation.
The original source and failure were retained. A separately authorized corrected
source removed only `--dns=none`, kept `--network=none`, used a new directory and
source hash, and executed once.

Initial local evidence directory, relative to the main workspace:

```text
.lunar-evolution/validation/parallel-batch-20261027/podman-inert-custody-gsxmj55i/
```

Its evidence-manifest SHA-256 is
`49a60fd4a1f131e9697dfc10f6a8e8be72d15ce19792b03d67283afbcdb6612c`.
The original result SHA-256 is
`6cfa74518ee3cc8f58a0bc5437657417b26fb5db057e85e5577903c4b390e2bf`.
The imported image was retained as
`sha256:1924fc5e8e3d56022f7f6e9e83f6beaa80c8400b5be0386eb9e4b4f231de4c5a`.
The original remote evidence lives under
`/home/qinzhiqing/vchive/lunar-podman-inert-YsUW1Ayg`.
Its actual window was 2026-10-27 19:20:46.625682–19:20:46.930259 UTC.
This overlapped the end of another mixed run. No absence of interference or
causal explanation of that run's timeout is claimed.

## Actual corrected two-phase result

The corrected driver SHA-256 is
`d85d42651d44222658a494d1b3e9faedebfef1b0553861c5ff23f04736629be9`.
Its remote directory is
`/home/qinzhiqing/vchive/lunar-podman-inert-UQPg70f6`.
The retained source/result write timestamps bound the execution to
2026-10-27 19:26:04.365572–19:26:05.238155 UTC. Its own original monotonic
elapsed measurement was **0.872717729 seconds**.

Phase A imported a deterministic scratch filesystem containing only the static
helper, one fixed input and the declared directories. After import, the host
source input's bytes were actually changed on the original inode. The consumer
still read the original imported bytes. It independently checked root
read-only/output writable state, PID 1, all capability sets zero and
`no_new_privileges=1`; write, create, rename and chmod each returned `EROFS`.
It generated the actual 26-byte `/output/generated.txt`, then remained alive
behind a fixed stdin gate while the controller inspected the original container
and independently copied that file out. The readback SHA-256 was
`dc3e04bcf29c8a42a7b34a95efa6779768fe3d71f3d9e611776f2de4f0773915`.

Only after the original gate was released and phase A's original process exited
did the controller construct and import a second scratch filesystem from those
actual read-back bytes. Phase B consumed that generated file under the same
read-only/output and process checks. Both containers exited with code zero.
The controller matched each live helper's reported PID namespace to the
runtime's original host PID, retained `/proc/PID/stat` starttime, and confirmed
that original process identity absent or replaced after exit. Numeric namespace
identities were reused between the sequential phases; their equality is not a
proof of namespace lifetime or complete namespace disappearance.

Original identities:

| Phase | Container ID | Imported image ID |
| --- | --- | --- |
| A | `fe72e153a5e395e99b4da361e3f2cfbfebdd64da22a4b8e4ec102b9a2db5e727` | `sha256:338f8527acd1e64b8e624825b951d341b316b9c5bc4a73408964c46c6c54fdbc` |
| B | `bcdda29eef55fe90348fd5a5440ce9c9ef41e92b4851c46b9188d5b791876b8c` | `sha256:36c142783402308fcb8b6251d47520b926202ceb22b4e5b0101b3cbab97353cb` |

The corrected local evidence directory is:

```text
.lunar-evolution/validation/parallel-batch-20261027/podman-inert-custody-dns-fixed-xnu34gl4/
```

All 64 `remote-originals` files were copied back and SHA-256/size matched against
an independent read-only remote file manifest. Local driver/helper sources also
matched the original remote `source-pins.json`. The local evidence-manifest
SHA-256 is `76cbc51e85df1832d66d0048a4efcf215d2a6edb2df89e7178ee3ae3d138c2e0`;
the original corrected result SHA-256 is
`67bef467d6b51e7de0a0fdbed9e1d0239665799ec4de58672b00e1661738bd2e`.
Containers, images, commands, stdout/stderr, actual readback, tar inputs and
partial evidence were retained. No cleanup proof is inferred from removing an
evidence path, and no old mixed run was retried.

## What remains open

The finite experiment establishes a feasible trusted-custodian worker read-only
view and a real input → generated-output readback → new protected-image →
consumer transition. It does **not** establish any of these:

- Complete source/toolchain/archive inventory, exact archive modes/directories,
  original held-archive-to-image binding, or protection against hostile host
  custodian/store modification.
- A complete configured `pyconfig.h`, generated and declared musl/CRT/compiler_rt
  support, complete driver/helper/config/cache closure or actual CPython build.
- Arbitrary namespace/FD/mount-alias attacks, an exhaustive consumed-input
  observer, supported syscall semantics, complete descendant/namespace drain,
  production resource exhaustion behavior or actual native runtime startup.
- Integration with `run_dependency_checked_build` → `run_pinned_build_v3`, an
  accepted installation/runtime, native RSI CLI, solver correctness or release.

The diagnostic explicitly retained `g1_custody_accepted`,
`driver_inputs_verified`, `complete_namespace_disappearance_verified`,
`production_admission` and `online_publication` as **false**. The software work
needed to connect the original build path is drafted separately in
`../193-static-python-rsi-launch/podman-custody-integration-draft.md`.
