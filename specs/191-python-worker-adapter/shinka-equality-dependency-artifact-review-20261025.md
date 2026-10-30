# Shinka equality-pinned dependency artifact review

Status: two explicitly pinned dependency releases and their published source
and universal-wheel bytes retained and statically reviewed on 2026-10-25.
Root independently checked the retained bytes with result
`PASS_DEPENDENCY_ARTIFACT_IDENTITIES_ONLY`. This completes only a dependency-artifact
subitem of step 1 in [project-runtime-profile.md](project-runtime-profile.md).
It does not complete Shinka's direct/transitive/build/native dependency closure,
select an executable profile, install packages or accept a runtime.
`production_admission=false`.

## Selection and target boundary

The already reviewed Shinka v0.0.7 source, commit
`c4568adde253cacf185be3a8412c3c2142761ebe`, declares `hydra-core==1.3.2` and
`httpx==0.27`. This slice freezes public releases **hydra-core 1.3.2** and
**httpx 0.27.0**, using the latter's normalized public release version. It
introduces no selection for the other 24 floating direct requirements or any
transitive/build requirement. See the existing
[source review](shinka-source-profile-review-20261025.md) for the Shinka source
identity; that source review was not repeated here.

The candidate build baseline remains CPython **3.13.12**,
**x86_64-linux-musl**, Zig **0.16.0**. This document does not replace it with the
observer's macOS Python, a glibc/manylinux runtime, host site-packages or an
installed wheel. Both retained wheels declare `py3-none-any` and
`Root-Is-Purelib: true`. Those declarations identify published wheel packaging;
they do not prove CPython 3.13, musl, frozen-loader or static-image compatibility.

## Original bytes and acquisition

All raw material is create-only ignored evidence under
`.lunar-evolution/validation/feature191-20261025/shinka-equality-dependency-freeze-y4v6iloi/`
in the primary workspace. The exact-version PyPI JSON snapshots are retained,
along with each request's original URL, response/final URL, status, headers,
UTC observation time, size and SHA-256. The snapshots each list exactly one
sdist and one universal wheel; all four were acquired. No moving latest/index
resolution, `pip`, backend, package import or executable was used. Every
acquisition in the retained helper run succeeded on its first attempt.

| Retained file | Bytes | SHA-256 |
| --- | ---: | --- |
| `hydra-core-1.3.2.pypi.json` | 19,302 | `dcc39203cef563376e95350aea5a82f6852a8ed75dc4c2d825ea4444c01a7ea0` |
| `hydra_core-1.3.2-py3-none-any.whl` | 154,547 | `fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b` |
| `hydra-core-1.3.2.tar.gz` | 3,263,494 | `8a878ed67216997c3e9d88a8e72e7b4767e81af37afb4ea3334b269a4390a824` |
| `httpx-0.27.0.pypi.json` | 9,163 | `6b699cd0fedea6327969672bd2ac556665f2d16736767f5d0299e74a50c5720c` |
| `httpx-0.27.0-py3-none-any.whl` | 75,590 | `71d5465162c13681bff01ad59b2cc68dd838ea1f10e51574bac27103f00c91a5` |
| `httpx-0.27.0.tar.gz` | 126,413 | `a0cb88a46f32dc874e04ee956e4c2764aba2aa228f650b06788ba6bda2962ab5` |

The exact metadata endpoints are
`https://pypi.org/pypi/hydra-core/1.3.2/json` and
`https://pypi.org/pypi/httpx/0.27.0/json`. Artifact URLs, including their complete
`files.pythonhosted.org` paths, are retained in those snapshots and
`dependency-artifact-review.json`. Each actual artifact size and SHA-256 matches
its retained JSON declaration. All four were reported `yanked=false` in those
snapshots. PyPI and its artifact host are one distribution authority here;
matching those observations is not independent publisher authentication. No
signature, provenance attestation or correspondence to a separately authenticated
dependency source commit was verified.

