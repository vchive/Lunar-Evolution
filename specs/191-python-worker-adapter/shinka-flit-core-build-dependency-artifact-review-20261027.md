# Shinka flit_core build-dependency candidate artifact review

Status: candidate bytes and local static declarations independently reviewed on
2026-10-27. This is one candidate-artifact
observation under step 1 of [the existing runtime profile](project-runtime-profile.md),
following the [packaging 25.0 candidate](shinka-packaging-dependency-artifact-review-20261026.md).
It is not a resolver result, global lock, authenticated publisher build chain,
reproducible build, complete dependency/native closure, accepted executable
profile or runtime. `production_admission=false` and `online_publication=false`.

## Explicit selection and original requests

The reviewed packaging 25.0 sdist declares `flit_core >=3.3` and backend
`flit_core.buildapi`. **3.12.0** is a new explicitly selected candidate satisfying
that individual lower bound, recorded before requesting
`https://pypi.org/pypi/flit_core/3.12.0/json`. Packaging's wheel records
`Generator: flit 3.12.0`; this is only a version-selection clue. It does not
identify the actual flit_core artifact used by the publisher or establish
build provenance. No latest-version, resolver-selected or complete Shinka
compatibility claim is made.

The candidate baseline remains CPython 3.13.12, x86_64-linux-musl and Zig 0.16.0,
with the musl version unresolved. The macOS observer interpreter is not that
target. The JSON and both filenames were selected before their respective
requests. The exact release JSON lists two non-yanked files, both acquired
once from their original `files.pythonhosted.org` URLs:

| Artifact | Bytes | Members | SHA256 |
| --- | ---: | ---: | --- |
| `flit_core-3.12.0-py3-none-any.whl` | 45594 | 22 | `e7a0304069ea895172e3c7bb703292e992c5d1555dd1233ab7b5621b5b69e62c` |
| `flit_core-3.12.0.tar.gz` | 53690 | 102 | `18f63100d6f94385c6ed57a72073443e1a71a4acb4339491615d0f16d6ff01b2` |

Actual byte counts and hashes match the release JSON. The three requests had
zero retries and zero redirects. Each had a 30-second socket timeout and
absolute SIGALRM deadline; JSON was capped at 2 MiB and each artifact at 16 MiB.
The metadata observer returned raw rc0 within its 40-second outer bound; the
two-artifact observer returned raw rc0 within its 75-second outer bound.
Original response headers, claims, process streams and terminal receipts are
retained. The reader streams partial bytes to create-only files before further
inspection, rather than discarding them if a request fails; no request failed
in this acquisition.

## Archive identity and metadata

All 22 wheel and 102 sdist members are regular files, with original ZIP mode
`0o100644` and tar mode `0o644`. Every member's name, mode, size and SHA256 is
retained. Archive readers allow at most 10000 members, 64 MiB expanded content
and 2 MiB of retained text per member. No package member was extracted to a
package filesystem tree. The complete 22-row wheel RECORD covers every file
exactly once, with matching SHA256 and size and empty self hash/size.

The wheel's 17 files outside its top-level dist-info directory, including
vendored source, metadata, README and typing resource, match their sdist
counterparts byte for byte. All 13 wheel Python source files and all 47 sdist
Python source files parse as AST with the observer interpreter. This parses
the source; it does not import or execute it, or validate a target interpreter.

The JSON, top-level wheel METADATA and sdist PKG-INFO declare
`Requires-Python: >=3.6` and no Requires-Dist entries. The source project also
declares `dependencies = []`. The actual WHEEL contains `Tag: py3-none-any`,
`Root-Is-Purelib: true` and `Generator: flit 3.12.0`. No native-extension suffix
member occurs in the wheel. These facts do not accept the finite CPython
stdlib/loader or prove compatibility with the proposed static target.

## Self-hosted build declaration and vendored material

The root sdist pyproject declares:

```toml
[build-system]
requires = []
build-backend = "flit_core.buildapi"
backend-path = ["."]
```

This is a self-hosted backend declaration with no declared external bootstrap
requirements. The root project's dynamic version is backed by the retained
`flit_core/__init__.py` constant `__version__ = '3.12.0'`. No backend hook or
self-build ran. Sample pyproject files under `tests_core/` declare their own
fixture dependencies; they are retained without treating them as root project
requirements. Included `bootstrap_install.py` and `build_dists.py` also remain
unexecuted source, rather than accepted install/build entrypoints.

Both artifacts include vendored `tomli` source, a README describing its
bootstrapping role, `tomli-1.2.3.dist-info/METADATA`, and an MIT license. That
embedded metadata says `Name: tomli`, `Version: 1.2.3`,
`Requires-Python: >=3.6`, no Requires-Dist, and an MIT license classifier; it has
neither a License nor a License-Expression header. The source's own version
constant also says 1.2.3. These observations identify the bundled bytes, not an
independent comparison with an original tomli release. No separate tomli
artifact was fetched or silently added to the profile.

