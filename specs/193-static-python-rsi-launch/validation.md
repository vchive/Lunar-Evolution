# Feature 193 validation

## Cross-contract validation corrections — 2026-10-12

F03 fixed native argv/marker/entrypoint and executable/lifecycle agreement,
F04 exact integer sizes, and F05 exact count/time types, precision, independently
pinned state and unknown cleanup gates pass 79 focused cases. Three initial
test-oracle mismatches were retained and corrected without validation changes.
Adding 280 disjoint existing build/source/report cases gives 359 unique passes,
zero failures/errors/skips on Python3.13.12. Independent review replays the same
79 cases with no blocker. Whole-source Ruff, compileall and diff-check pass.
Completion metadata and XML are retained create-only in ignored
`.lunar-evolution/reports/contract-validation-20261012/`. JUnit SHA256:
`0dcebcfd1f18f3c2dd1f1874404aeb4f54fc91af04b6d314ceb6ced5f13909c0`.
The compatibility run emitted pre-existing macOS pytest cleanup warnings.

F05 callers must now supply three separately retained state pins. There are no
existing production callers of this unpublished detached parser. F03 historical
synthetic `--fixture`/`LUNAR_RSI_INPUT`/alternate-entrypoint descriptions now
refuse instead of diverging from the reviewed C launcher. Old Feature189/193
assets/profile/native intent wire are unchanged. No real sealed runtime,
installation, input consumption or publication is accepted. The final committed
source still needs its own CI and independent raw/source/tree audit.

Status: stage 1 local verification complete; final-source CI/audit pending. All cases use local
inert fixtures, fake C APIs or fake Python runtime facts. No CPython/toolchain
acquisition/build, static image launch, input consumption or producer admission
is established by this plan.

## Detached installation contract continuation — 2026-10-12

The separate F01 wrapper binds six mandatory independent comparison pins, fixed
reviewed marker/source-plan/overlay/launcher descriptions, complete nine frozen
sources and generated-header records, original initialization and false claims.
The unchanged original parser validates embedded canonical descriptor bytes.
No tools/profile imports or filesystem/network/process/runtime effects occur.
Actual source-to-object/header correspondence and accepted installation remain
unverified; matching synthetic metadata pins cannot establish those facts.

Root Python3.11 passes189 focused plus515 disjoint compatibility cases,704 unique
passing cases with zero failures/errors/skips. Compatibility covers original
build inputs/installation, RSI preparation/launch/source-plan and input report.
Root inventories actual JUnit case identities and all27 baseline files remain
unchanged. Independent Python3.13.12 replay passes the same189 cases with final
source/test hashes unchanged, not an additional189 unique passes. Independent
source reviews verify nine literal freeze-task projections, exact launcher and
base/overlay/source-plan records; test review verifies independent synthetic
fixtures and retained external-pin mismatch oracles. Whole-source Ruff,
compileall and diff checks pass. The retained189-case focused gate is separate
from the existing focused shell body, which remains byte-identical.

Source pins:

- `src/lunar_evolution/static_python_rsi_installation.py`:12873 bytes,
  SHA256 `6d28b8f5d071e7ae777ad96fc4b23d6bf780b18284c2a54f16cf6a665d95697c`.
- `tests/test_static_python_rsi_installation_contract.py`:25208 bytes,
  SHA256 `795b897f1aa2226022369b16e80fcd405c31323a9af61921a84806c93115a9e1`.

Ignored main-workspace reports directory
`rsi-installation-contract-1791748409946671000` retains baseline-pins,
compatibility/root-final-inventory, root-focused-final XML, independent first/
second/third/fourth reports and final independent-py313 completion/XML/log.
Initial alias/enum test-oracle failures are not replaced by the passing evidence;
the product source did not change to accommodate them. Independent source review
also retained `f01-installation-independent-source-review-1791748797420408000`.
This source starts from PR52 final8d44efd and requires its own complete CI plus
raw/source/tree audit and dependency-order merge. Actual F01–F06 and P2 status
are unchanged.

## Recorded local results — 2026-10-12

Python 3.11 focused tests passed 82 cases (51 launcher/wrapper, 31 source plan),
with zero failures/errors/skips. The local C compiler compiled and executed only
inert Python API stubs. The real reviewed encoder body was exercised using a
closed fake import map through the wrapper, detached DTO adapter and observation
comparison; these are simulated runtime facts. The four existing build/source/
observation modules passed 133 disjoint compatibility cases. Root parsed both
JUnit files, checked unique case IDs and verified 215 unique passing cases.
Ruff, compileall and diff checks passed. Earlier test setup/assertion failures
remain retained and are not substituted for final results.

