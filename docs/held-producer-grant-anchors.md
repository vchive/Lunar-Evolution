# Held producer grant anchors

This standalone host API keeps the original approved filesystem objects open while
checking their no-follow pathname bindings. It prepares for native FD-based grants;
the current formal bootstrap still uses its existing policy/control v1 path interface.

```python
from lunar_evolution import ProducerGrantIdentity, ProducerGrantRequest, hold_producer_grants

# These values must come from the already-validated original input manifest.
original = ProducerGrantIdentity(device=original_device, inode=original_inode, kind="file")
requests = (
    ProducerGrantRequest(input_path, "protected-file", original),
    ProducerGrantRequest(work_path, "writable-directory"),
    ProducerGrantRequest(work_path, "cwd"),
    ProducerGrantRequest(output_path, "writable-directory"),
)
with hold_producer_grants(requests) as plan:
    plan.validate(reserved_fds=private_protocol_fds)
    live_anchors = plan.anchors
    observation = plan.manifest.to_dict()
```

Paths must be canonical absolute strings without symlinks, traversal or normalization.
If work and output are the same path, issue only one writable request; different roles
on that path merge to a single leaf anchor. Directory identities omitted by the caller
are captured for the first time at context entry. This cannot prove they were the objects
approved by an earlier `_safe_dir` call. The formal integration must enter the owner at
the original work/output acquisition and retain it through native rule installation.

Replacing a leaf, ancestor or cwd path fails revalidation rather than refreshing the pins.
Protected files require nlink=1. Read-only directory subtrees cannot intersect write grants,
and different-path same-object aliases are rejected. Content and mode changes alone are
outside this identity contract; existing input byte/mode validators remain necessary.

Leaf FD numbers are borrowed and valid only inside the context. Do not close or replace
them. Ancestor pins remain host-private. Context exit revalidates and attempts cleanup of
still-identifiable owned descriptors; failure preserves the original exception and
continues cleanup of other partial opens. OS failures refuse clean success.
A reused FD naming a different device/inode/type is refused and is not closed by this
owner. These checks cannot detect a same-object reopen or prove FD generations. This
is a trusted host ownership API, not a boundary against hostile same-process FD manipulation.

The manifest has scope `host-held-grant-anchors`, `execution_enforced=false`, and no FD
numbers. Its digest is an observation identity, not an execution receipt or launch/recovery
authority. No parser reconstructs a live plan from it. This feature does not install Landlock,
exec a producer, seal runtime contents, bind mount aliases, enforce egress or independently
stop targets when the bootstrap dies or pauses. Those remain separate native work.