The top-level METADATA and PKG-INFO declare
`License-Expression: BSD-3-Clause`, and License-File headers for `LICENSE` and
`flit_core/vendor/tomli-1.2.3.dist-info/LICENSE`. Standalone material agrees
between wheel and sdist:

| Material | Bytes | SHA256 |
| --- | ---: | --- |
| Root BSD three-clause LICENSE | 1525 | `35b4f1dec512e617077fd6980dbb43ef8c2887adc5d0185edb4c04da175dd816` |
| Vendored tomli MIT LICENSE | 1072 | `b80816b0d530b8accb4c2211783790984a6e3b61922c2b5ee92f3372ab2742fe` |

The wheel additionally carries an identical tomli license under its top-level
dist-info/licenses tree. `versionno.py:8-31` retains inline packaging/PEP 440
regex attribution and BSD two-clause text. `_spdx_data.py` says its dictionary
is generated from SPDX license data; this review preserves that source but
does not authenticate the originating dataset or generator. Sdist test fixture
license files are retained separately from the root and vendor license texts.

## Execution boundary and original reader failure

An empty root Requires-Dist or build requirement list does not make arbitrary
backend use an inert operation. `buildapi.py:21-43` can return a target
project's runtime requirements when dynamic metadata cannot be obtained
statically. `common.py:180-228` retains the metadata fallback that calls
`spec.loader.exec_module(m)` at line 201. `config.py:10-18` first tries stdlib
tomllib, then vendored tomli, then external tomli if the bundled import fails.
These routes were inspected as source and never invoked. Finite build inputs,
entrypoints, source/resource access, custody and loader facts still require
their own review before any build or runtime admission.

The original static observer returned raw rc1: its inherited reader counted
nested `flit_core/vendor/tomli-1.2.3.dist-info` as another top-level distribution
and raised `wheel_dist_info_invalid`. This was a reader assumption failure,
not an artifact hash or RECORD mismatch. Its original script, empty stdout,
819-byte stderr and terminal receipt remain untouched.

A separate create-only local successor identifies dist-info by the top-level
path component and includes nested vendor files in the source comparison. It
returned raw rc0 within its 40-second bound. No artifact was fetched again and
no acquisition or prior observer was rerun. The successful observation does
not overwrite the first failure or replace an independent review.

## Retained evidence and open work

Create-only primary-workspace evidence:
`.lunar-evolution/validation/feature191-20261027/shinka-flit-core-build-candidate-8dxnimm2/`.
Successful static reports and their process evidence are in
`static-successor-review-savduosi/`. The exact release JSON is 3189 bytes,
SHA256 `f8483d52f3957adacc30376fdc3855fc103b51862e14f13ed3a80da7461df0b3`.

The terminal index covers all 50 completed original/successor files, excluding
itself, SHA256
`85dffbb2f6589047e8c4b55a71bddd69e5b7daf87af54fd69dc5b42321424f04`.
`observation-terminal-summary.json` has SHA256
`8836abb3a84bb6a2422b522e52a77d2774e1aff5f63539d86dee3b1669d577a0`;
`local-supplemental-declaration-review.json` has SHA256
`80fa69618b6a96b63db7e18d4b03526ae448c3ee250a6613280d9b47d462cfd3`.
The successor's `dependency-candidate-artifact-review.json` has SHA256
`13c14104480599caab7498decfd02fb67834e2b77ee7007d6f53bd8a6d45e78f`.
PyPI and its artifact host remain one distribution authority; their matching
hashes are not independent publisher authentication.

The packaging build edge now has one explicit candidate identity observation,
independently audited. The separate review checks all 50 terminal-index files,
archive members/modes/hashes, RECORD, source correspondence, metadata, licenses,
build declarations and original failure/success receipts. All 33 checks passed;
original files remained unchanged across the audit. The report is retained in
`feature191-20261027/shinka-flit-core-independent-review-6s4glqul/review.json`,
SHA256 `e909a53fae73f32f92610188f2bc092dd9868acc476c92ac5c41e00329ac1ca2`.
The report's spec pin identifies the pre-audit draft; this paragraph records the
later independent result without relabeling the draft or artifact evidence.

Full build/native dependency closure, the ANTLR
license gap, PyYAML/LibYAML/toolchain inputs, HTTPX transitive dependencies,
the other floating Shinka requirements, immutable custody, finite executable
profile, lifecycle and production CLI acceptance remain open. This observation
does not satisfy the separate Linux mixed or complete CI acceptance gates.

No pip/resolver/install, third-party import, backend/native build, project,
model, evaluator, SSH or .env read occurred. Product source, benchmark sources
and frozen acceptance archives were not modified. This change adds only this
review document; the parent task handles independent review and task/status
updates.
