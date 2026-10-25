# Candidate codec negative workload slice

## Problem and scope

The current candidate `loader-negative` case checks finite file, bytecode,
extension, zip and ordinary import refusal. It does not call the codec lookup
API. The existing source-preparation tests exercise a synthetic callback through
the host codec registry; that does not establish the candidate workload's
unknown-codec behavior.

Extend the installation-owned candidate source with one fixed internal helper.
Use only the already expected `sys.modules["codecs"]` entry. In the existing
`loader-negative` case, require the canonical UTF-8 name and the six reviewed
aliases (`cp65001`, `u8`, `utf`, `utf8`, `utf8_ucs2`, `utf8_ucs4`) to identify
UTF-8 and encode/decode one fixed string correctly. Require one fixed unsupported
name, `lunar_only_unavailable_codec`, to raise `LookupError`. Return no new
observation fields. The fixed cases, finite module inventory and existing
`loader_negative.direct` / `loader_negative.ordinary` wire shape stay unchanged.

Take module-name/object and `sys.path` / `sys.path_hooks` snapshots around this
bounded check. A changed snapshot must fail the candidate case. These are local
observations at the helper boundary, not an enforcement claim about transient
imports, another interpreter, or arbitrary code.

## Implementation and validation

Change `tools/static_python_fixture/assets/frozen_main.py`, add focused tests
that extract only the repository-owned helper AST into a synthetic `sys` map,
and adapt the existing synthetic observation fixture to provide the fixed codec
lookup. Do not execute archived source, build tools, a solver or the target
runtime. Verify success, wrong codec/name/roundtrip results, unsupported-name
admission, unexpected exception, inventory/object/path drift, and helper routing.
Keep the original baseline behavior and observation protocol intact.

A candidate source change requires explicit new candidate build-input pins and
any dependent candidate RSI overlay pins. Do not change historical source audit
graphs or observations to make them appear to describe the new source. Retain
old source bytes where an old audit is replayed. Run the affected pure
source-plan, readiness, encoder and RSI projection tests; record their result
without claiming configured consumption, static compilation, sealed startup,
G2/G3 completion, or production admission.

## Candidate identity transition

Before this slice (commit `5ce6d674cfa170cd3955836bffab1354313a7b84`):

| Candidate input | Bytes | SHA-256 |
| --- | ---: | --- |
| Raw `assets/frozen_main.py` template | 6,223 | `627bc8e6520c58859f5d5c33d06423a7588c6f6465f5b453605f6de7ab6a64a1` |
| Expanded `assets/frozen_main.py` | 6,794 | `6e6a9e661f50dc1baf5b1e6e1f2a717468f1351d7fc6d534ecae125717e0695d` |
| `reviewed-build-inputs.json` | 80,050 | `c305d56956b75eda286b0e630ceeeaa0f37db2e9f669879eb30a563f8dd2bb31` |

The new candidate identities and focused validation results are recorded below
only after implementation. The old identities above remain historical evidence.


After this slice, the new candidate identities are:

| Candidate input | Bytes | SHA-256 |
| --- | ---: | --- |
| Raw `assets/frozen_main.py` template | 7,329 | `6d1f3aaf075b62c7d5c36128e6cfff8dce6f449a9086fc12dcd65b83b6ce8825` |
| Expanded base `assets/frozen_main.py` | 7,900 | `8f93ce3c74a2fac6d04d9f18da714101801b8d37931a99d0aa395eb3c24c82e5` |
| `reviewed-build-inputs.json` | 80,050 | `6e2d35188aadc5e00f2d6eb98e90b2f9e34f3a425c8f3575b759f52c3e38ba5c` |
| Expanded RSI `assets/frozen_main.py` | 8,333 | `e1285d5a8308209067630e9135d828737019b30533701ea86efe859b6461b7f6` |
| RSI source-plan manifest | 6,706 | `bd95a2c120821d5ff4b72cae740e3abc85ee747881c13aa43ffddd9bd4197175` |
| `reviewed-profile-overlay.json` | 2,456 | `91d808742d567a79b2deca48e977fd696771904e0c6c059a94ffa4274ea599e8` |
| RSI profile-preparation wire | 73,802 | `8c37a447238682e05b43ba5fd2463e3c136805161794eec2570b146e1d791389` |
| Current nine-source AST observation | 3,636 | `bbec89a8aec4c354c3f8556ef0be07b2725b668489e23531855cb75ae9868497` |

