# Real-source staging consistency probe — 2026-10-21

This Linux probe exercised the new source-tree/staging consistency validator
against the pinned CPython 3.13.12 archive on `5090gpu`. It is a real-input
implementation regression, not candidate-build provenance or release
acceptance.

The archive was opened from
`/home/qinzhiqing/vchive/lunar-cpython31312-probe.4V1KB0/Python-3.13.12.official-verified.tar.xz`.
The bounded observer confirmed the repository profile pin: 22,926,488 bytes,
SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`.
It replayed the manifest and source-tree pins previously retained in
[`linux-input-observation-20261019.md`](linux-input-observation-20261019.md):

| Evidence | Result |
| --- | --- |
| Extraction manifest SHA-256 | `27c37b470ee41f0efd765e4a5d2d8617ee462481dadd8563d3efa1d6abaf4c95` |
| Original source-tree SHA-256 | `f7e8e480b96c4fe11bf1f0b0e5543377f9e4017c635bf7dca39175819de7e16f` |
| Original regular files / bytes | 4,837 / 108,687,660 |
| Staging entries | 5,245 |
| Fixed patch-set SHA-256 | `f3f740c644165d8c4d2e89840a1e75427806c12c13debf843d3b6fb2cc90f479` |
| Staging manifest SHA-256 | `5dba3f51da5dc3ac7f84932c486912c5ad39f2b1f99456cf1756f50bc2d0631d` |
| Consistency result | `passed` |

The staging output was created once in a new `/tmp/lunar-source-consistency.*`
directory. The result JSON is 945 bytes with SHA-256
`87b961d2702a6b951792b72508a63c9b5aa4c3fc7f0da3e420e04ca57909495b` and was
retained with the temporary remote probe. The record reports
`profile_pin_verified=true`, `metadata_validation=validated`,
`source_preimages_checked=false` on the source-tree observation, and
`signature_verification=not-performed` in the DTO. The comparator retained the
false preimage-observation claim while independently matching the observed
preimage files and fixed patch pre/postimage digests against the staging
manifest.

The staging digest was produced by the staging operation in this same probe
and supplied as its expected staging pin; it is not an independently retained
pre-run staging pin. The prior manifest and source-tree pins were replayed, but
this does not independently establish archive acquisition, signer trust, or
that a candidate build consumed the staged tree. The separate GPG audit records
a cryptographically valid detached signature with `TRUST_UNDEFINED`. No
configure/make/freezer, CPython execution, evaluator, solver, or production
admission occurred; all build/runtime/admission claims remain false. The
temporary `/tmp` archive copy and staging tree are not durable release inputs.
