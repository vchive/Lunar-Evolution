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
   The sole optional runtime link is `/etc/mtab` to exactly `/proc/mounts`, and
   only when the original checked OCI selection includes `/proc` of type proc.
   Its original no-follow O_PATH FD, inode, single-link count, exact size/target
   and repeated name identity must agree. Every other link remains refused.
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

The Python build used for actual acquisition must export callable
`os.pidfd_open`; a matching Python minor release or software-fixture pass does
not establish that capability. The concentrated3.11.15 environment lacks that
export. Its separately attempted six-command observation failed at original
service acquisition before any target start or new gate. The original
2.642591-second failure, source equality and stopped original container are
retained; the software regression is unchanged. A separately reviewed fresh
plan selects the independently observed3.12.3 interpreter that exports the API,
with fresh output/scratch paths and no automatic fallback or retry.

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

## Frozen concentrated regression

Implementation566778de5891205950cfe6d6c3b646b25875759f, tree
61c527d1694b4bb07560ae39d0900dd9524e8835, passed all2,216cases in51complete
affected files on5090gpu Python3.11.15. All159new cases passed: original boundary
integration27, filesystem51, namespace-init50 and output-FD31. The original
child was reaped with zero exit in84.63074161065742seconds /600seconds,
zero failures/errors/skips/retries. No product compiler, solver or image ran;
existing tests may construct and execute their inert native helper fixtures.

All2,795frozen source records match Git blobs, stored execution bits and archive
contents; original source-before/source-after reports are unchanged. Independent
review compared exact per-file counts and all new raw keys. One existing raw
parameter differs by platform: frozen source uses errno.EDQUOT, which is69 on
the collection's Darwin and122 on the original Linux interpreter. The other
2,215raw keys match exactly. Neither original collection nor JUnit was changed,
and no pytest run was repeated. Ruff, compileall and diff checks passed.

Original evidence is under primary ignored
`validation/worker-boundaries-20261031/`. Independent review SHA256:
3445898233a78393a2bdd2f862d412b96421a4ff3a2f100a4c221b11ff93aecf.
Original batch-result SHA256:
3d7a5d4dc21e42d28fe2038c7841dee02f82735ff2ec9b284f4b4e3d85bdc15f.
JUnit SHA256:
15b11e09273f767f131a53cccf1c69bda5880bba17d35f279e82bfef197e78fe.

The first dependent extraction was mistakenly requested while SCP was still
running; the archive hash refused before extraction, and the harness file was
absent at that initial Python invocation. No pytest import, collection or run
occurred there. The original SCP then completed successfully, the complete
archive hash was verified, and the single batch above executed. The original
transport pre-execution record is retained separately.

The later result-documentation changes do not modify product or test bytes.
Fresh finite Podman compatibility and this successor's final CI/source/main
integration remain pending and must retain their own actual outcomes.

The distinct3.12.3 six-command observation failed in3.531581seconds before
target start, after the original initialized lifetime phase. The report retains
ValueError and confirmed original container exit137. A separately recorded
post-exit host-image observation found the runtime's `/etc/mtab` link, which the
initial fixed vocabulary does not admit. This observation is not a read of the
earlier live worker. It motivates the narrow fixed-link successor above; it
does not rewrite the original failure, prove its lost inner error text or
establish compatibility. The successor needs its own affected regression and
separately reviewed fresh observation.

## Narrow compatibility continuations

Frozen3c34d9ae/tree436c13b1 passed222cases in four complete affected files on
Linux3.12.3 in6.177187seconds, zero failure/error/skip/retry, original child
reaped. This includes31new mtab cases;82 is the whole filesystem file count,
not82new cases. All2,795source files matched before/after, archive, Git blob
and execution bits. Independent original review2695afd0… passed. The previous
2,216-case batch remains its separate frozen result.

The distinct fresh V3 actual Podman attempt still failed before target start in
3.588861seconds with generic ValueError, no completed stages and original
container exit137. Original source-before/source-after are identical. Its
retained host image after exit contains three fixed empty0755directories:
`/tmp/home`, `/tmp/zig-global`, `/tmp/zig-local`. The original `_image_archive`
producer explicitly emits the same directories. A tmpfs may preserve these
source-owned empty directories; requiring an entirely empty tmp vocabulary is
a static compatibility mismatch. Neither the after-exit observation nor this
static comparison uniquely identifies the earlier live-worker failure.

The narrow successor admits only those three optional empty directories through
the existing complete no-follow FD walk; `/tmp` remains0700. Nonempty, extra,
linked, replaced or wrongly permissioned entries still refuse. A private
ValueError subclass carries the constant `podman_worker_filesystem` code through
the existing original failure field, without wrapping OS/control errors or
changing the successful wire. This successor needs its own253-case affected
supplement and a separately reviewed new original six-command observation.
All prior actual failures and all-false acceptance claims remain unchanged.