Evidence under ignored `.lunar-evolution/reports` in the main workspace:

- `static-python-rsi-launch-tests-completion-20261012/completion-v3.json`
- `static-python-rsi-launch-focused-final-v3-20261012.xml`
- `static-python-rsi-launch-20261012/compatibility.xml`
- `static-python-rsi-launch-20261012/root-local-inventory-v3.json`

The emitter verifies 11 independent input pins before output, snapshots literal
profile assignments without executing the profile, writes six sources plus one
manifest create-only and checks all output bytes. File mode uses the opened file
descriptor. Common Feature189 assets and initialization vectors remain unchanged.
The baseline encoder stays an exact expanded prefix of the new frozen source.
The new manifest has nine false capability claims. A syntactically valid digest,
including all-zero or all-f lowercase hex, is not evidence of input identity.
Concurrent hostile filesystem replacement is not an atomic snapshot or ownership
guarantee provided by this local source emitter.

Independent Python 3.13.12 replay passed the same 82 unique cases in 2.459
seconds, zero failures/errors/skips, with all seven source/test hashes unchanged.
Eleven source pins and nine old inputs were independently verified. Its retained
report is `static-python-rsi-launch-independent-py313-20261011T184509747196Z`,
completion SHA256 `15bb1d3806acc93eae3c1f2d78ede2186202a4f6d70fdbbda0b12e9952ee9a1f`.
A separate read-only review verified 683 existing source/test/tool files against
PR49 Git blobs and mode, and reviewed fixed launcher/wrapper semantics without
rerunning the suite: `feature193-independent-source-review-final-1791744244972180000`.
This replay is not an additional 82 unique cases. The CI gate requires all 82 selected cases with no skip and retains/annotates its own XML.
Complete three-version final-source CI and raw/source/tree audit remain pending;
source preparation does not admit any installation or worker.

## Source pins and output

Verify every reviewed source dependency against independently supplied expected
size and SHA256. Mutate each source category independently and demonstrate
refusal before output creation. Do not compute an expected pin from the mutated
input under test. Include missing/extra source shape and bounded/invalid version
cases according to the final public API.

Run preparation twice in separate fresh local destinations. The six asset bytes,
manifest source/profile/launch facts and recorded hashes must be deterministic.
Check the exact output set and all payloads by independent readback. Existing
destinations, substituted payloads, short writes and readback drift must refuse;
partial output must never yield a completed preparation result. Verify API and
CLI enforce the same source-pin/create-only/readback rules.

Independently check that the output contains only six source assets plus its
source manifest. It must contain no executable build/configure/freezer driver,
artifact, generated bytecode/header or accepted installation/build-input record.
Configured/build/runtime/installation/input-consumption/production-admission
claims and runtime-load/general-origin protection must all remain false.

## Launcher and frozen wrapper

Exercise the reviewed C source through inert Python API stubs where a local test
compiler is available; it must not link or initialize CPython. Invalid argc,
missing/wrong/duplicated/reordered marker, trailing arguments and malformed,
uppercase, short/long digest inputs refuse before any Python initialization or
call. For a valid input, require the fixed module/callable and exact digest passed
once, retaining initialization/finalization error handling. Verify no environment
selector is consulted and no OS metadata modifies either fixed PyConfig vector.
Label any platform/compiler skip explicitly; a skip is not runtime acceptance.

Exercise `_rsi_launch` with independently supplied fake sys/loader/pipe facts and
the real baseline encoder body. Reject non-string objects and string subclasses,
wrong lengths, whitespace, uppercase and non-hexadecimal input before baseline
or broker effects. Valid lowercase digest input delegates once to baseline and
retains the existing fixed computation and wire. Guard input-file/environment
read routes so an accidental new read is a failure; no staged inputs are needed
for wrapper success.

Compare the old encoder body and common asset source bytes with the frozen
baseline. The new wrapper cannot change baseline observation semantics, add an
RSI result envelope or imply that the digest names consumed input bytes.

## Compatibility and final evidence

Freeze old Feature 189 asset/profile/recipe/reviewed-build-input/parser hashes
before editing and verify them unchanged afterward. Run the relevant existing
static source/profile and runtime-observation focused tests. Keep native marker
validation, broker/v2/frame wires and the existing two request/memory grants
unchanged. Do not fabricate a live marker/native-input success from source text,
fake API traces or the fixed encoder observation.

