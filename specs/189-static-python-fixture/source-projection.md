# Snapshot-bound fixed source preparation

This Feature189 G1/G2 slice connects the existing archive-byte observer to the
existing three-file source transformation. It performs only bounded in-memory
projection and preparation. It does not reopen the archive, extract an
installation tree, write source files, run source code, generate bytecode,
configure, compile, link, start a runtime, or publish an installation.

## Current gap and fixed scope

`archive_observation.py` hashes actual regular-file member bytes and emits a
canonical inventory. `source_patches.prepare_static_python_sources` checks and
transforms a separately supplied mapping of source bytes. Neither API alone
establishes that the transformed bytes are the members of the same observed
archive. The legacy pathname-based `recipe.extract_source` is a separate
containment-only helper; its verification followed by a second pathname open
does not satisfy this snapshot-bound contract and is not called by this slice.

The projection accepts only the CPython profile and these installation-owned
relative paths:

- `Lib/encodings/aliases.py`
- `Lib/importlib/_bootstrap_external.py`
- `Python/import.c`

Their archive paths have the existing `Python-3.13.12/` root. Callers cannot
select a member, provide a replacement source mapping or observation, change a
patch, or request a generic extraction operation. Other archive members remain
subject to the complete archive grammar, collision and budget checks; they are
not returned or represented as prepared source files.

## Public contract

`prepare_archive_sources(snapshot, *, expected_manifest_sha256: str,
require_profile: bool = True, deadline: float, monotonic = time.monotonic)`
returns a frozen, detached result containing the original and prepared bytes
for exactly the three fixed paths and canonical projection metadata.
The result is `StaticPythonArchiveSourcePreparation`; its `sources` is an
immutable tuple of `StaticPythonPreparedArchiveSource` records carrying the
relative path, archive path, and original/prepared bytes with their size/SHA
pins. No live FD or caller-owned source mapping is retained.

Accept only the existing exact `StaticPythonArchiveSnapshot` DTO and exact
primitive argument types. `require_profile` must be an exact boolean.
`expected_manifest_sha256` must be an independently retained lowercase SHA-256
pin in the existing manifest-pin domain, with no missing or placeholder value.
`deadline` is mandatory, an exact finite positive float in the caller's original
absolute monotonic timebase. Reject invalid inputs before archive parsing,
source preparation or output construction.

The caller supplies a retained expected inventory digest. The implementation
reconstructs canonical inventory bytes from the complete snapshot and compares
their actual digest with that pin in both profile and inert modes. It cannot
choose its expected pin from the inventory it has just computed, or accept an
inventory supplied by the caller instead of observing the snapshot.

With `require_profile=True`, use the existing profile-verified archive checks,
source-identity shape and canonical metadata validation. With
`require_profile=False`, only the explicit inert snapshot seam is exercised;
matching a synthetic inventory pin does not upgrade it to a release-profile
observation. Record the skipped profile/metadata status separately from the
source-byte checks performed below. There is no automatic fallback from a
failed profile check to inert processing.

## Byte chain and refusal ordering

1. Revalidate snapshot scalars, immutable compressed bytes, size and digest using
   the existing archive boundary. Consume those bytes only, never a pathname.
2. Decode and inspect the complete archive under the existing bounded XZ/USTAR
   grammar. Retain exact regular-file slices for the three fixed paths while
   preserving all duplicate, ancestor, root, extension and end-marker refusals.
3. Require the complete canonical manifest digest to equal the external pin.
   Each selected path must exist once as a regular file. Its actual slice size
   and SHA must equal the observer's member size and SHA.
4. Check every selected actual preimage against the installation-owned size,
   SHA and path policy in `source_patches.py`. Complete all three preimage and
   aggregate checks before calling the existing source transformation.
5. Call `prepare_static_python_sources` with a fresh exact mapping constructed
   by the projector. Preserve its exact preimage, unique-snippet and postimage
   checks and fixed source-preparation policy. Its signature does not change.
