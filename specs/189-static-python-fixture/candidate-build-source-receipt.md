# Candidate-build source receipt (G1 continuation)

`tools.static_python_fixture.candidate_build_source` emits
`lunar-static-python-candidate-build-source-v1`. The receipt is detached
source provenance for a future configured build. It binds three independently
pinned canonical records:

- the complete staged-source manifest and a `staged_tree_sha256` computed from
  sorted path/kind/implicit/source/staged/archive-mode/size identities;
- the exact fixed patch policy, including every file preimage/postimage and
  operation digest, with `patch_set_sha256` equal to the canonical `files`
  vector digest; and
- a source profile containing the archive, source-tree, version/commit and
  patch-set digests.

The builder API receives all records as bytes plus external expected digests.
It verifies canonical UTF-8 JSON, exact fields, bounded vectors, duplicate-free
paths, digest/size types, cross-record archive/version/commit/patch bindings,
and all source-only claims before emitting the receipt. A caller cannot derive
an expected pin from the supplied record itself.

The receipt is evidence only. `status` is always `source-only`; source
execution, build, generated frozen headers, runtime execution, runtime load
protection, code-origin protection and production admission are all false.
The module performs no path access, extraction, patch application, subprocess,
compiler, freezer, linker or runtime operation. Matching detached records do
not establish that a real builder consumed the staged directory. G1 still
requires independently retained acquired source/toolchain evidence and a real
configured build before G2/G3 claims can advance.