After each implementation change, run its focused tests, Ruff, compileall and
`git diff --check`. Final validation records must include actual test selection,
interpreter, unique case count, failures/errors/skips, final source hashes and
source-preparation pins. Retain first failed evidence separately. Repeated or
overlapping verification is not an additional unique pass count.

Before merge, run this source's complete CI and independently verify retained
raw metadata/JUnit artifacts against the exact commit/tree and selected case IDs.
CI source collection and local fake tests do not establish a built/runtime image.
Do not copy an earlier source's approval or count pending CI as passed.

## Acceptance still required after stage 1

Independent new installation/profile acceptance, matching source/toolchain and
static artifact closure, actual image startup/loader-negative/owner/native
lifecycle, authoritative input binding and real consumption, producer result/
post-execution handoff, interruption recovery and local solver/production CLI
acceptance remain unverified. These later stages stay unchecked in `tasks.md` and
must receive their own contracts and evidence before any claim is promoted.

## F03 provider-free startup wire — 2026-10-12

The detached `static_python_runtime_startup` comparator and its 12 focused
tests validate canonical JSON, exact pins, baseline and loader-negative fixture
semantics, argv/marker/startup/owner/lifecycle shape, dependency ordering,
false claims, parser error normalization, bounds and side-effect absence. The
tests use synthetic caller bytes only; no process, ELF parser, filesystem or
`/proc` operation ran. Ruff, compileall and `git diff --check` are required
before submission. This is a contract slice, not actual startup, loader,
owner, native lifecycle or installation evidence; F03 runtime acceptance stays
open.

## F01 source-only profile preparation continuation — 2026-10-12

Python3.11 new focused module passes 113 cases; disjoint old build-input and
installation modules pass 101 and disjoint stage-1 marker/source-plan modules
pass 82. Root confirms 296 unique cases across the three JUnit files, zero
failures/errors/skips. This count does not include repeated or overlapping runs.
Create-only root inventory is `rsi-profile-root-local-inventory-1791745186327988000`,
completion SHA256 `ac92787e0317a6dc36c3e3970ee9904fe1a592371be740518b24396ffcc8c2fe`.
New focused completion is `static-python-rsi-installation-profile-tests-completion-20261012/completion-v1.json`,
SHA256 `2e9d3d3275bcb2db752641fb160395e3ce8bd685fa9f527001824831729a7162`.
Independent semantic/pin review has no blocker:
`rsi-profile-independent-semantic-review-1791744992735051000/completion.json`,
SHA256 `61bdaf179576e134e95ac53670dd5b1840f9e76278f0656529728889b5e9094c`.
Its earlier environment preparation failure is retained separately.

This API has no filesystem/process/network/environment/clock access. All caller
buffers/map/key/value types are exact built-ins before hashing or parsing; a
private dict snapshot prevents later caller map replacement. All six supplied
payloads match fixed source-plan records. Only complete launcher and main-freezer
records change; the 162 shared, two freezer and four target units, nine freeze
tasks, generated sources and other headers retain their original content. All
nine output headers are pending with no generated digest. A separate candidate
schema is refused by old accepted parsers; nine claims remain false. The old
Feature189/193 inputs and parser semantics are unchanged. Final-source CI/audit
remains required; no configured/build/runtime/accepted installation is claimed.

Independent Python3.13.12 replay passes the same 113 focused cases with zero
failures/errors/skips and eight source/test/dependency hashes unchanged. Its
create-only report is `static-python-rsi-profile-independent-py313-20261011T185949854237Z`,
completion SHA256 `07148aba89b5329db116fd391421d0ffc2b59ea05ecf59fa871a1a9d703477f1`;
JUnit SHA256 `76286b9d78ef7842d001912e3f2c6932da9a5eea7d0a6f34779e886eb96b9683`.
Repeated replay is not an additional 113 unique tests. Whole `src/tests/tools`
Ruff and compileall pass, as do diff checks and YAML/gate annotation/upload wiring.

## F04 source/mock two-input report continuation — 2026-10-12

The separate uninstalled source prototype reads only request and memory grants,
using exact fixed binary paths and131073-byte reads; it refuses invalid marker
metadata before opening either input and refuses empty/oversized/nonbytes reads.
It returns canonical ASCII hex fields after both reads and fixed computation285,
with five false claims. The pure comparator checks independently supplied caller
bytes and marker and returns only digests/sizes. It never reads retained input
files or descriptors, creates a result envelope, or grants evidence authority.
Malformed JSON/Unicode/depth errors are normalized outside the exception handler
so parser cause/context does not retain raw input; completion records must still
exclude traceback locals and the raw report. Existing accepted profile/emitter/
frozen inventories and pins are unchanged.