The create-only standard-library helper `freeze-dependency-artifacts.py` is
10,416 bytes, SHA-256
`dc0cef5f93fcad6fbe5a60c905007cc7de4deae83e56a5018017a4e9fecaa588`.
`dependency-artifact-review.json` is 3,114 bytes, SHA-256
`37b83a5d80cdd37708236f79fe194edcf3862f3d08c3b28e7699501cc6856b09`.
The acquisition `evidence-index.json` is 6,152 bytes, SHA-256
`735b6a3facccd4391ff20cbe83bde4dd13a62963618f04ceecf88166b972d7a4`.
The helper reads archive bytes as data and refuses existing output names; it
must not be rerun into that same directory. These retained observations are
not an enforced build-custody interval.

The independently produced `root-independent-review.json` has SHA-256
`fdb4927f3f108568d57ba31ae0894ab10d64896239124399c5bb50abaee6e518`.
It checks all 35 acquisition-index files, all four archives' complete member
bytes/modes, wheel metadata, licenses and RECORD, and source build controls and
the included JAR. The reviewer's first refusal incorrectly required every ZIP
payload to carry `S_IFREG` type bits; `root-independent-initial-refusal.py` and
`root-independent-initial-refusal.json` remain retained. The corrected review
distinguishes missing type bits from explicit
special types, without changing upstream material. This is a reviewer correction,
not an upstream build or runtime failure.

## Wheel metadata, license and RECORD observations

Both wheels were read with `zipfile`, without extraction or importing package
code. Member paths were checked for absolute/traversal/backslash paths and
duplicates; encrypted and explicitly special-type members were refused. The static
index retains each member's original ZIP attributes, compression, CRC, size
and content SHA-256. The hydra wheel has 150 files; the httpx wheel has 30 files.
Hydra's attributes contain 149 modes `0100644` and one `0664` (its RECORD);
httpx has 25 modes `0100644` and five `0644`. The latter modes have no file-type
bits: they are accepted as untyped ZIP payloads, not asserted to be `S_IFREG`.
No missing type bits are silently added to the retained attributes.

Each wheel has one `.dist-info` directory with the expected `Name` and exact
`Version`. Its `RECORD` names every file exactly once. Every non-`RECORD` member
has a matching SHA-256 and size; the `RECORD` row itself has the expected empty
hash/size. Reading every member also exercises ZIP CRC checking. This checks
internal archive consistency, not an external signature or permission to load
those modules. Original `METADATA`, `WHEEL`, `RECORD` and license bytes are
separately retained under `reviewed-text/`.

| Item | hydra-core 1.3.2 | httpx 0.27.0 |
| --- | --- | --- |
| `METADATA` SHA-256 | `399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7` | `214ea06d0fc2e4c61072ca3a7ed03cd0262fe4f168997893578b5e9544b9a119` |
| `RECORD` SHA-256 | `dcdb3558d3cfcd3f9b84782b1f319b9452b133c0e63cb14421427c058f2f4eba` | `aa84bff180f918bc4e81f893e025cf33b4b3f81e86d811c0ef3658c1995ca12c` |
| Python requirement | No `Requires-Python` header | `>=3.8` |
| License | `License: MIT`; `.dist-info/LICENSE`, 1,086 bytes | BSD classifier and sdist `license = "BSD-3-Clause"`; `.dist-info/licenses/LICENSE.md`, 1,508 bytes |
| License SHA-256 | `52412d7bc7ce4157ea628bbaacb8829e0a9cb3c58f57f99176126bc8cf2bfc85` | `4ec59d544f12b5f539a3a716fd321ac58ccd8030b465221f2c880200cdf28d8d` |
| Wheel generator field | `bdist_wheel (0.38.4)` | `hatchling 1.21.1` |

The generator fields are publisher metadata, not accepted build-tool bytes or
reproducibility evidence. Each sdist retains a license with the same bytes as
its wheel's license. The httpx wheel has no `License` header; this review does
not invent one from the classifier or source declaration.

## Dependency declarations and markers

The retained wheel `METADATA` states these requirements; they match the
corresponding exact-version JSON lists:

