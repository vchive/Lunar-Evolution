# Closed Python filesystem layout

Feature177 adds a read-only, bounded check of the complete filesystem layout inside the explicit
roots of a Feature171 Python runtime manifest. Every regular file must already be declared and
every declared file must be present. It records exact directory membership, including empty
directories, and refuses symbolic links, hardlinks, special objects and inode aliases.

Feature171 remains a declared-file inventory: an unlisted file does not change its acceptance.
The separate closed-tree API refuses an unlisted module, bytecode, customization hook, native
library or resource anywhere inside a selected root, even if it is outside an import root.

```python
from lunar_evolution import (
    build_python_runtime_tree_manifest,
    parse_python_runtime_tree_manifest,
    verify_python_runtime_tree_manifest,
)

# These are independently retained admission inputs from the original v1 inventory.
# declared_manifest is a PythonRuntimeManifest; target is a PythonRuntimeTarget.
closed = build_python_runtime_tree_manifest(
    declared_manifest=declared_manifest,
    expected_manifest_sha256=original_declared_digest,
    expected_target=target,
)
# Retain this digest independently when explicitly admitting the closed layout.
original_tree_digest = closed.tree_sha256
retained = parse_python_runtime_tree_manifest(closed.to_json())
observation = verify_python_runtime_tree_manifest(
    retained,
    expected_tree_sha256=original_tree_digest,
    expected_manifest_sha256=original_declared_digest,
    expected_target=target,
)
assert observation.entry_count == observation.file_count + observation.directory_count
assert observation.to_dict()["scope"] == "closed-filesystem-layout"
assert observation.to_dict()["runtime_load_protection"] is False
```

Store the original declared digest, tree digest and target in the caller's trusted admission
state, separate from received manifest bytes. Parsing checks a self digest and graph shape;
it does not read the filesystem or grant authority. Rebuilding after drift and trusting the new
digest silently would abandon the original admission. Pins include host inode and stat metadata,
so a copied tree with identical content also requires a new explicit admission.

Build and verification hold no-follow root directory chains, stream only declared file bytes and
record all directory members. Two complete snapshots include closing membership and metadata
checks; the original declared-file pin is verified before and after them. A final metadata-only
tree pass checks membership again after the last declared-file reads. Owned descriptors close on
refusals and interrupts. No subprocess, target import, package installer, filesystem mutation,
permission repair or read grant occurs.

The layout has finite limits: 8192 files and directories in total, including each root; 64 relative
path components below each root; 256 MiB per file; 1 GiB aggregate file bytes; and 8 MiB canonical
manifest JSON. Retained v1 directory pins are additionally limited to 8320 per root and 10240 in
aggregate, accommodating outside ancestors of the 16 explicit roots without scanning those
ancestors' contents. Exact tuple/count/nested-field validation runs before serialization or v1
validation, so caller-forced DTO mutation cannot invoke custom collection callbacks.
Paths and labels have cheap character caps before parsing or hashing; the existing 4096-byte
UTF-8 path limit remains enforced. Raw embedded v1 fields and external expected targets use
the same guards. The sum of all directory child names is limited to 8192 before member validation,
preventing repeated directory objects from multiplying that work. String JSON inputs are bounded
before encoding and then checked against the final UTF-8 byte limit.
The wire protocol is `lunar-python-runtime-closed-tree-v1` and embeds the unchanged
original manifest. The API raises `PythonRuntimeTreeError` with a fixed `python_runtime_tree_*`
code on refusal; it never incorporates caller paths into that error message.

All observations and manifests explicitly set these capabilities to false:

- `execution_performed`: no interpreter or producer was launched.
- `runtime_load_protection`: files can still change after this preflight; no immutable runtime
  or atomic snapshot under arbitrary concurrent writers is established.
- `archive_contents_complete`: archive bytes are pinned, but archive member names and import
  behavior are not inspected.
- `loader_dependencies_complete`: transitive native loader dependencies are not discovered.

CPython identity, ABI compatibility, dynamic imports, sealed runtime delivery and launch/isolation
binding remain subsequent work. A successful closed layout check does not establish acceptance of
a real OpenEvolve or ShinkaEvolve campaign. Tests use inert bytes for every runtime role.
