# F06 provider-free acceptance envelope provenance boundary

The provider-free composition helper emits one canonical summary only after
the installation, build-closure, startup, input/result and handoff DTOs have
passed their individual contracts and cross-pin checks. The summary keeps the
five detached build pins in a `provenance` object:

```json
{
  "status": "detached-pins-only",
  "source_tree_sha256": "…",
  "toolchain_manifest_sha256": "…",
  "frozen_inventory_sha256": "…",
  "link_manifest_sha256": "…",
  "artifact_sha256": "…"
}
```

The status is deliberately explicit. These values are canonical contract pins,
not proof that source archives or toolchains were acquired, that a compiler or
freezer ran, or that artifact bytes were inspected. The summary continues to
set `live_acceptance_ready=false` and `production_admission=false`.

The composition seam also rechecks that a detached build DTO's provenance
attributes agree with the corresponding canonical wire sections, and that the
installation wrapper's descriptor digest and artifact/frozen inventory pins
agree with its nested descriptor. This protects the final envelope from a
caller constructing a DTO whose convenience attributes drift from its wire.
The full F01/F02 parsers remain the authoritative source/toolchain/ELF shape
checks; this repeated comparison performs no I/O, process launch, compiler,
evaluator, or campaign work.

Actual source/toolchain receipts, static ELF inspection, sealed startup, owner
lifecycle, authoritative input/result and production admission remain open
Feature189/193 gates.