The previous RSI expanded-main identity was 7,227 bytes /
`2b30f4463db471419df601a0c7640a560d2be95aed08d69cdf0e8e10d6871d28`;
its source-plan identity was 6,706 bytes /
`2b95d9d77a875245361ff0aa20d6a98f29034f5d0b33a03b143f3d55786dbb6a`;
the overlay identity was 2,456 bytes /
`93a33ee5b753f7d64705adcedb1938b0f887b177348b091ed037c318eef938f0`;
and profile-preparation identity was 73,802 bytes /
`f507b275e2be088287d1e46b341c8aee7e9dd89102cace481641e491c4d0c98e`.
These are candidate source/metadata identities, never installed image pins.

The finite pin refresh updates the base build-input policy, the RSI source
recipe's two changed source records, overlay preimage/postimage, profile
preparation, mock build-driver comparison pins and detached RSI installation
comparison pins, plus their active test assertions. The fixed nineteen builtin,
nine frozen and twenty-two startup-module names, two aliases, path/config
profile, fixed marker protocol and observation schema are unchanged. The RSI
marker wrapper continues to call only the existing baseline case.

## Historical and current source audits

`tests/fixtures/static_python_source/Lunar/frozen_main-before-codec-negative.py.source`
retains the exact old expanded 6,794-byte source. The historical prepared-source
and startup-scope graph tests now read those bytes directly. The v1 graph,
old AST observation digest, old source pins and old unsupported-site line 68
remain unchanged; they describe the old candidate.

The separate `candidate-codec-negative-source-imports.json` records a fresh
bounded AST observation of all nine current prepared Python sources. The new
focused test reproduces its exact wire bytes and independently checks the
current expanded-main size/digest, all twenty-eight imports, zero unresolved
imports and all four unsupported sites. No import edge or module inventory was
added. The fixed `__import__` negative site moves from line 68 to line 94 after
the helper insertion. The active single-current-main audit follows that new
line; the historical graph does not. Both old and new observations keep every
claim false. This scan does not resolve configured table membership, deferred
reachability, codec registry initialization or target runtime behavior.

## Focused validation

The new focused file contains twenty-two synthetic/source-only cases. Existing
fixed CI groups retain their counts: build-input preparation 100, source-import
and startup audit 107, observation encoder 43, RSI launch/source plan 82, RSI
profile preparation 113 and detached RSI installation contract 189. The new
file can be guarded separately at twenty-two cases with zero skips; it must not
replace or lower any existing gate.

Final integration passes 1,032 distinct cases with zero failures, errors or
skips, adding the complete-copy 54 and regression-runner 204 selections to the
774-case codec/source/profile/observation set. The separate 22-case selection
also passes the exact new workflow XML guard; it overlaps the combined suite.
Independent review's 69 cases likewise overlap. Whole-repository Ruff,
src/tools/tests compileall and diff checks pass. Evidence is retained under
ignored `feature189-20261024/codec-final-*/` in this worktree.

The fourteen directly affected focused files pass 595 cases with zero failures,
errors or skips. The separate 107-case source-import/startup group and 74-case
observation-policy group also pass. Their startup-scope cases overlap the
595-case group; these are grouped validation counts, not a distinct-case sum.
The first focused runs exposed stale active candidate SHA and dynamic-site
line assertions; those expectations were corrected to the new source. Historical
assertions and the old-main rejection vector were retained. Repository Ruff,
`compileall` over `src tools tests`, and `git diff --check` pass.

The existing RSI launcher tests compile a bounded repository-owned argv probe
against a fake `Python.h` and fake runtime. That fixture is not CPython or the
candidate target. No CPython configure/freezer/compiler/link, archived member,
solver, remote evaluator or target runtime was executed. Actual immutable
custody and G2/G3 acceptance remain open.