Root Python3.11 verification passes219 new focused and195 disjoint compatibility
cases,414 unique passes, zero failures/errors/skips. The compatibility selection
is the previous113-case profile plus82-case marker/source-plan modules. The
create-only report `static-python-rsi-input-report-root-20261012/completion.json`
has SHA256 `e5766f3f7742b18ec7a52b0ef273cdd480bdc8d697b2962d40450e7c7b0a221a`.
Source/test hashes were identical before and after the focused run. An earlier
pytest console invocation lacked the tools namespace and had45 passes/174 setup
errors; the corrected `python -m pytest` invocation passes without product fixes.
Both original logs remain retained separately; repeated219-case runs are not
additional unique cases. No raw input report is retained in completion evidence.

The219-case CI gate retains/annotates its own XML. Complete final-source CI and
independent raw/source/tree audit remain pending. Live F04, accepted installation,
actual build/sealed runtime, original terminal/capture/materialization binding,
solver envelope/publication and production CLI/Linux acceptance remain open.
Only inert/mock fixtures ran; `production_admission=false`.

## F02 pure build-closure comparison — 2026-10-12

`tests/test_static_python_build_closure.py` passes 10 focused synthetic cases.
The new comparator validates exact canonical wire shape, independent source,
toolchain, frozen-inventory, link-manifest and artifact pins, nine frozen header
slots, duplicate/forbidden link records, ELF loader-negative fields, false
claims and F01 cross-field agreement. It returns only an immutable DTO. Tests
monkeypatch filesystem/process APIs to confirm no external effects. Ruff,
compileall and `git diff --check` pass for the changed files.

This is not a configured build or artifact result. No compiler, freezer, linker,
ELF parser, source acquisition or executable ran. F02c remains open until a
controlled build produces independently audited source/tree, toolchain,
generated-header, object/archive, link-map and final ELF byte evidence.

Independent Python3.13 replay passes the same219 cases with zero failures/errors/
skips and unchanged API/asset/test/package hashes. Its create-only completion is
`static-python-rsi-input-report-independent-py313-20261011T192213737063Z/completion.json`,
SHA256 `d6d0e10054a1a4b629047a6e47c6d6e3f5e04c54ecdbbff5b9fb46eab7691491`;
semantic review SHA256 `314b2b9581abb0c8c6d8a00fc10e81c330932d1c19dfcd22bb857359cae57c25`.
Independent replay is not an additional219 unique cases. Whole src/tests/tools
Ruff, compileall, diff checks and YAML gate/annotation/upload wiring pass.

## F04 provider-free input/result cross-pin continuation — 2026-10-12

`static_python_input_result` joins independently supplied F03 startup and F04
input-report digests, sizes, fixed computation and report schema through the
`lunar-static-python-input-result-v1` wire. It enforces canonical JSON,
duplicate-key/type/bounds checks, exact cross-pins and five false claims, then
returns only an immutable digest/size DTO. The comparator performs no file,
process, environment, network, clock, solver or evaluator operation. Its focused
suite passes 9 local synthetic cases; this does not establish input ownership,
actual consumption, runtime startup, output validity, producer admission or a
solver result. Final-source CI and independent raw/source/tree audit remain
pending; live F04 and later F05 acceptance are unchanged.

## F05 provider-free runtime/post-execution handoff continuation — 2026-10-12

`static_python_runtime_handoff` validates the bounded canonical
`lunar-static-python-runtime-handoff-v1` projection against independently
supplied startup, input/result, terminal, binding, launch-intent, result and
publication-intent digests. It also checks request budget/count, wall timeout,
Unix deadline, terminal/cleanup/publication state combinations, duplicate keys,
canonical bytes, bounds and all-false capability claims. The parser returns only
an immutable digest/state DTO and has no filesystem, process, clock, network,
solver, evaluator, publication or recovery effects.

The focused F05 suite passes 10 cases; the adjacent F04 input/result contract
passes 9 cases in the same run, for 19 unique local cases with zero failures,
errors or skips. Ruff, compileall and `git diff --check` pass on the final tree.
This is a provider-free consistency contract: it does not establish CPython or
ELF build evidence, sealed launch, original owner/lifecycle, authoritative input
consumption, a bounded producer result, publication eligibility or durable
interruption recovery. The complete local `tests/test_static_python*.py` selection collected and
passed 1,395 cases with exit code zero after this continuation. macOS pytest
cleanup emitted permission/directory-not-empty warnings for existing protected
fixture snapshots; no test failure or product exception occurred.
Final-source CI and independent raw/source/tree audit remain pending.
