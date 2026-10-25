# Independent retention of existing candidate source records

Status: existing release/source records and actual fixed postimages are now
retained locally and independently reviewed. This closes the raw-record
retention subtask, not immutable custody or configured-build consumption.

## Retained bytes and comparison

Eighteen pre-existing files were copied from the release audit directory and
`/tmp/lunar-source-observer.pt2FMx5m` on 5090gpu. They include the official
archive, detached signature, public key, saved release/signer metadata and GPG
transcript, complete staging manifest, observation record and historical replay
scripts. The five actual patched files were then copied from that existing
stage. File types, modes, sizes and hashes match the remote before/after
inventories. Each patched file's device, inode, mode, nlink, size, mtime and
ctime also matches the previously pinned staging manifest before and after
transfer. Original destination and identity fields remain untouched.

An independent local script uses only the standard library. It reads every
archive member without extracting or executing source, reconstructs the complete
extraction manifest and original source-tree projection, and compares their
existing pins. It reads fixed patch constants from the repository module's AST
without importing that module, applies the fixed operations in memory, and
compares every actual retained postimage byte with the expected result.

The archive contains 5,245 members: 4,837 regular files and 408 directories,
with 108,687,660 original file bytes. All unchanged files retain their original
size/hash. The five fixed postimages and all unchanged entries reconstruct
108,659,188 staged bytes and the existing staged-tree projection digest. Thus
the retained archive plus five actual postimages contain enough bytes to
reconstruct the candidate's complete content. No local staged filesystem was
transferred or freshly observed.

The saved public-key packet fingerprint, official signer metadata and saved
`GOODSIG`/`VALIDSIG` transcript agree. This review does not repeat cryptographic
OpenPGP or Sigstore verification; the Sigstore file is retained and its archive
digest compared only. The historical GPG trust result remains
`TRUST_UNDEFINED`. The staging manifest's own signature disposition remains
`not-performed`; a historical release audit is not a signature operation by the
staging observer.

## Evidence pins

The local ignored package is
`.lunar-evolution/validation/feature189-20261024/retained-source-provenance-v2-1arwy08x/`.
Its `release/`, `observer/` and `postimages/` directories retain original bytes;
`remote-before.json`, `remote-after.json`, `postimages-before.json` and
`postimages-after.json` retain transfer inventories. The two before/after pairs
match. An initial transfer wrapper compared stat tuples including access time
and refused before transferring files; the corrected wrapper excludes atime
from the content/identity pin. This was a transfer preflight correction, not a
replay of a failed source observation or build.

| Retained record or digest domain | Bytes, where applicable | SHA-256 |
| --- | ---: | --- |
| Official CPython archive | 22,926,488 | `2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593` |
| Original complete staging manifest | 2,032,226 | `9c9b3dabf020c60302fc50dfba4777b3e4a72d8f5c1afc180d7253fb19e735d1` |
| Original saved observation | 840 | `3848ccbbe861eb3d3ad21c7bbdc0c229618e77826fd26b0772da17d4ad89f0aa` |
| Complete extraction manifest | — | `27c37b470ee41f0efd765e4a5d2d8617ee462481dadd8563d3efa1d6abaf4c95` |
| Complete original source tree | — | `f7e8e480b96c4fe11bf1f0b0e5543377f9e4017c635bf7dca39175819de7e16f` |
| Fixed full patch policy | — | `130ee69a2578a450aa35018cddee482675bf8bccb725ed2b46f3d8229fdaada6` |
| Fixed patch file vector | — | `f3c6f45437b954bdb8bd59a3fd05ef98d0b1715066e570cb3c277dda16596b48` |
| Complete staged-tree projection | — | `5ee1f24cf0f3cee55537d2f90ce6e4977d7cd8fa5c8e22f01dd33c378849e11c` |
| Eighteen-file before inventory | — | `3f04e9f2b870a17316bdebbbfaa4bff18b1fafb4b0c865ab997dce202914d6ea` |
| Five-postimage before inventory | — | `b42a25958227d1fc2af4ef88f7afaa91ba75ce6aa46c9e6904bcbd49fa0e4bbb` |
| Independent review script | — | `3db8994aee3323c582631dd7331af27a9f119d3e2170b38c5980f805729f4023` |
| Independent review JSON | 3,712 | `98be8a5440e3ddbb545928ff211ca6903c8e651982a03798978f0d7c494d8882` |

The saved observation is 839 canonical JSON bytes plus one LF. Preserve its
840-byte historical pin. The saved `write_bytes(observed.canonical_json)`
script would not add that LF, whereas the saved print-based replay would.
These files do not establish which runner produced the historical record or
which modules were loaded then; no live provenance is reconstructed afterwards.

## Remaining gates

This review retains and checks complete records and candidate content. It does
not observe the entire remote staged filesystem's current state, establish
immutable source/toolchain custody, or prove a configured consumer used it.
The complete configure/helper/cache/freezer/compiler/link recipe, actual build
and sealed runtime remain open. All build, consumption, protection and
admission claims remain false. No old replay, source observer, signature
command, compiler, solver or evaluator was rerun for this retention slice.