| Release | `Requires-Dist` |
| --- | --- |
| hydra-core 1.3.2 | `omegaconf (<2.4,>=2.2)`; `antlr4-python3-runtime (==4.9.*)`; `packaging`; `importlib-resources ; python_version < "3.9"` |
| httpx 0.27.0, base | `anyio`; `certifi`; `httpcore==1.*`; `idna`; `sniffio` |
| httpx, optional markers | `brotli; (platform_python_implementation == 'CPython') and extra == 'brotli'`; `brotlicffi; (platform_python_implementation != 'CPython') and extra == 'brotli'`; `click==8.*; extra == 'cli'`; `pygments==2.*; extra == 'cli'`; `rich<14,>=10; extra == 'cli'`; `h2<5,>=3; extra == 'http2'`; `socksio==1.*; extra == 'socks'` |

The hydra `python_version < "3.9"` edge is false for the proposed 3.13 baseline.
The two Shinka direct declarations request no extras. Neither observation
resolves the complete graph: another selected dependency can request extras,
and all applicable versions, artifacts, markers and conflicts must be reviewed
together. `==4.9.*` and `==1.*` still leave version choices; they are not exact
artifact identities. No transitive artifact was selected or acquired here.

Hydra's Python classifiers end at 3.11; httpx's end at 3.12. Missing 3.13
classifiers neither prove failure nor establish support. Parsing metadata and
retaining pure-Python wheels does not demonstrate target execution, runtime
import/resource closure, loader refusal or behavior under cancellation.

## Source and build boundary

The hydra sdist has 181 regular files and 48 directory records; the httpx
sdist has 69 regular files. Every regular file's content SHA-256 and original
tar mode, plus directory records, is retained in its static-review index.
No symlink, hard-link or special-file member was accepted. These tar permission
modes are not silently normalized to Git modes. No sdist was extracted or built.

The hydra `pyproject.toml` has no `[build-system]` declaration. Its retained
`setup.py` imports `setuptools`, `pkg_resources` and local `build_helpers`,
reads `requirements/requirements.txt`, and installs custom build commands.
`build_helpers/build_helpers.py:148–153,171–199` includes an ANTLR generation
route that invokes Java with its included JAR. The sdist contains
`build_helpers/bin/antlr-4.9.3-complete.jar` (3,508,089 bytes, SHA-256
`afcd40946d3de4d81e28d7c88d467289e0587285d27adb172aecc5494a17df36`).
The raw sdist pins those bytes; this does not select or accept a Java runtime,
ANTLR execution, generated parser provenance, setuptools version or backend
policy. This review does not execute `setup.py` to discover requirements.

The httpx sdist explicitly declares backend `hatchling.build` with unversioned
build requirements `hatchling` and `hatch-fancy-pypi-readme`. Those requirements
and their own closure remain unselected. The retained sdist contains
`pyproject.toml` and `PKG-INFO`; its `PKG-INFO` bytes equal the wheel's
`METADATA`. This does not prove that rebuilding the sdist produces the wheel
or a valid frozen module inventory. Neither prebuilt wheel is accepted as an
escape from the existing same-source/static-build gates.

## Next executable slice and acceptance limits

The next unblocked work is to select and retain exact versions/artifacts for
the applicable dependency graph and build controls, using these actual
metadata edges, while reviewing the fixed Shinka patch/entrypoint and its
finite imports/resources. The other 24 direct declarations, transitive
dependencies, generated sources, scientific/native/static-link inputs,
standard-library additions and target/ABI behavior remain open. Disabling
Hydra's arbitrary-factory entry route does not by itself authorize removing a
declared requirement; any reduced closure needs a reviewed profile patch and
actual reachability/resource evidence.

KVM access is unnecessary for this byte-acquisition and static archive review.
It does not repair the separately failed build-custody mechanism or authorize
configure/freezer/compile/target execution. Preserve the current fixture pins
and nine-module profile. No DTO, new loader, launch API, broker or evaluator was
added. No upstream package, `pip`, resolver, build backend, JAR, project, model,
solver, WebAgent or remote/company evaluator was executed. No user's `.env`
file was read. This document-only slice was checked with
`git diff --check`; no executable repository behavior changed.
