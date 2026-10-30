# Opt-in in-image live-module private sink

## Scope and current boundary

`fixed-live-modules-private-sink-v1` is a separately selected build source
profile. The original launcher, source-plan pins, control v1/v2 bytes and
unselected runtime closure remain unchanged. No production admission flag is
enabled. This extends the original native trusted attempt; it never creates a
second process launcher, accepts solver JSON as authority or uses stdout as a
collector channel.

The installed caller supplies an exact immutable sink request containing the
expanded installation, independently selected image bytes and composed frozen
main source. The native runner checks their image digest against the original
attested target and the RSI manifest against the original terminal argv marker.
This comparison request is not custody or installation acceptance.

## Original ownership and control v3

The original trusted host creates a fresh anonymous pipe before its existing
`Popen`. Only its write end is inherited by the original bootstrap; the read
end stays in the host. Linux control v3 is the complete v2 grant record followed
by `u32 source_fd, u64 pipe_device, u64 pipe_inode, u64 deadline_monotonic_ns`
(big endian). The deadline must equal the original native guardian deadline.
No path, environment selector or candidate-selected descriptor is accepted.

The bootstrap verifies PIPEFS/FIFO, write access, original device/inode and
disjointness from control, gate, frame, lifeline, guardian, broker, executable,
grants and newly allocated exec-error descriptors. It preserves only this
additional slot through the existing close-range/grant isolation sequence and
maps it to fixed target FD 198. A collision with FD 198 is refused rather than
overwritten. The bootstrap parent closes its copy immediately after fork. Its
target environment contains only the original decimal monotonic deadline in
`LUNAR_FIXED_LIVE_DEADLINE_NS`; the target FD number is fixed in reviewed C.
The independent guardian never inherits either sink end.

## In-image sequence and failure semantics

The separately pinned C launcher validates the original argc/marker/digest,
pipe slot and canonical deadline, initializes the fixed isolated interpreter,
imports only the reviewed frozen `_lunar_static_main`, and explicitly invokes
`_lunar_collect_live_modules(manifest_sha256)`. It accepts an exact `bytes`
result of 1..128 KiB ending in LF. Nonblocking writes/poll consume the original
absolute deadline. After the complete write, FD 198 is closed before fetching
`_rsi_launch` or importing the solver. Every refusal closes the slot and exits;
it cannot continue into candidate code. The collector asset remains byte-exact.

The host registers its bounded nonblocking reader before releasing the original
execution gate and drains synchronously after the original target_started frame.
The bootstrap emits that frame on exec-error-pipe EOF before waiting for the
target, so a collector waiting on pipe capacity cannot block that frame. There
is no extra reader thread or process. The host reads at most 128 KiB plus an
overflow sentinel and requires
EOF by the same original attempt deadline. It compares the canonical complete
collector table, selected source, image bytes, original sealed image
device/inode, original native target PID and original manifest digest. Missing,
partial, oversized, late, wrong-image or drifted material is a fixed refusal.
Reader cleanup closes the original read FD synchronously and cannot renew the
deadline. The solver can start after complete write/close; no host-comparison
ACK gate is added. Sink results stay separate from stdout, broker
replies, execution receipt, output admission and publication authority.

## Validation plan and acceptance gates

Focused tests cover default byte preservation; v3 round trip and collisions;
wrong pipe identity/direction; source/manifest/image/PID drift; empty, partial,
oversized and no-EOF streams; original deadline expiry; launcher call order and
closure before solver; and source-profile recipe pin selection. Source/C
harness checks do not establish real static-image custody. The actual selected
x86 image still requires an accepted native x86 Linux build/runtime and the
existing custody/lifecycle gates. ARM emulation, host Python and solver
self-report cannot substitute for that acceptance.
