# Sealed Python runtime material

Feature188 turns an independently pinned Feature177 closed filesystem inventory
into one anonymous Linux data memfd. The canonical frame contains a bounded JSON
table followed by the files' exact bytes. All four Linux write/grow/shrink/seal
seals must be present before the API yields. Empty directories and empty files
retain their exact logical membership. Original declared/tree/target pins remain
external inputs; a newly observed filesystem inventory cannot replace them.

```python
from lunar_evolution import (
    materialize_sealed_python_runtime_material,
    verify_sealed_python_runtime_material,
)

with materialize_sealed_python_runtime_material(
    original_tree,
    expected_tree_sha256=original_tree_pin,
    expected_manifest_sha256=original_declared_pin,
    expected_target=original_target,
    material_version="runtime-1",
    deadline=original_absolute_monotonic_deadline,
) as material:
    # Retain the independently verified material digest at this boundary.
    admitted_frame_pin = material.descriptor.frame_sha256
    observation = verify_sealed_python_runtime_material(
        material,
        expected_frame_sha256=admitted_frame_pin,
        expected_tree_sha256=original_tree_pin,
        expected_manifest_sha256=original_declared_pin,
        expected_target=original_target,
        expected_material_version="runtime-1",
    )
    detached_bytes = observation.to_json()
```

`material.fd` is a borrowed CLOEXEC duplicate. The creating context privately
holds the original anchor, canonical table and descriptor bytes, pins, object
identity and deadline. Do not close, replace or rebind either owned descriptor
concurrently from controller threads. A sequential public-FD replacement refuses
verification and cleanup leaves the known foreign replacement open. Cleanup
still releases its original anchor. Cleanup uncertainty raises a fixed
`python_runtime_material_cleanup_unknown` code, or adds that fixed diagnostic to
an already active exception while preserving the primary error or interrupt.

The verifier uses `pread`, so borrower offset changes do not change its result.
After sealing, deleting or replacing source files does not change the retained
material bytes. Separate source-tree verification can still report source drift.
One original absolute deadline applies throughout copying and live verification;
expired contexts still attempt owned-FD cleanup. Checks around synchronous
syscalls are cooperative and cannot preempt a blocked kernel call.

`parse_python_runtime_material_descriptor` accepts only bounded canonical bytes
or text and returns detached evidence. JSON and manually constructed handles
cannot acquire live ownership. Descriptor fields are rederived from independently
read frame/file bytes during live verification. The five fields
`execution_performed`, `runtime_load_protection`, `production_admission`,
`archive_contents_complete` and `loader_dependencies_complete` remain false.

This API does not launch CPython, interpret archives, enforce imports, extend
native control v2 inherited FDs or admit Python workers. The target is the original
declaration, including opaque cross-target inventories. Pinned static CPython,
runtime load closure and a versioned production handoff require separate native
acceptance. An inert C reader test only demonstrates deliberate fixture delivery
of one sealed data FD. No live FD or cleanup authority survives context exit.
