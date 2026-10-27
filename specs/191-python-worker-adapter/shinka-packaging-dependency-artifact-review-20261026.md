# Shinka packaging dependency candidate artifact review

Follow-up (2026-10-27): the previously unselected `flit_core>=3.3` build edge
now has a separately observed [3.12.0 candidate](shinka-flit-core-build-dependency-artifact-review-20261027.md).
The original packaging observation below retains its own scope and outcome;
this follow-up does not establish a consistent lock, build or runtime.

Status: candidate bytes and declarations independently reviewed on 2026-10-26. This closes only a candidate-artifact observation under
step 1 of [the existing runtime profile](project-runtime-profile.md), after the
[Hydra candidates](shinka-hydra-dependency-artifact-review-20261026.md) and
[PyYAML candidate](shinka-pyyaml-dependency-artifact-review-20261026.md).
It is not a resolver result, global lock, complete build/native closure,
accepted executable profile or runtime. `production_admission=false` and
`online_publication=false`.

## Explicit selection and original bytes

The reviewed Hydra 1.3.2 wheel declares the unversioned requirement `packaging`.
**25.0** is a new explicitly selected candidate, recorded before requesting
`https://pypi.org/pypi/packaging/25.0/json`. It satisfies that individual name
edge; no complete Shinka compatibility or latest-version claim is made.
The candidate baseline remains CPython 3.13.12, x86_64-linux-musl and Zig 0.16.0.
The macOS observer interpreter is not that target.

The exact JSON lists two non-yanked distribution files; both were selected
before artifact acquisition. Each was requested once from its original
`files.pythonhosted.org` URL, with zero retries. Actual size/SHA256 match JSON:

| Artifact | Bytes | Members | SHA256 |
| --- | ---: | ---: | --- |
| `packaging-25.0-py3-none-any.whl` | 66469 | 23 | `29572ef2b1f17581046b3a2227d5c611fb25ec70ca1ba8554b24b0e69331a484` |
| `packaging-25.0.tar.gz` | 165727 | 79 | `d443872c98d677bf60f6a1f2f8c1cb748e8fe762d2bf9d3148b5599295b0fc4f` |

The metadata request was capped at 2 MiB, artifacts at 16 MiB each, each request
at a 30-second socket and absolute alarm deadline, archive expansion at 64 MiB,
member count at 10000, and retained source text at 2 MiB per member. The artifact
helper ran once under a 75-second outer bound, raw rc0. The metadata helper also
returned rc0. No package member was extracted to a package filesystem tree.
Original raw streams, request claims, response headers and size/hash receipts
remain separate from later local inspection. All 23 wheel and 79 sdist members
are regular files; original ZIP attributes/tar modes and content hashes are
retained. The wheel's complete 23-row RECORD covers every file exactly once,
with matching SHA256/size and empty self hash/size. A later local byte reader
matched every member against the first inventory. The wheel's 17 package files
(including 16 parsed Python source files) match the sdist's `src/packaging/`
bytes exactly. AST parsing did not execute those files.

## Metadata, licenses and build edge

The JSON, wheel METADATA and sdist PKG-INFO declare `Requires-Python: >=3.8` and
no Requires-Dist entries. The original pyproject explicitly declares
`dependencies = []`. The actual WHEEL tag is `py3-none-any`,
`Root-Is-Purelib: true`; `Generator: flit 3.12.0` is publisher metadata, not an
accepted build-tool identity. No native-extension suffix member occurs in the
wheel. None of these observations accepts the target's finite loader or proves
that every package code path is free of native, subprocess or resource needs.

The source build declaration is:

```toml
[build-system]
requires = ["flit_core >=3.3"]
build-backend = "flit_core.buildapi"
```

`flit_core>=3.3` remains an unselected build dependency, and was not followed,
downloaded or run. Dynamic project version metadata is backed by the retained
`src/packaging/__init__.py` source declaring `__version__ = "25.0"`; this is a
source observation, not backend execution or a reproducible-build result.