6. Rehash the actual returned prepared bytes, bind their sizes and SHA values to
   that policy, and build the detached canonical projection record. A failure
   produces no partial result and no filesystem effect.

Use the reviewed archive parser and member offsets rather than a second,
more permissive tar reader. No returned or fabricated frozen DTO is an
authentication token. This is a trusted local-process byte-consistency
boundary; actual archive provenance, acquisition and signature acceptance
remain separate gates.

## Bounds and original deadline

Retain the existing compressed, XZ-memory, decompressed-stream, member-count,
member-size and total-file budgets. The selected input vector additionally
uses `source_patches.MAX_SOURCE_BYTES` (256 KiB per source) and
`MAX_TOTAL_SOURCE_BYTES` (512 KiB for the three sources). Validate selected
sizes before retaining their bytes, and retain bounded original/prepared vectors
only; do not return all decompressed member payloads.

Pass the same deadline and clock through decompression, member traversal,
selected-byte copying/hashing and metadata construction. Check before work,
around bounded compressed/output chunks and members, before and after the
existing finite source transformation, and before returning the final result.
No phase starts a new duration or recomputes the deadline. Expiry and invalid
clock results are fixed-code refusals. The finite pure patch function has no
new clock parameter; the wrapper checks the original deadline around its
already bounded work. A result is not returned after the deadline merely
because parsing or preparation started before it.

## Evidence record and claims

The result owns immutable original/prepared bytes and their path, size and SHA
projections. Its canonical metadata binds the snapshot/archive digest, actual
complete inventory digest, fixed source-preparation policy/patch-set digest,
source version/commit, and all three preimage/postimage records. Record the
actual profile/metadata verification status and signature status separately.
The canonical record and its digest are detached from returned mutable views.

Successful source-byte/preimage checks are real facts about these three bytes
vectors. They are not complete source-tree verification or filesystem patch
application. The existing preparation manifest retains its reviewed-Git
provenance and unperformed release/archive/signature status; a separate local
archive-profile check must not rewrite those fields into release acceptance.
Signature verification remains `not-performed`. Source execution, filesystem
extraction, build, frozen-header generation, runtime execution, runtime-load
protection, production admission and general code-origin protection remain
false or explicitly unperformed. No new inherited FD, native protocol, CLI
solver or build-driver execution route is introduced.

## Local acceptance and later gates

Use a synthetic USTAR/XZ fixture containing the repository's three licensed
`tests/fixtures/static_python_source` byte fixtures. Generate and retain its
expected canonical inventory pin independently in the test harness. This is
not a downloaded CPython distribution or a release signature test.

Cover the exact byte-to-member-to-preimage-to-postimage chain; wrong or absent
inventory pin; missing/directory/duplicate selected members; selected source
size/SHA drift; callback-bearing input types; unsupported archive/profile;
archive grammar/trailing-data refusals; aggregate budgets; immutable/detached
results; no pathname reopen or filesystem/subprocess effects; and deadline
expiry before parsing, after decompression, around hashing/preparation and
before return. Preserve the existing 64-case archive-observation gate unchanged.
Run focused tests, Ruff, compileall and diff checks, then require final-source
three-version Linux CI and an independent raw/source/tree audit before merging
this new slice. Keep first failures separate from later successful evidence.

Actual release/toolchain acquisition and signatures, safe staging/extraction,
complete configured build closure, real same-source frozen headers, static
ELF/link/size inspection, runtime observations and native lifecycle acceptance
remain the unchecked G1/G2/G3 gates. Feature191 real Python adapters and
production RSI CLI composition still depend on those later acceptance gates.

Local validation on 2026-10-09: 114 focused cases (64 unchanged archive cases
and 50 new projection cases) pass on Python 3.13.12 and cached Python 3.11.15.
Root composition passes 725 cases with zero failures, errors or skips. Ruff,
compileall and diff checks pass; independent source review has no open finding.
The workflow retains a dedicated 50-case source-projection gate. Final-source
three-version Linux CI and independent raw/source/tree audit remain pending.
