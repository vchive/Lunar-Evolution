# Shinka PyYAML dependency candidate artifact review

Status: one candidate dependency identity statically reviewed on 2026-10-26,
continuing the [Hydra candidate review](shinka-hydra-dependency-artifact-review-20261026.md)
and step 1 of the [existing runtime profile](project-runtime-profile.md).
This is not a resolver result, complete dependency closure, compatibility result,
accepted image or runtime. `production_admission=false`, `online_publication=false`.

The candidate baseline remains CPython **3.13.12**, **x86_64-linux-musl**, Zig
**0.16.0**. The macOS observer interpreter is not that runtime.

## Selection and official artifacts

OmegaConf 2.3.0's reviewed wheel declares `PyYAML (>=5.1.0)`. PyYAML **6.0.3**
was selected explicitly before its exact public PyPI JSON request. This version
satisfies that individual lower bound; it does not establish global consistency.
The exact JSON lists 73 distribution files. Only the following two were selected
before artifact acquisition, both non-yanked:

| Artifact | Bytes | Members | SHA256 |
| --- | ---: | ---: | --- |
| `pyyaml-6.0.3-cp313-cp313-musllinux_1_2_x86_64.whl` | 794115 | 28 | `eda16858a3cab07b80edaf74336ece1f986ba330fdb8ee0d6c0d68fe82bc96be` |
| `pyyaml-6.0.3.tar.gz` | 130960 | 656 | `d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f` |

The JSON was fetched once under 2 MiB. Each artifact was fetched once from its
exact declared `files.pythonhosted.org` URL under 16 MiB, with a 30-second socket
and absolute alarm deadline and zero HTTP retries. Actual size/SHA256 match the
original JSON. Archive expansion was bounded at 64 MiB and 10,000 members, with
selected source text capped at 2 MiB per member. No package member was installed
or extracted to a package filesystem tree.

The actual WHEEL tag is `cp313-cp313-musllinux_1_2_x86_64` and
`Root-Is-Purelib: false`. Complete RECORD inventory, SHA256 and sizes match all
wheel files. Independent bounded archive readers verify every member's original
mode and bytes against the first observation. The tag identifies a candidate
CPython 3.13 x86_64 binary requiring musl>=1.2; the baseline has not yet fixed or
validated its musl version, and this tag is not runtime acceptance.

## Python and build declarations

The JSON, wheel METADATA and sdist PKG-INFO declare `Requires-Python: >=3.8`.
They contain no Requires-Dist entries (`null` in the JSON/retained field lists).
That is a metadata fact, not a complete import/build/native dependency proof.

The original sdist pyproject.toml declares:

```toml
[build-system]
requires = [
    "setuptools",
    "Cython; python_version < '3.13'",
    "Cython>=3.0; python_version >= '3.13'"
]
backend-path = ["packaging"]
build-backend = "_pyyaml_pep517"
```

For the candidate 3.13 interpreter, `setuptools` and `Cython>=3.0` are applicable
build requirements; neither is an exact selected build identity. The local
backend source bridges setuptools.build_meta through ActiveConfigSettings.
It is retained as text and has not run. setup.py imports setuptools/distutils,
attempts optional Cython and wheel integrations, and declares
`Extension('yaml._yaml', ['yaml/_yaml.pyx'], ..., libraries=['yaml'])`. The sdist
contains the original `.pyx`, `.pxd` and header declarations, but no generated
`yaml/_yaml.c` member. Generated C, compiler flags, LibYAML headers/library and
the controlled build recipe remain unaccepted. Optional wheel imports do not
select an exact wheel-package dependency.

Source selection of LibYAML is optional: setup.py supports with/without-libyaml
and fallback, while yaml/__init__.py tries cyaml and catches ImportError. A
future finite profile must explicitly bind this choice; ambient availability or
silent fallback cannot substitute for a reviewed closure. No variant is admitted
by this artifact review.

## Native and license observations

The wheel contains one native extension:

```text
yaml/_yaml.cpython-313-x86_64-linux-musl.so
size: 1906976
SHA256: 9e0ff8804b4583a19a9b51478a37cf469188d64e6732f4af15f03d989b50b385
```

Pure byte decoding observes ELF64 little-endian EM_X86_64, dynamic
`DT_NEEDED: libc.musl-x86_64.so.1`, no SONAME/RPATH/RUNPATH, and 54 exported
`yaml_` symbols with no undefined `yaml_` symbols. These observations do not
establish which LibYAML source/version, generated source, toolchain or static
link recipe produced this binary. No ELF initializer, shared library or Python
package was executed. The reviewed wheel bytes are a distribution artifact,
not an accepted static runtime image.

Both artifacts retain the same standalone MIT LICENSE: 1101 bytes, SHA256
`8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4`.
The native provenance/closure still needs its own source and license inventory;
this package license alone cannot identify all compiled input bytes.

## Original failure and evidence

The first artifact-helper process remains **rc 1**: the default observer Python
lacked stdlib tomllib and failed before main, artifact request claims or any
artifact download. Those raw streams and registration remain retained. The
unchanged helper then ran under the already installed macOS CPython 3.13.12,
returning rc 0. This did not refetch the JSON or retry an HTTP artifact request.
No interpreter/package installation was performed.

Create-only evidence is under the primary workspace:
`.lunar-evolution/validation/feature191-20261025/shinka-pyyaml-candidate-p7u17eds/`.
The successful artifact child is
`artifact-static-freeze-supported-runtime-iyfxfnhy/`; the original startup failure
is separately preserved under `artifact-static-freeze-86b3fz44/`.

The exact JSON is 66402 bytes, SHA256
`c3f35597bc2f08cc990c2a5fe57bef6687b3a3d7c61d8b0ba4cc067777eb1def`.
The independent local archive/ELF report SHA256 is
`b90f9b029f2b89cd11cd65c1a14694e09ae0eedb155f5510a930afb8db3cf78a`.
It covers byte identities and declarations only. PyPI JSON and its artifact host
are one distribution authority; matching hashes are not independent publisher
authentication.

No pip, package import, backend, native code, producer, model or evaluator was
executed, and no .env was read. The existing ANTLR license-material limitation,
other unresolved runtime/build requirements, finite loader/resource inventory,
source/toolchain/static-image acceptance and executable project entrypoint
remain open. This slice closes only the missing exact PyYAML artifact observation
within step 1, not the complete step or SDK execution support.

A second independent local review rechecks the 44 evidence-index records, both
complete member inventories, wheel RECORD, metadata/build declarations and ELF
dynamic/symbol tables. Its report is retained under primary-workspace
`release-closeout-20261025/pyyaml-independent-second-yxavz1pc/review.json`, SHA256
`4c5393d586f3020f61586ea8aa9bf9a7119141375e2830bb3d5cf952b8793aa7`.
The WHEEL generator declaration `setuptools (80.9.0)` is not an independently
selected or accepted build identity.
