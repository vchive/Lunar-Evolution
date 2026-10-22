# Authenticated CPython source and bounded import audit (2026-10-21)

## Scope and evidence limits

This read-only audit inspected the pinned CPython 3.13.12 release archive and a previously staged source tree on 5090gpu (host name observed as worker01), plus the Lunar-owned frozen-main source template in this repository. It did not extract the archive, build or install software, run a fixture/evaluator, or modify the staging tree. The source audit is limited to eight Python files used by the current frozen-module profile; it is not a complete import graph.

The archive is the authenticated release input. The expanded staging directories are separate observations and must not be treated as pristine or authenticated source trees. No Git checkout or complete source-and-patch provenance was found for those staging directories.

## Release archive identity

The archive observed at /tmp/lunar-toolchains/sources/Python-3.13.12.tar.xz on 5090gpu is 22,926,488 bytes with SHA-256:

2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593

This matches the digest recorded on the python.org CPython 3.13.12 release page and the archive digest in the retained release-input audit. The retained audit bundle is /home/qinzhiqing/vchive/lunar-cpython31312-probe.4V1KB0/. Its signature-verification transcript records GOODSIG and VALIDSIG for Thomas Wouters, primary fingerprint 7169605F62C751356D054A26A821E680E5FA6305, for the detached signature over the verified release archive. The python.org OpenPGP metadata page identifies Thomas Wouters and key ID A821E680E5FA6305 as a signer for CPython 3.12/3.13 source releases.

Signature limits: GnuPG reported TRUST_UNDEFINED because no local web-of-trust certification was configured. The signer-to-release association is cross-checked against saved python.org metadata. This audit read the retained verification transcript rather than re-running GnuPG; it does not independently establish the authenticity of the key outside that metadata cross-check, verify a Git tag or source commit against the archive, or make the remote evidence bundle self-contained in this repository.

A read-only tarfile inspection of the archive observed 5,245 members, 4,837 regular files, 108,687,660 bytes across regular files, and the single top-level root Python-3.13.12/.

## Expanded staging comparison

The existing tree at /tmp/lunar-toolchains/cpython-staged/Python-3.13.12 is not a pristine extraction. Comparing each archive regular member byte digest with the corresponding staged file found 4,834 identical files, 3 changed files, no missing regular archive paths, and 24 extra files, all observed as .pyc files. This is an observed comparison against the archive; the directory itself has no Git metadata, and its complete patch history was not established.

| Path | Authenticated archive member SHA-256 | Observed staged file SHA-256 |
| --- | --- | --- |
| Python/import.c | 4e18922dc31001c24fd9875746881ab407252bddc6bca544f22403d50e493a61 | 58a5fac8fac5916511f890f3fdd095d817e6f32ab709ebf0ed0becf9328226b1 |
| Lib/importlib/_bootstrap_external.py | a97a03ea9f9d38d90c8a50942183382ff5a479e7c4c5163c2ac5bae3561444ae | 2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab |
| Lib/encodings/aliases.py | cac92d68c7ea5bc0f05b448b9144e3bdf236d0b7d27ab66112e96d43aad15b3f | 43aadac378861c1bbdaaf04be8e1bb7d878529a7641ec123b5df4eccdd4c6106 |

A prior read-only review records fixture-specific changes in Python/import.c and an empty _get_supported_file_loaders() implementation in Lib/importlib/_bootstrap_external.py. The identity and intended effect of every staged change are not established by this comparison. The sibling cpython-fullfreeze and G2 probe trees are also staged observations, not release-authenticated trees.

## Bounded AST observations

AST parsing was performed on bytes read directly from the authenticated tar members, using Python ast.parse; archive members were not extracted. Imports nested in functions and conditional branches are included below, so an AST import root is not proof that the edge runs during startup. Platform-conditional and deferred edges are marked where visible in source. No __import__ or importlib.import_module call was found in these eight CPython files other than the dynamic codec import in encodings. The loader's exec_module method calls are not dynamic module-name resolution.

| Frozen module | AST import roots and relevant edges | Dynamic import observation |
| --- | --- | --- |
| _frozen_importlib (Lib/importlib/_bootstrap.py) | _frozen_importlib_external (bootstrap setup; line 1549) | No __import__/import_module call found. |
| _frozen_importlib_external (Lib/importlib/_bootstrap_external.py) | _imp, _io, sys, _warnings, marshal, posix on Linux; nt and winreg on Windows; deferred tokenize; deferred importlib.readers; deferred importlib.metadata. | No __import__/import_module call found. |
| abc (Lib/abc.py) | _abc, with _py_abc imported as an ImportError fallback. | No dynamic import call found. The fallback target is outside the current finite profile and needs an explicit disposition or a proven unreachable gate. |
| codecs (Lib/codecs.py) | builtins, sys, _codecs; encodings imported by the open() helper. | No dynamic import call found. |
| encodings (Lib/encodings/__init__.py) | codecs, sys, relative .aliases; Windows-only _winapi and encodings.mbcs branches. | At line 99, __import__('encodings.' + modname) computes the codec module name at runtime. This source alone does not limit the target to encodings.utf_8. |
| encodings.aliases (Lib/encodings/aliases.py) | No import statements found. | No dynamic import call found. |
| encodings.utf_8 (Lib/encodings/utf_8.py) | codecs. | No dynamic import call found. |
| io (Lib/io.py) | _io and abc; named imports from _io. | No dynamic import call found. |

