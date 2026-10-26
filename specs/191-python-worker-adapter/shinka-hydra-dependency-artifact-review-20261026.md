# Shinka Hydra dependency candidate artifact review

Status: retained artifact and declaration facts independently reviewed on 2026-10-26.
The two selected releases pass byte/member identity checks; ANTLR license material
remains unresolved. This extends the [prior two-package review](shinka-equality-dependency-artifact-review-20261025.md)
under step 1 of [the existing runtime profile](project-runtime-profile.md).
This covers **two candidate dependency identities**. It is not a resolver result,
complete dependency closure, compatibility finding, accepted image or runtime.
`production_admission=false`, `online_publication=false`.

The candidate baseline remains CPython **3.13.12**, **x86_64-linux-musl**, Zig
**0.16.0**. The observer interpreter and published wheel tags do not replace it.

## Selection and original declarations

The reviewed Hydra 1.3.2 wheel declares:

```text
omegaconf (<2.4,>=2.2)
antlr4-python3-runtime (==4.9.*)
packaging
importlib-resources ; python_version < "3.9"
```

OmegaConf 2.3.0 is within Hydra's `>=2.2,<2.4` interval. ANTLR runtime
4.9.3 matches Hydra's `==4.9.*` and OmegaConf's same minor-series constraint.
These exact candidate versions were recorded before fetching their JSON;
no general solver or latest-version selection was used.
Shinka's reviewed project declaration remains Python `>=3.10` and
`hydra-core==1.3.2`.

## Retained official artifacts

Each exact PyPI JSON was fetched once under 2 MiB. Every artifact below was
fetched once from its declared official `files.pythonhosted.org` URL under
16 MiB, with a 30-second request deadline and zero retries. Actual sizes and
SHA256 match the original JSON. HTTP observations and create-only claims remain
in the evidence directory. Archive expansion was bounded at 64 MiB; no archive
member was written as a package file or executed.

| Artifact | Bytes | Members | SHA256 |
| --- | ---: | ---: | --- |
| `omegaconf-2.3.0-py3-none-any.whl` | 79500 | 31 | `7b4df175cdb08ba400f45cae3bdcae7ba8365db4d165fc65fd04b050ab63b46b` |
| `omegaconf-2.3.0.tar.gz` | 3298120 | 115 | `d5d4b6d29955cc50ad50c46dc269bcd92c6e00f5f90d23ab5fee7bfca4ba4cc7` |
| `antlr4-python3-runtime-4.9.3.tar.gz` | 117034 | 78 | `f224469b4168294902bb1efa80a8bf7855f24c99aef99cbefc1bcd3cce77881b` |

The OmegaConf wheel declares `py3-none-any`; its actual WHEEL tag matches the
filename, and its complete RECORD inventory, SHA256 and sizes match all files.
Both OmegaConf artifacts retain their standalone license bytes.
All archive members retain their original mode and content hash in static JSON.

## Actual dependency and build declarations

OmegaConf wheel `Requires-Python` is `>=3.6`. Its exact `Requires-Dist` fields are:

```text
antlr4-python3-runtime (==4.9.*)
PyYAML (>=5.1.0)
dataclasses ; python_version == "3.6"
```

Its sdist PKG-INFO omits Requires-Dist. The independently retained
`requirements/base.txt` and egg-info `requires.txt` declare the same edges.
`setup.py` reads that requirements file, imports `pkg_resources`/`setuptools`
and local build helpers, and installs custom ANTLR/build commands. Its
`pyproject.toml` has no `[build-system]` declaration. The referenced requirements,
build-helper Python sources, README and version source are retained as original
bytes in `omegaconf-2.3.0.local-build-control-supplement.json`.

The sdist includes `build_helpers/bin/antlr-4.9.3-complete.jar`: 3,508,089 bytes,
mode `0o664`, SHA256
`afcd40946d3de4d81e28d7c88d467289e0587285d27adb172aecc5494a17df36`.
The JAR is retained inside the original archive. Java/toolchain execution,
generated-code reproduction and build compatibility remain unknown.

ANTLR's exact JSON has Requires-Python `""` and Requires-Dist `null`; its
PKG-INFO omits both fields. Its retained `setup.py` nevertheless declares
`typing ; python_version<'3.5'` in `install_requires`, uses setuptools and
installs `bin/pygrun`. Missing JSON/PKG-INFO fields therefore do not prove no
dependencies or support for every interpreter. The setup description mentions
Python 3.7 while README says Python 3.4; neither proves compatibility with the
candidate 3.13 target.

## Original failure and license limitation

The acquisition helper's original process remains **rc 1**, with
`license_material_missing`. All three downloads had already succeeded. The
helper required an independent LICENSE/COPYING/NOTICE member; ANTLR ships none
with such a basename. PKG-INFO and setup.py declare `BSD`, but a standalone
license text is absent from this archive inventory. This is not an artifact
identity failure and does not turn the original helper result into rc 0.

A separate authorized pure-local read retained all 78 ANTLR members, modes and
hashes, plus original PKG-INFO, setup.py/setup.cfg, README, MANIFEST and egg-info
requires text. That local observation completed with rc 0 and no new network;
it does not close the license-material limitation or admit a runtime.

## Scope and remaining edges

PyYAML still needs its own exact candidate and artifact review. The dataclasses
(Python 3.6), typing (Python <3.5), and Hydra importlib-resources (Python <3.9)
markers are false for the candidate 3.13 target. Packaging, anyio, certifi,
httpcore, idna, sniffio, the other 24 floating direct project requirements, and
all applicable build/native dependencies remain unresolved. These local version
constraints do not establish a globally consistent graph. No third package was
selected here.

No pip, package import, backend, Java, model or evaluator was executed. No `.env`
was read. Finite imports/resources, generated grammar policy, toolchain/image
acceptance and project entrypoint integration remain separate work under the
existing project runtime profile.

## Retained evidence and validation

Create-only evidence is in the primary workspace under
`.lunar-evolution/validation/feature191-20261025/shinka-hydra-transitive-candidates-vwue8a7_/`;
artifact material is in its `artifact-static-freeze-3ku4ef6x/` child. The original
HTTP responses, raw files, failed process output and later local observations
remain separate. PyPI JSON and its artifact host form one distribution authority;
matching their digests is not independent publisher authentication.

The independent constraint report has SHA256
`0b894369a0ef3bb01c27f14f1169e62aceecda8d46f0c6b7bb29dbe34e9fbf93`.
The independent artifact report has SHA256
`1327712254d4d371c9040de59b64bf5b7333912b8fbb0ca68c67d87dbf1a7de6`;
it checks all three raw archives against their original JSON/HTTP declarations,
all members' bytes/modes and OmegaConf's complete RECORD. Its result is
`PASS_ARTIFACT_BYTE_IDENTITIES_WITH_UNRESOLVED_ANTLR_LICENSE_MATERIAL`.
The acquisition/local-observation index has SHA256
`65b6b04a5a7ed8638099d048bbd20f43ab27f2f45890aef1cae43ddd034ca932`;
the later independent report is separately pinned above.

This is a documentation and retained-input slice with no executable repository
change. Ruff, compileall and `git diff --check` validate repository hygiene;
existing product test results retain their original source identity. Static
archive review does not substitute for build/runtime tests.
