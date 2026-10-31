# Parallel original-worker boundary enforcement

This continues Feature 193 on `codex/parallel-build-closure`. PR203 remains
frozen on its original CI attempt while this successor is developed. Complete
all three software slices before a single concentrated affected regression;
retain any genuine failure and validate only the necessary correction.

## P0 and parallel P1 scope

P0 is PR203 final CI, independent source/original evidence review and verified
main integration. It can proceed independently of the following P1 work:

1. Verify that the original initialized worker is the thread-group leader and
   PID 1 of its held private PID namespace. Check bounded original proc status
   at both live boundaries, alongside existing start ticks, namespace handles
   and original pidfd. Original successful attach, wait and state plus that
   same pidfd's terminal event must precede output readback.
2. Walk the original held worker root before start. Permit only fixed image
   directories, the original checked kernel-mount vocabulary and pinned
   ancillary metadata. Reject extra data/config/helper entries; scratch must
   be initially empty and output must contain only declared parent directories.
   Source/toolchain/prior role inventories retain their independent full walk.
3. After copying outputs, verify the complete original output role through its
   held FD against the copied pins, sizes and execution bits. Refuse missing,
   extra, linked or changed files, and replacements during the verification
   walk, before completing the command and
   allowing the next command to consume prior outputs.

The helpers occupy separate new modules and tests. The original lifetime and
custody integration, CI inventory and documentation have one owner. No agent
runs a separate test campaign while the shared source is still changing.

## Compatibility and evidence

Only the explicitly selected original worker-input-view backend gains these
enforcement gates. Old runner defaults and successful report/profile/candidate
wire shapes remain unchanged. The original runtime policy transfers its checked
metadata and kernel destinations privately; a detached receipt cannot supply
the production transfer. PID status enforcement adds no replayable status role
to the older lifetime schemas. Their old detached readers remain finite old
observations and cannot attest that new gates ran.

Namespace-init terminal semantics require Linux procfs/pidfd and the existing
private PID namespace, no capabilities, no-new-privileges and exact seccomp
policy, including refusal of setns/unshare and namespace creation. No transient
process scan is substituted. Holding the namespace FD intentionally preserves
the namespace object. Namespace disappearance and general descendant cleanup
claims remain false; hostile-host writers, foreign same-credential processes
and inherited input capabilities are still separate boundaries.

The filesystem gate closes a finite pre-start data-tree entry route. Kernel
filesystems, inherited FDs, implicit driver behavior and interval-wide backing
protection are not made complete by this walk. Output equality checks do not
seal its backing or exclude a later external writer. All configured/custody,
installation/runtime/admission/publication authority remains false.

## Downstream dependency order

Complete driver input closure and original input/output protection before
accepted static image acquisition. The first scheduler context may require the
original accepted **image/material owner**; it cannot require its own already
running producer process. Existing order is context, plan/claim, attestation
consumption, sealed executable pair, then spawn/register/target gate. Native
process ownership is created during that attempt. A preliminary producer run
would violate once-only semantics. Reuse the existing stager, resolver,
gateway, recovery and reserved BRS serial after the real acquisition is ready.

Keep the production CLI refusal until then. No WebAgent, model, remote
evaluator, company platform or real solver campaign belongs to this software
regression; original benchmark content is read-only. Fixed-U/account/root/ACL/
cgroup environment acceptance remains separately required.