Both artifacts contain identical standalone license bytes:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| `LICENSE` | 197 | `cad1ef5bd340d73e074ba614d26f7deaca5c7940c3d8c34852e65c4909686c48` |
| `LICENSE.APACHE` | 10174 | `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594` |
| `LICENSE.BSD` | 1344 | `b70e7e9b742f1cc6f948b34c16aa39ffece94196364bc88ff0d2180f0028fac5` |

The first text offers either license; the source declares
`BSD-2-Clause or Apache-2.0`. METADATA/PKG-INFO contain classifiers and the three
License-File headers, but no License or License-Expression header. Do not invent
an original metadata field from the source declaration.

## Finite runtime boundary

Static source inspection retains concrete routes requiring a later reviewed
profile: `_manylinux.py:127` calls `ctypes.CDLL(None)` in a fallback path;
`_musllinux.py:39-53` reads the selected executable's ELF interpreter and can
invoke its loader through `subprocess.run([ld], ...)`; `tags.py:414` has a
platform-specific subprocess route. None ran. Metadata's absent Requires-Dist
therefore closes only published distribution declarations, not native/stdlib or
process reachability. A finite Hydra entrypoint may select a smaller reachable
subset, but that requires explicit reviewed source/configuration and loader
facts; this artifact review does not remove modules or dependencies.

The existing unresolved ANTLR license material, PyYAML/LibYAML/build inputs,
HTTPX transitive requirements, the other 24 floating Shinka direct requirements,
complete source/resources/toolchain/static-image closure, immutable custody,
entrypoint/lifecycle and production CLI acceptance remain open. This candidate
observation does not block PR189's inert regression gate by itself or imply
that the complete P1 track has passed.

## Retained evidence

Create-only primary-workspace evidence:
`.lunar-evolution/validation/feature191-20261025/shinka-packaging-candidate-6noajk9s/`.
Artifacts and first static inventories are in `artifact-static-freeze-_cxomn8d/`.
The JSON is 5501 bytes, SHA256
`6ab300d7b0735a50109912decebb1731ed292f1ed88a3ce5e4bb7876b182cac0`.
The later local reader report is `local-archive-declaration-review.json`, SHA256
`e35b442b1ea33ab1b324df4476c91a7c61f3e393b249f03e9f84cb5b6cefa103`.
PyPI and its artifact host are one distribution authority; matching their
hashes is not independent publisher authentication.

No pip/resolver, third-party package import, backend, native code, project,
model, evaluator, SSH or .env read occurred. The acquisition and local readers did not modify product source or the frozen
acceptance archive.


## Evidence index reconciliation and independent review

The artifact helper wrote its original 16-record index before printing its
281-byte terminal summary. That index therefore retains a stale empty stdout
pin; the other 15 records match. The first independent review returned rc1
on this index mismatch and remains preserved at
`release-closeout-20261025/packaging-independent-fsy8t9g7/review.json`.
No artifact was refetched and no helper, package or product was rerun.

The original 32-record complete index matches actual final bytes. The later
create-only `evidence-index-reconciliation.json` records the generation order;
`terminal-evidence-index.json` covers all 34 original/reconciliation files,
excluding itself, SHA256
`5a71fcd44fb9d8e8c1bba93eec1c2bcb1ff7f3375853df8eb58622e05f5f0829`.
Neither original index nor stdout was replaced.

The second independent local reader verifies that terminal index before and
after, all members and modes, official sizes/hashes, RECORD, metadata, licenses,
all 17 package source/resource files against the sdist, the unselected build
edge and retained dynamic probe paths: 21 checks pass. Its report is
`release-closeout-20261025/packaging-independent-fx8yhxpk/review.json`, SHA256
`111defbebd5792bd0861bbe865baf974bd404af4332d1756a06b3553c28c9ab8`.
This supersedes no original failed process and accepts no build or runtime.