## First Linux focused attempt and source-invariance refusal

The one provider-free Linux run of exact commit
`83c1d88dd86cdf98138646abea6d3ed56fa2581b` reports 774 tests, zero
failures/errors/skips and 21.697 XML seconds. All 236 loaded Lunar/tools modules
match their source records. All 2,332 original tracked source files retain their
bytes, full modes and executable bits. The overall gate nevertheless **fails**:
three `.pyc` files and one `__pycache__` directory were added to the source tree.
Both the original tree and additions are retained; this source was not rerun.

The CLI test with a replaced minimal environment drops inherited
`PYTHONDONTWRITEBYTECODE`, consistent with those additions. The three CLI argv
lists now pass `-B` explicitly, keeping the minimal environment, original
assertions and full-tree invariance requirement. Local launch51 plus codec22
passes all 73 cases without skips. The new-commit Linux run below subsequently
passes the complete source-invariance gate.

The original collector asserted source invariance before persisting the child
`Popen.returncode`. That raw child status is unknown. The recorded pytest plugin
session status is 0 and collector status is 1; neither is substituted for the
missing child receipt. The replacement collector must persist raw process
status and complete before/after inventories before evaluating any gate.

All 17 returned artifacts match their manifest SHA-256. The ignored local
package is
`.lunar-evolution/feature189-codec-linux-evidence/83c1d88dd86c-l2c_8b69/`.
Its artifact manifest SHA-256 is
`a970b3601c3accc4e4addab9ded3d8f0829e8d74056a3a0bff93e84775111491`;
summary SHA-256 is
`363554763e87f209f5b7361cff0cbc506526a8d649a570648156943afa458c23`;
XML SHA-256 is
`679d1fb5c4b41c842be5c16d0403d9c2afb0254e717f1a74eed6462dac59b0ff`.

## New-commit Linux focused acceptance

Exact `de9bd3873ccc56bfa124e87db0dc495a084de7b7` ran the same 774 tests
once on Linux Python3.11.15. All pass, with zero errors/skips, 22.331 XML seconds
and 22.664091 monotonic subprocess seconds. The raw process returncode0 was
persisted with flush/fsync before the source-after, XML and module gates.
All 2,333 source files retain bytes, full modes and executable bits; complete
directory/file inventories are identical, with no additions. All 236 final
session Lunar/tools module origins match the exact source index. This establishes
the focused provider-free gate, not static target or production acceptance.

The 17 transferred artifacts match their indexed sizes/SHA-256. An independent
root review also compares `source.tar` byte-for-byte with exact `git archive`,
every archived/indexed source file, both inventories, 235 file-module records
plus one namespace, 774 unique testcases, and the separate raw process receipt.
No collector error or missing receipt is recorded. The previous83c FAIL and
its retained source additions remain unchanged.

The ignored package is
`.lunar-evolution/feature189-codec-linux-evidence/de9bd3873ccc-yuz1s8yp/`.

| Evidence | SHA-256 |
| --- | --- |
| Git archive (26,849,280 bytes) | `60d58eaa1d7847aa5a7629c2999c565516d24cf3f6b9c01b92b9e064add4ba67` |
| Artifact manifest | `eacdec73b4b2bf77d9a8697e24d6f9e646e07eed2256c4cc85845c492d2b0361` |
| Summary | `8a353953479b75128740ac40899ba60570531171688b7d3ce3a9bc4485e210ab` |
| Raw process result | `212b056a03f86cc149ec9fff118296a4883bb4dd0bef3e5e2900256c52c2f519` |
| Results XML | `f6b7180b95c6a4b5464e8eecdf4c56a69307bc780c2fc8d2c8f65d1098bcf0e8` |
| Source before and after (identical) | `3325ceea85db17dd294047aa314e113ae2730e602b651e0dbfa3e147423307ac` |
| Root independent review | `2ea2efea0e526611214f0e7ea306b6aee459d15c1502a54193bda2a641473ccc` |

No real CPython configure/build/freezer, target, solver or evaluator runs.
Immutable custody, configured consumption, ELF and G2/G3 remain open.
