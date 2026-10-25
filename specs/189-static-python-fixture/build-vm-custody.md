# One-shot build VM custody: unselected environment design

Status: **design only; unselected, unimplemented and unaccepted**. This is a
possible alternative environment for G1, not a supported fallback for the
current bubblewrap recipe. G1 immutable custody, G2 configured build and G3
runtime acceptance remain open. No VM was started for this design.

## Scope and existing boundaries

The existing complete-tree materializer, exact archive modes, full inventory
and original held archive/manifest binding remain required. Preserve the two
independent 5090gpu failures: the read-only remount returned `EPERM`, and the
nested installed bubblewrap user-namespace operation returned `EPERM`. A VM
design does not retroactively make either path supported.

The restriction in `toolchain-private-custody.md` against changing AppArmor,
raising host privileges, adding a mount service or inventing a general
supervisor remains in force. A fixed, one-shot VM with no host filesystem
mount service is not inherently one of those mechanisms. This document does
not authorize a generic VM manager, a persistent daemon, arbitrary guest
commands, host mounts, self-authorized group changes or elevated execution.
The user's existing authorization to prepare ordinary missing dependencies on
5090gpu remains applicable; this draft adds no VM-launch authority. The
existing selected tmpfs interval is not silently replaced by this draft.

Before any future consumer record, `candidate-build-provenance.md:110-135`
still requires a demonstrated enforced mechanism and complete configured
source-input closure. Do not introduce a new DTO, receipt wire, build entry
point or production-admission switch while those obligations remain open.

## Read-only 5090gpu findings and current refusal

An inventory performed as uid 2110, gid/group 2100 found:

- `/usr/bin/qemu-system-x86_64` is installed, root-owned mode 0755 and
  31,328,048 bytes. The installed qemu-system-x86/common/data package version is
  `1:10.2.1+ds-1ubuntu3.2`. Its executable SHA-256 is
  `0cd4112a8f0cb891eb7c10e8df38c9dfeec8c7389bb22db6aa425f0d6fe733dc`.
  This observation is not a frozen QEMU/helper closure.
- `/dev/kvm` exists, root:108 mode 0660. The executing uid has neither read nor
  write access and is not in group 108. Loaded kvm/kvm_intel modules do not
  establish accelerator access. No KVM device was opened or ioctl attempted.
- `/boot/vmlinuz-7.0.0-38-generic` is root-owned mode 0600 and unreadable to the
  executing uid. Its initrd is readable, but neither constitutes an approved,
  complete guest boot closure. Do not change permissions or use sudo to read it.
- Installed QEMU documentation describes TCG. The parent agent separately
  reported that `qemu-system-x86_64 -accel help` listed `tcg`, `mshv`, and `kvm`
  on 2026-10-25; that enumeration is a parent observation, not an independently
  retained result of this review. No VM or accelerator was started. Listed
  names do not prove initialization, isolation, resource limits or runtime
  under the original budget.

The installed `system/security.html` explicitly requires a virtualization
accelerator such as KVM or HVF and a listed supported machine type for its
virtualization security policy. It places TCG in the non-virtualization use
case and says users **must not rely on QEMU to provide guest isolation or any
security guarantees**. Accordingly TCG is not an accepted isolation or G1
custody fallback. A separately scoped, trusted inert TCG diagnostic could
observe image transport and timing only; it could not close these gates.

The current environment must refuse production-custody selection before image
construction or a consumer launch. Installed QEMU alone is insufficient. Do
not increase privileges, change host policy or group membership on the agent's
own authority, silently switch accelerators or increase an existing deadline
to make this draft pass. Ordinary dependency preparation may proceed under the
user's existing authorization. If an administrator separately provides access
to a supported accelerator, that only removes one environment prerequisite:
full source, helper closure, input/view custody and deadline verification are
still required before acceptance.

## Fixed input and separate output boundary

A future implementation would accept one fixed complete source/toolchain input
closure, not a caller-selected host directory:

1. Acquire and retain the original archive snapshots and independent complete
   canonical manifests under existing bounds. Construct one finite filesystem
   image from those held bytes, preserving every regular file, exact supported
   mode, explicit directory and empty directory. Any temporary materializer
   path used by the image generator needs its own enforced custody proof;
   verifying the image only after import does not prove it used the held bytes.
2. Retain the **whole** resulting image in an original-owner memfd; verify its
   complete inventory and independent digest, exact size and inode identity.
   Confirm `F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL` on that
   same held inode before QEMU or any reader receives it. `F_SEAL_FUTURE_WRITE`
   alone is insufficient because prior writable shared mappings may survive.
   Never reopen a mutable pathname in place of the held image.
3. Bind that exact memfd to a fixed raw virtual block device, with writes
   rejected by the host seals as well as the QEMU block/device configuration.
   Disable image-format probing, writable backing chains, external data files,
   snapshots, host-file import fallbacks and arbitrary block-node additions.
   The precise inherited-FD route, read-only open requirements and original FD
   identity need validation against the frozen QEMU implementation.
4. Mount that device read-only inside the guest and expose the same root to
   the complete observer and the fixed consumer. The input root must not be
   hidden by writable overlays, overmounts, aliases or per-process replacement
   mount views. A guest read-only mount is not by itself global immutability.
