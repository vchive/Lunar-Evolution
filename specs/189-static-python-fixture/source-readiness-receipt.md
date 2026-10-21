# Source-only readiness receipt

Feature189 now has a detached `lunar-static-python-source-readiness-receipt-v1`
wire produced by `tools.static_python_fixture.source_readiness`. It joins the
independently pinned CPython archive receipt, complete original source-tree
observation, patched staging manifest, the five-file patch/policy digests, and
the six emitted RSI source assets. The expanded `assets/frozen_main.py` bytes
are checked against the source plan record rather than inferred from a path.

The receipt also carries an exact Zig archive-rooted file inventory. The
inventory has an independent canonical SHA-256 and must say
`evidence_status="unverified"`; all archive/file/signature/build/admission
claims in that inventory remain false. This is intentional while the complete
Zig/sysroot/libc bytes and their independent audit are not retained in this
repository. A caller cannot omit the inventory, replace it with a profile-only
declaration, or replace its pin with a digest computed after the check.

`build_source_readiness_receipt` first runs the existing archive-to-source and
source-tree-to-staging consistency gates. It then validates the canonical RSI
source plan and all six asset bytes, including the expanded frozen main. The
result is immutable detached JSON and has no filesystem, subprocess, network,
source execution, configure, compiler, freezer, linker or runtime route.

This receipt proves only agreement of supplied source metadata. It does not
prove source acquisition or release-signature trust, complete toolchain or
sysroot provenance, configured/static link closure, generated frozen headers,
ELF properties, startup, producer lifecycle, evaluator results, installation
acceptance, or production readiness. The receipt's `status` is always
`source-only` and every execution/admission claim is required to be false.