These observations identify source-level roots and candidate edges only. They do not prove branch reachability, C-startup behavior, import origin, generated frozen-module identity, or closure of runtime-selected imports.

## Lunar observer replay over authenticated archive members

The eight exact `.py` member byte strings above were passed to the bounded Lunar
`audit_static_python_imports` observer after reading them directly from the
verified archive. The archive remained at 22,926,488 bytes with SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`. The
observer input totaled 200,001 bytes; the largest source was
`_frozen_importlib_external` at 73,219 bytes. No archive member was written to a
filesystem path or executed.

For this call only, each member's SHA-256 was calculated from the member bytes
and supplied as the scanner's expected digest. Those call-time values verify
that the scanner consumed the same byte strings; they are not independent
per-file release pins. The canonical scanner result is 3,471 bytes with
SHA-256 `9e3a0ad1fb808f703f20ed993247e732130f0ccff9b03328196153766bdd9d8f`.
It records 28 deduplicated import edges, zero unresolved imports, and four
unsupported sites:

| Source | Line | Column | Observation |
| --- | ---: | ---: | --- |
| `_frozen_importlib` | 1176 | 8 | `dynamic-code-execution` (`exec`) |
| `_frozen_importlib_external` | 1431 | 15 | `dynamic-code-execution` (`compile`) |
| `codecs` | 16 | 4 | `star-import` |
| `encodings` | 99 | 18 | `dynamic-import` (computed codec module name) |

The two `exec`/`compile` observations are dynamic code execution sites, not
computed module imports. Every scanner claim remains false, including complete
source graph, configured closure, build, startup, installation acceptance and
production admission. This replay demonstrates that the observer processes
these exact archive bytes within its current bounds; it does not authenticate
the call-time per-file pins, expand the configured source scope, or establish
runtime import closure. The source-preparation contract now records explicit
dispositions for the two observed source issues: `_abc` is required and the
same `ImportError` is re-raised without `_py_abc` fallback; codec selection is
fixed to UTF-8 and six retained aliases, with other names returning the normal
lookup miss. Tests exercise these source transformations, including registering
the synthetic lookup callback with the host `codecs.lookup` API. This does not
prove the patched frozen modules are built or registered during target startup.

## Expanded Lunar frozen-main source check

The provider-free integration test
`tests/test_static_python_source_import_profile.py` emits the fixed build plan,
reads the exact expanded `_lunar_static_main` source referenced by its reviewed
freeze task, and checks the emitted bytes against that task's 6,794-byte
`6e6a9e661f50dc1baf5b1e6e1f2a717468f1351d7fc6d534ecae125717e0695d` pin before
passing those same bytes to the AST observer. It observes `_imp`,
`_lunar_fixture_pipe` and `sys`, with no unresolved imports. The loader-negative
case's computed `__import__(name)` remains one unsupported site at line 68,
column 47. The test confirms all observer capability claims remain false.

The freeze-task pin and emitted-source comparison check the reviewed local plan
and emitter together; they do not independently authenticate the task pin,
generate frozen bytecode, or establish runtime reachability or loader refusal.

## Lunar-owned frozen main template

The Lunar source is separate from the CPython archive. The repository template tools/static_python_fixture/assets/frozen_main.py was observed as 6,223 bytes, SHA-256 627bc8e6520c58859f5d5c33d06423a7588c6f6465f5b453605f6de7ab6a64a1. Its AST import roots are _imp, sys, and _lunar_fixture_pipe. It contains a computed __import__(name) call at line 68 in the loader-negative case; that case iterates a fixed literal tuple of refusal-probe names. This is a bounded probe in the template, but the final runtime behavior still depends on the selected case and emitted source.

The RSI wrapper tools/static_python_rsi_fixture/assets/frozen_main.py was observed as 432 bytes, SHA-256 fc6f3b4908d284a57b26a9434018f8394d9f566958081d77d509da010eda5069. It adds no imports and delegates to _main. The base template contains __LUNAR_EXPECTED_*__ placeholders, and the recipe expands manifest values before freezing. The CPython staging tree did not contain Lib/_lunar_static_main.py. Therefore the repository template hash is not a hash of the exact emitted _lunar_static_main source; binding emitted bytes requires the actual expansion values and a retained preparation/freeze receipt.

## Reproduction and acceptance boundary

The archive digest can be checked read-only on 5090gpu with sha256sum /tmp/lunar-toolchains/sources/Python-3.13.12.tar.xz. To repeat the source parse without extraction, open that path with Python tarfile in r:xz mode, read a named member with TarFile.extractfile(), then pass the returned bytes to ast.parse(). For the staged comparison, hash each regular tar member's bytes and the corresponding file under /tmp/lunar-toolchains/cpython-staged/Python-3.13.12; do not use extractall(). The Lunar template can be independently hashed and parsed from the repository path above.

This document does not prove a complete startup/import closure, validate all C startup edges or configuration gates, verify generated frozen headers/tables against the reviewed bytes, establish actual runtime module origins or refusal behavior, or demonstrate a successful build or runtime. It is not production or release acceptance. No WebAgent, remote evaluator, company evaluation platform, solver campaign, build, or installation was used.
