# Python runtime inventory

Feature171 provides a local, read-only inventory of explicitly declared Python runtime files.
Use it before designing a native Python launch. It checks the same bytes and host file identities
against the caller's original pins; it does not execute Python or grant filesystem access.

```python
from pathlib import Path
from lunar_evolution import (
    PythonRuntimeFileDeclaration as File,
    PythonRuntimeImportRoot,
    PythonRuntimeTarget,
    build_python_runtime_manifest,
    parse_python_runtime_manifest,
    verify_python_runtime_manifest,
)

# An explicit, prepared tree with regular files; no symlinked venv discovery.
root = Path("/absolute/prepared-runtime")
target = PythonRuntimeTarget("linux", "x86_64", "3.12", "cp312")
entrypoint = File("runtime", "project/main.py", "project_source")
manifest = build_python_runtime_manifest(
    root_paths={"runtime": root},
    target=target,
    file_declarations=[
        File("runtime", "bin/python", "interpreter"),
        File("runtime", "lib/stdlib.zip", "stdlib_archive"),
        File("runtime", "requirements.lock", "dependency_lock"),
        entrypoint,
    ],
    import_roots=[PythonRuntimeImportRoot("runtime", "project")],
    entrypoint=entrypoint,
)
original_digest = manifest.manifest_sha256
retained = parse_python_runtime_manifest(manifest.to_json())
observation = verify_python_runtime_manifest(
    retained, expected_manifest_sha256=original_digest, expected_target=target,
)
assert observation.to_dict()["runtime_load_protection"] is False
```

Keep the original digest and target in the caller's trusted admission state. Recomputing a new
manifest after drift and accepting its new digest would discard the original pin. Digests include
inode/stat metadata and are host-bound, so copying an identical file or moving it under a replaced
parent still requires a new explicit admission.

The inventory separates interpreter/loader/stdlib runtime material, extension/site-package
dependencies, project source, resources and lock/venv metadata. A venv-tree declaration requires
one `pyvenv.cfg`; symlinked interpreters are refused. All file and directory reads use no-follow
identities, and each complete snapshot has closing identity checks. No directory content scan,
target import, pip/ldd call, subprocess, write or chmod occurs.

Target version/ABI and the fixed `-I -S -B` environment policy are declarations. The API cannot
prove that an arbitrary file is CPython, that all potential imports were listed, or that a future
launcher applies this policy. Unlisted files under import roots remain unverified; adding one
does not fail this declared inventory. Listed `.pth` and customization hooks are refused, but
unlisted hooks are not discovered. Observed files can still be writable.

The next step is complete import inventory in an immutable runtime layout, versioned launch and
isolation binding, then a local Python fixture using the inherited broker pipe. Feature170's
trusted C producer does not establish real OpenEvolve/Shinka Python campaign acceptance.
