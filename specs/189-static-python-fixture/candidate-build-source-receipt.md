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

## Read-only observation of a staged tree

`tools.static_python_fixture.candidate_build_source_observation` complements
the detached receipt with `observe_staged_candidate_source_tree`. It accepts
the canonical staging manifest and fixed patch policy as pinned bytes, then
opens the manifest's already-staged tree read-only. It verifies the complete
on-disk inventory, file types, identities and bytes against the retained
staging record, including the staging directory's direct children. Before
filesystem access, it binds each patched entry's recorded source digest to the
fixed patch preimage, and its staged digest and size to the patch postimage;
unpatched source and staged digests must match. It then reconstructs the
original source-tree digest from the recorded preimages and requires that
result to match an independent expected source-tree pin. Directory scans are
bounded by the pinned inventory and share the original deadline; opened path
descriptors are closed on every refusal path. The walk is sequential rather
than an atomic filesystem snapshot, so a later build consumer still needs to
revalidate the exact bytes it consumes. It does
not stage or modify files, apply patches, invoke a build, or grant runtime or
production authority. The returned detached record uses status
`staged-source-observed` and binds the staging manifest, staged tree, original
source tree and fixed patch set; all build, runtime and admission claims remain
false.

### CPython 3.13.12 staged-tree observation (2026-10-22)

The observer was exercised on a newly staged copy of the retained CPython
3.13.12 archive on `5090gpu` (`worker01`). The archive was
`/home/qinzhiqing/vchive/lunar-cpython31312-probe.4V1KB0/Python-3.13.12.official-verified.tar.xz`
(22,926,488 bytes, SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`). Profile
pin and source metadata validation passed; the replay used the original source
tree pin and fixed patch policy. This archive copy was retained from the
preceding input audit; it was not fetched or independently signed as part of
this observation, and its staging DTO reports
`signature_verification=not-performed`.

The run staged the tree at
`/tmp/lunar-source-observer.pt2FMx5m/stage/Python-3.13.12`, retained the full
canonical staging DTO at
`/tmp/lunar-source-observer.pt2FMx5m/staging-manifest.json` (2,032,226 bytes,
SHA-256 `9c9b3dabf020c60302fc50dfba4777b3e4a72d8f5c1afc180d7253fb19e735d1`),
and retained the observation record at
`/tmp/lunar-source-observer.pt2FMx5m/source-observation.json` (840 bytes,
SHA-256 `3848ccbbe861eb3d3ad21c7bbdc0c229618e77826fd26b0772da17d4ad89f0aa`).
It observed 4,837 files, 408 directories, 108,659,188 staged bytes and
108,687,660 source bytes. The record binds original source tree
`f7e8e480b96c4fe11bf1f0b0e5543377f9e4017c635bf7dca39175819de7e16f`, staged
tree projection `5ee1f24cf0f3cee55537d2f90ce6e4977d7cd8fa5c8e22f01dd33c378849e11c`,
and patch set
`f3c6f45437b954bdb8bd59a3fd05ef98d0b1715066e570cb3c277dda16596b48`.
All source execution, build, candidate-consumption, generated-header, runtime,
protection and production-admission claims are false. The manifest and records
are retained only on the remote disposable host and are not independently
custodied here. Replaying them proves that the observer accepts this staged
tree under the stated pins; it does not elevate archive custody, signer trust,
or the build/runtime gates.

This filesystem observation is stronger than consistency checks between
caller-supplied DTOs, but it is still local evidence. Fixture tests establish
observer behavior only; the real-source replay above separately exercises the
observer against CPython source bytes. That replay used an original source-tree
pin and fixed patch policy, but the archive was a previously retained copy,
signature verification was not repeated, the staging manifest digest was
generated by the same staging run rather than independently pinned beforehand,
and all full records remain on a remote disposable host. The observer exercise
is complete, while independent archive/signature custody and configured-build
consumption remain open. A separate configured build is still required. The
recorded `staged_tree_sha256` is the staging manifest's tree-projection digest
after the observer matched on-disk inventory, metadata and file bytes; it is
not an independently streamed filesystem Merkle digest.

The remaining candidate-build source/patch custody and later consumption
boundary are specified separately in
[`candidate-build-provenance.md`](candidate-build-provenance.md). That document
is design only; this observer exercise and the `source-only` receipt do not
complete its independent-retention or configured-build obligations.

### Later independent retention (2026-10-24)

The historical raw archive, release/signature metadata, complete staging
manifest, observation, scripts and five actual patched postimages are now
retained locally and independently checked. The archive's complete source
inventory and reconstructed fixed postimages match the existing source and
staged-projection pins. See
[`candidate-source-retention-20261024.md`](candidate-source-retention-20261024.md)
for exact evidence and limitations. The earlier remote-only statements describe
the original exercise; this later retention closes that raw-record custody gap.
It does not prove historical runner live provenance, the complete remote stage's
current state, immutable custody or configured-build consumption. In particular,
the saved 840-byte observation includes a final LF; its historical bytes and
pin are preserved rather than normalized into a different artifact.
