# CPython release input and toolchain audit (2026-10-21)

This is a bounded G1 input audit performed on `5090gpu`. It validates the
official CPython source archive and cross-checks the declared Zig archive plus
available musl package bytes. It does **not** configure or rebuild CPython,
complete the static link closure, or pass sealed-runtime acceptance.

## CPython release archive and signature

The verified source archive is CPython 3.13.12, 22,926,488 bytes, SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`. The same
digest and size appear in the saved python.org release page and in the already
retained archive at `/tmp/lunar-toolchains/sources/Python-3.13.12.tar.xz`.
The disposable audit copy is
`/home/qinzhiqing/vchive/lunar-cpython31312-probe.4V1KB0/Python-3.13.12.official-verified.tar.xz`.

The detached python.org signature is 963 bytes, SHA-256
`1a0f233d4f31ad9cdda8bfd4db856c74654704304816c00e5ca159e28fb1c925`. It was
verified with GnuPG 2.4.8 using a key fetched by full fingerprint
`7169605F62C751356D054A26A821E680E5FA6305`. The saved python.org OpenPGP page
lists Thomas Wouters as a signer for 3.12/3.13 source releases and lists key ID
`A821E680E5FA6305`. GnuPG returned both `GOODSIG A821E680E5FA6305` and
`VALIDSIG 7169605F62C751356D054A26A821E680E5FA6305`; the signature is
cryptographically valid. GnuPG also returned `TRUST_UNDEFINED`: no local
web-of-trust decision was configured. The signer identity is cross-checked
against the saved official Python metadata page rather than the local WoT.
The key endpoint was
`https://keys.openpgp.org/vks/v1/by-fingerprint/7169605F62C751356D054A26A821E680E5FA6305`;
the checked signature command was:

```bash
GNUPGHOME="$PWD/gnupg" gpg --batch --status-fd 1 --verify \
  "$PWD/Python-3.13.12.tar.xz.asc" \
  "$PWD/Python-3.13.12.official-verified.tar.xz"
```

The verification transcript, detached signature, release/OpenPGP metadata,
candidate key, and `SHA256SUMS.audit` are retained in the disposable audit
directory. The manifest check passed for every listed file. The audit summary
has SHA-256 `6fbfe982d87295593539a5bc8e97648ec9fda352d5f3becc36f1f272ab3c172f`;
the manifest has SHA-256
`3d9b50763023cb28f778a4b6841a7365c92f88ef92624d498f86764f24010e66`.
Those raw files remain on the remote disposable host and are not committed in
this repository; this report preserves the key digests and result, but is not a
self-contained evidence bundle for independently re-running the signature check.

One earlier slow range download completed after its caller had moved on and
overwrote a same-name candidate. That 18,100,224-byte file (SHA-256 beginning
`d2f3d38`) was rejected and is not part of the verified inputs. The accepted
archive uses a separate filename and passed both the official checksum and
signature checks.

## Toolchain input cross-check

The existing Zig 0.16.0 Linux x86_64 archive is 55,478,392 bytes, SHA-256
`70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00`, matching
the fixed profile in `tools/static_python_fixture/profile.py`. The selected
target is `x86_64-linux-musl`; the profile describes Zig's bundled musl 1.2.5
with backports and Zig-libc replacements.

The separately extracted Ubuntu musl packages (version `1.2.5-3build1`, amd64)
were downloaded from the configured USTC Ubuntu `resolute/universe` apt source
to the disposable directory and compared byte-for-byte with the existing
package cache. The audit did not establish that these packages participated in
the prior CPython build; the build's compiler profile selects Zig's bundled
musl. No system package was installed:

| Package | Size | SHA-256 |
| --- | ---: | --- |
| `musl` | 425,264 | `ab4117a96375bd25db6be0be00fc1552d1747b7ed2401e96c48171a9e309c5b3` |
| `musl-dev` | 626,486 | `6a254be70caa3515b04e5b1abd048bc158ad6cd58a5c61a907d3deb744104dc1` |
| `musl-tools` | 5,538 | `db41428e8dc59fe0f9f299e5a2f33efa842fe7abf50359e3aedac236b11de49e` |

The extracted libc archive, headers, compiler wrapper, and specs were hashed
and compared with the existing host-local auxiliary prefix in that disposable
audit. Their per-file digests are not reproduced in this repository, so this is
a bounded cross-check rather than a retained, independently pinned input
manifest. It does not complete the actual configured sysroot or linker input
manifest. An older
`/home/qinzhiqing/vchive/toolchains/musl-1.2.5/INSTALL-MANIFEST.md` contains a
61-character typo for the `musl` package digest; the actual 64-character value
is recorded above. The old manifest was not changed.

## What this closes and what remains open

This closes the source archive size/digest/signature check and confirms the
current compiler/libc package bytes against their fixed profile. It does not
produce an independently signed Zig toolchain manifest or complete the
compiler, static-library, configured-object, freezer, generated-header, or
link-input closure. It also does not audit a newly staged full source tree and
patch set as an accepted build input.

The existing static CPython builds remain engineering observations recorded in
[`real-build-probe.md`](real-build-probe.md). One stock build produced a static
ELF, but empty-environment startup failed with
`ModuleNotFoundError: No module named 'encodings'`. This remains a hard G2/G3
failure. No configure/build was repeated during this audit because the
verified source archive and selected toolchain bytes match those of the prior
probe. `production_admission=false` and `online_publication=false` remain in
force.