5. Provide a different bounded writable output device/filesystem. Source and
   toolchain inputs cannot live on it. Generated headers, compiler outputs and
   eventual artifacts are separately identified outputs, not evidence that a
   writable source-input tree is acceptable. No host output extraction may
   execute guest programs or traverse uncontrolled image paths.

No host directory sharing is allowed: no 9p, virtiofs, shared-folder device,
FUSE export, host bind mount, passthrough block device or arbitrary host path.
Do not attach network devices/backends, user networking, TAP, forwarded ports,
vsock, migration, VNC, SPICE, QMP or an interactive monitor. Use one finite,
bounded control/result channel with a fixed inert protocol; do not permit it
to select paths, execute host commands or modify the VM/device graph.

## Guest and host authority obligations

Freeze the guest initialization sequence that performs setup, then drops
writer and control authority before any observer/consumer runs. The fixed
consumer must not retain mount/device-management privileges, writable raw
input-device aliases, a privileged setup process, user-namespace creation,
control channels or a path to different input contents. Account for inherited
FDs, open file descriptions, guest `/proc` access, kernel modules, executable
helpers, guest mount namespaces and any remaining init authority. An input
image may be byte-immutable while the filesystem view observed by a process
is replaced; both properties require evidence.

Run the host QEMU/helper chain as the existing non-root user, without changing
host policy or credentials. Account separately for same-uid host `/proc`, FD,
ptrace and writable-memory/control aliases. Input seals prevent image-byte
mutation; they do not freeze QEMU memory, its emulation behavior, guest RAM,
the selected block graph, helpers, loaded code or what the consumer sees.
A parent-held FD, trusted-helper exit, a guest read-only flag or a hash before
and after the run is insufficient to discharge those obligations.

Retain original image references until the original process chain is drained.
Prove that no writable image or alternative backing reference remains usable
by a guest/host authority that can change the observed view. Reopening through
`/proc/PID/fd/N` does not substitute for seal and identity checks. Explicitly
separate a trusted host controller from guest-controlled replies; do not
accept self-reported guest hashes or shutdown messages as independent proof.

## Closure that must be frozen before mechanism selection

The proposed closure must cover the exact guest kernel and configuration,
initrd/root/init and all guest setup/observer/reader helpers, filesystem driver,
input-image generator/parser and all real source/toolchain support files. It
must also cover QEMU's exact executable, machine/accelerator/device model,
command/environment, dynamic loader, libraries, optional modules, firmware/ROM,
configuration and host launch/extraction helper dependencies. Disabling default
user configuration/devices is necessary but is not a complete closure proof.
A host diagnostic Python installation is not automatically a frozen helper.

Pin one accelerator explicitly. No accelerator list, auto fallback, restored
snapshot, migration, replay of an old guest state, plugin or dynamic device
configuration is allowed. A readable approved guest kernel/initrd and a
supported non-root accelerator must exist before selecting an isolation
mechanism. Any proposed exception for a trusted inert diagnostic must retain
false custody/build/runtime claims.

## Deadline, resource and original-chain completion

Use one original absolute monotonic deadline across image construction,
launch, boot, observation, consumer and shutdown/drain. Every preflight,
bounded read/write, image decode and control/result exchange must checkpoint
that same deadline. Bound image size/counts, memory, vCPUs, output bytes,
control messages and disk writes before launch. Slow TCG or boot cannot mint
another allowance. A missing supported accelerator, incomplete closure,
expired budget or unprovable custody is a refusal before consumption.

Maintain authority over the original launcher/QEMU/helper process identities
and their complete descendants. On deadline or failure, use only that retained
authority to terminate and drain them; reject reused PIDs/groups and unknown
ownership. Do not launch a repair/retry VM. Preserve partial evidence and an
unknown/failed terminal state if the original chain cannot be proven drained.
Guest poweroff, QEMU exit, a helper exit, result-channel EOF or an output file
alone does not prove descendant cleanup or correct consumption.

## Smallest later validation sequence

This design adds no permission to run a build. After mechanism and closure
review, a separately bounded inert probe could test only one tiny sealed input
image, one fixed reader and one separate output, with networking and host
shares absent. It must independently check complete image-to-guest tree
binding, exact modes and directory entries; rejected host/guest writes,
namespace/view replacement attempts and original FD aliases; unavailable
accelerator and budget refusals; and complete original-chain shutdown.

A tiny success would establish only its actual finite interval. The real
complete source/toolchain replay remains separate and cannot truncate the
inventory, increase bubblewrap argument limits or reuse the tiny result as
build authority. Configure, freezer, compile/link and G3 runtime acceptance
remain later gates. Ordinary model-case smoke results are unrelated evidence.

## Retained read-only evidence

Local ignored evidence directory:
`.lunar-evolution/validation/feature189-20261025/one-shot-vm-readonly-review-31sj1nhj/`.
It contains the exact compact inventory, package query and installed QEMU
invocation/security documentation. No VM, KVM ioctl, mount, package install,
permission change, code build, solver or evaluator was executed by this review.
