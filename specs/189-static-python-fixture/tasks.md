# Tasks — bounded static installation and fixture

Unchecked boxes are future deliverables, not work already completed by
171/177/184/188. Preserve the source of every first build/startup/test
failure and cancelled preflight separately from later successful evidence.

## G0 prerequisite

- [x] Confirm Feature188 final exact source/head/tree, Linux dedicated no-skip
  acceptance, raw artifacts independent audit and main merge. Record references.
- [ ] Review/freeze this bounded189 SDD and installation descriptor field/bound
  contract. Confirm no new v2 FD, general solver adapter or production admission.

## G1 installation inputs and pure admission

- [x] Specify the bounded archive-receipt and extraction-manifest preparation
  contract in `verified-inputs.md`; keep advertised pins and caller-supplied
  metadata separate from observed archive/signature/toolchain evidence.
- [x] Implement and locally validate the pure archive-receipt/extraction-manifest
  validator with inert fixtures. It performs no acquisition, extraction, build,
  filesystem traversal or signature verification; passing it does not complete
  either actual input-verification gate below.
- [x] Complete final-source three-version Linux CI and independent raw audit for
  this pure slice before main merge: run37871696368/main1e492dc, exact tested
  source4ec32b2/treeeb9f9e8e. The dedicated metadata gate requires143
  cases and zero failures/errors/skips; it is not archive or runtime acceptance.
- [x] Specify and implement the bounded local archive observation slice in
  `archive-observation.md`: held O_NOFOLLOW path/file descriptors, immutable
  compressed bytes, prechecked USTAR file/directory headers, bounded XZ and
  actual member-size/SHA manifest validation. Validate with inert local fixtures.
- [x] Complete final-source three-version Linux CI and independent raw audit
  for local archive observation before its main merge; require the dedicated
  64-case gate without failures/errors/skips. This fixture gate does not verify
  downloaded releases, release signatures, extracted staging or runtime admission.
  Accepted PR30 run37894203485/main68cb31f, source2889dc1/tree58e912d6.
- [x] Specify the snapshot-bound fixed three-source byte projection and preparation
  contract in `source-projection.md`: mandatory external canonical manifest pin,
  actual member/preimage/postimage byte bindings and one original deadline.
- [x] Implement and locally validate this projection with synthetic USTAR/XZ
  containing the existing inert source fixtures; no pathname reopen, filesystem
  extraction, source execution, build or runtime operation.
- [x] Complete final-source three-version Linux CI and independent raw/source/tree
  audit for source projection before its main merge. Preserve the existing
  64-case archive gate and keep release/signature/G1/G2/G3 claims uncompleted.
  Accepted PR31 run37896389062/mainc48d234, source31f335f/tree81b2efa3.
- [x] Specify snapshot-bound create-only complete source staging and fixed patch
  application in `source-staging.md`, with bounded implicit directories, retained
  descriptor identities, readback/inventory gates and preserved partial failures.
- [x] Implement and locally validate staging using inert USTAR/XZ fixtures only;
  one strict decode feeds complete inventory and the existing fixed patch policy.
- [x] Complete final-source three-version Linux CI and independent raw/source/tree
  audit for staging before its main merge. This does not complete downloaded
  release/signature/toolchain provenance, configured build closure or runtime gates.
- [x] Observe the complete original regular-file source tree from the same immutable
  snapshot with independent manifest/tree pins, explicit inert/profile states and
  deadline coverage. Keep the source-tree digest separate from extraction,
  projection, staging and Git object digests; this remains provenance observation,
  not acquisition or release authentication.
- [x] Verify the CPython 3.13.12 release archive size/SHA-256 and detached
  signature against the official Python signer metadata; retain the GPG status
  and raw-file digest manifest in
  `release-input-audit-20261021.md`. This closes the archive/signature portion
  of G1 only.
- [ ] Independently retain the complete acquired/extracted source-tree digest
  and exact applied patch set for the candidate build. The archive signature,
  source projection and source-tree DTOs do not themselves prove a staged,
  patched tree was used for a configured build.
- [x] Cross-check the declared Zig 0.16.0 archive digest and the byte-for-byte
  archive and available Ubuntu musl package bytes on 5090gpu; preserve their
  exact versions and hashes in `release-input-audit-20261021.md`. This cross-check
  does not assert every package participated in the prior build; no system
  packages were installed during this audit.
- [x] Add the SDD-defined provider-free source-tree/staging consistency check.
  Bind independently pinned canonical DTOs and their per-file source/patch
  postimages; do not reopen the staging directory or grant build/runtime
  acceptance. Keep the separate candidate-build-source/patch evidence task open
  until an actual configured build consumes and records that tree. The current
  check compares detached canonical DTOs only and does not itself prove either
  DTO was honestly produced.
- [x] Observe an actual real-source staged tree with the read-only staged-source
  API and retain its complete canonical staging DTO and observation record on
  5090gpu. The release profile, archive extraction manifest, fixed patch policy
  and original source-tree pins were replayed; the staging manifest digest was
  generated by the staging run itself, not independently pinned beforehand.
  Record that custody limit in `candidate-build-source-receipt.md`. This closes
  only the observer exercise: it does not establish independent archive/signature
  custody or prove that a configured build consumed the tree.
- [x] Give staging its own producer-consumer entry/path/string/wire budgets so
  implicit ancestor-directory expansion and canonical JSON escaping cannot make
  a legal staged DTO fail the pure consistency check. Keep the source-observation
  and archive-receipt 32 MiB bounds unchanged.
- [x] Add the source-only readiness receipt in `source-readiness-receipt.md`.
  Bind the archive receipt, complete original tree, patched staging tree, fixed
  five-file patch/policy digests, all six RSI source assets (including expanded
  `_lunar_static_main`) and an independently pinned Zig file inventory. Require
  explicit `unverified` toolchain evidence and false build/runtime/admission
  claims; this receipt does not close source acquisition, toolchain, build or
  runtime acceptance.
- [ ] Select one exact separately pinned musl x86_64 compiler/sysroot/libc profile;
  resolve compiler/binutils/static-library sources, versions and artifact hashes,
  including zlib/libffi/freezer inputs and the configured build environment.
- [ ] Freeze configure/cache/module/compile/link/environment recipe and provenance.
- [x] Freeze the prerequisite private original target-owner binding and independent
  Feature190 fixture proof: final run37802795693/main merge3a7782c. Feature189's
  actual target-owner integration remains a G3 gate.
- [x] Implement bounded pure descriptor/parser/external-pin validation with focused
  invalid shapes/collections/digest/count/unknown-field tests; no build/FS effects.
- [x] Freeze `startup-closure-contract.md` and implement its separate bounded
  canonical import-graph DTO parser. Version 2 separates the descriptor-pinned
  expected startup-module inventory from a separately hashed root vector, requires
  exact module/alias records, and checks graph reachability from those roots. Its
  65-case focused suite (including the pinned-root composition check) proves
  DTO consistency only; the synthetic graph edges remain synthetic and do not
  establish source closure. The synthetic
  root vector is not claimed to be the real CPython startup roots.
- [x] Derive and retain the source-level primary root vector from the pinned
  CPython C startup sources and fixed Lunar launcher. Its independent canonical
  hash is `d1743e729bac34c5110a1d1373cc48c74a52b585034825227ed37d0178e39313`;
  the source sites and limitations are in `startup-root-audit-20261022.md`.
  This closes root derivation only, not the graph audit or runtime evidence.
- [ ] Independently complete the C/Python import-edge audit for the configured
  source/startup scope, then exercise the v2 comparator with the source-derived
  root hash and an independently retained graph. Do not claim source or
  configured closure from synthetic DTO results.
- [x] Specify and implement the separate source-byte-bound Python AST import
  observer in `python-import-audit-contract.md`. Require exact caller-supplied
  module/source bytes and matching external per-source SHA-256 pins; record
  ordinary/from/relative/literal observations plus fixed unresolved/unsupported
  sites under finite budgets. Keep output claims false and do not compare or extend
  the installation profile. Synthetic tests prove only observer behavior; they do
  not establish source provenance or complete import enumeration.
- [x] Record a read-only AST review of eight frozen-module Python files directly
  from the pinned CPython 3.13.12 release archive, including the archive identity,
  changed staged-source paths and bounded import observations in
  `authenticated-source-import-audit-20261021.md`. This is a partial source audit,
  not a complete import closure or independent re-verification of the signature.
- [x] Replay those eight exact release-archive member bytes through the Lunar AST
  observer without extracting or executing them. Preserve the canonical result
  digest, per-source observations and fixed unsupported sites; the call-time
  source pins were computed from the bytes and are not independent release pins.
- [x] Emit the exact expanded Lunar `_lunar_static_main` source from the reviewed
  build plan, match its size/digest to the freeze-task pin, and run that byte
  string through the Lunar AST observer. Keep the fixed loader-negative dynamic
  import visible as unsupported; this is a source-plan check, not a freezer or
  startup observation.
- [x] Record a bounded, source-pinned CPython C-startup review for the fixed
  import/lifecycle/configuration/table inputs, distinguishing stock archive
  files from generated Lunar tables and fixture-owned path code in
  `c-startup-source-audit-20261021.md`. This does not complete the configured
  C/Python closure or runtime audit below.
- [x] Cross-check the single pinned `codecs → _codecs` source edge against the
  synthetic candidate descriptor in `codecs-edge-audit-20261023.md`. Preserve
  the generic observer's `star-import` unsupported result. This does not review
  the complete C implementation or prove builtin-table/link membership.
- [x] Retain exact archive `_codecsmodule.c` and `Setup.bootstrap.in` members
  as inert fixtures and check their declared module/initializer and bootstrap
  source line against the synthetic `_codecs` entry, including consistency
  with Lunar's emitted candidate table/source/object plan. The bootstrap file
  is a template. Pin its direct include spellings and Windows guard while
  leaving header resolution/bytes, configured consumption, compilation,
  linking and runtime origin open.
- [x] Project the fixed 28 prepared-source AST edges onto the synthetic frozen
  and builtin name inventories with exact-name membership results. Preserve
  absent targets as inventory observations only; do not infer reachability,
  platform safety, refusal, or closure.
- [x] Pin the `Modules/_io/_iomodule.c` archive member and cross-check its
  `_io`/`PyInit__io` declaration against the upstream Setup template, explicit
  candidate source/object plan, AST edge and source-derived `io` startup root.
  This is bounded source/metadata consistency, not compilation or runtime proof.
- [x] Retain exact archive `Modules/_abc.c` bytes as an inert fixture and
  cross-check its `_abc`/`PyInit__abc` declaration against the Setup template,
  Lunar's candidate emitted table/source/object plan, and the synthetic
  descriptor in `abc-c-source-audit-20261023.md`. This source-only check does not
  establish configured consumption, compilation, linking, ELF contents, or
  runtime module origin.
- [x] Define bounded source-preparation dispositions for the observed dynamic
  codec-name selection and `_py_abc` fallback: direct fixed UTF-8 binding, a
  six-alias allowlist, and preservation of the original `_abc` import error.
  Provider-free tests cover the source transformations and normal `LookupError`
  from host `codecs.lookup` when the synthetic callback declines an unknown
  codec. This does not verify target startup registration or frozen-module use.
- [ ] Independently audit CPython 3.13.12 source imports and startup edges, including
  relative/literal imports, bootstrap aliases, C-created builtins and dynamic-import
  refusal sites across the complete configured source/startup scope, including
  any dependency outside the pinned profile and a versioned profile decision.
  The bounded importlib bootstrap/loader review in
  `importlib-edge-audit-20261022.md` records the `_frozen_importlib` startup edge
  and candidate loader dispositions, but leaves deferred direct resource-reader/
  metadata routes and configured/runtime binding unresolved. The DTO parser
  cannot certify the full audit or infer new modules.

The offline source-preparation contract in `source-preparation.md` covers pure
exact preimage/snippet/postimage gates and finite table-source assets. These do
not check the remaining acquisition, toolchain, generated bytecode, compile/link
or startup gates below.
The `verified-inputs.md` slice checks only bounded supplied receipt and member
metadata. A complete-looking receipt cannot be used as a machine acquisition,
safe-extraction or signature-verification result.

## G2 fixed image and complete startup closure

- [x] Specify the fixed candidate build-input preparation in `build-inputs.md`:
  separate shared/core/builtin, freezer/target plans, nine adjacent header paths
  and unresolved configured/static-link inputs. This is not actual build closure.
- [x] Implement and locally validate pure fixed build-input emission and bounded
  known-escape recipe refusal with inert fixtures; the parser is not a compiler
  allowlist and does not authorize configure/make/freezer execution.
- [x] Complete final-source three-version Linux CI and independent raw audit
  for the build-input slice before main merge; require the dedicated90-case
  source-only gate and source-preparation100-case gate without failures/errors/skips.
  Accepted PR29 run37894037150/maincce8e892, sourcece606690/tree6812af8f.
- [ ] Audit actual3.13.12 C headers, all path outputs and frozen-use flags/API;
  freeze fixed isolated preconfig/config including UTF-8 and locale dispositions.
- [ ] Close all encodings/importlib/stdio/startup dependencies and stock frozen,
  alias, separate embedded startup arrays and static inittab dispositions. Replace
  the seed with an exact finite
  reviewed inventory; no automatic acceptance of discovered extra modules.
- [ ] Implement the tiny static pipe builtin and one fixed inert frozen main with
  real computation/runtime observations and predefined bounded negative cases.
- [ ] Implement/refuse installed file/zip/dynamic-extension fallback routes; audit
  needed bootstrap_external code and unsupported codec behavior.
- [ ] Build matching pinned freezing tools and static target; retain first compiler,
  linker and startup failures. Record every input/generated table/digest/link map.
- [ ] Independently inspect final ELF/source/table/configuration/provenance and
  publish actual installation descriptor and expected image pins. No PT_INTERP /
  DT_NEEDED, missing input hash, placeholder inventory or host runtime substitute.
- [ ] Reject final images larger than 128 MiB/134217728 bytes under the existing
  producer-launch/executable-binding ceiling; no increase or temporary bypass.

## G3 exact sealed-target fixture and acceptance

- [ ] Validate original pins and use existing executable sealing/guardian/v2 target
  FD with no new inherited FD or host Python exec/runtime roots.
- [ ] Observe real CPython3.13.12/cache_tag/flags, startup without host stdlib,
  fixed frozen computation, pipe request/response and absence of pyc.
- [ ] Verify readable decoys, unknown codec/module and loader refusals, original
  source/image pin drift, post-seal source replacement and exact inherited FD census.
- [ ] Verify ready/release/start/terminal, inherited pipe ownership, deadline,
  cancellation, guardian interruption, process reap and FD cleanup on every path.
- [ ] Independently validate the selected private target owner's original binding
  and cleanup/recovery against closed/reused numbers, same-byte foreign objects,
  forced observation mutation and interrupted acquisition/release. No private
  API is assumed and no public numeric FD may authorize foreign-object close.
- [ ] Run focused/static/current/archive/frozen regressions and exact final Linux
  dedicated gate with zero skips. Preserve raw ZIP/log/XML/source/toolchain/image
  evidence; require independent final audit before main merge or any completed claim.

## Explicitly later

- [ ] Separate SDD for188 framed bundle delivery/importer, extra native FD/version,
  C seal/frame/pin checks and generic project-runtime closure.
- [ ] Separate production Python admission, SDK freezing, real solver adapters and
  local RSI composition. No campaign is authorized by this fixture acceptance.

## Unknowns to resolve with source review or actual build fixtures

The selected toolchain candidate is pinned Zig0.16.0 Linux x86_64 with bundled
musl1.2.5 plus backports/Zig-libc replacements; no static artifact exists. Actual
required core/bootstrap modules/codecs, minimal bootstrap_external disposition,
frozen-generator build sequence/compatibility, configure/autodetection removals,
static dependency/symbol closure, PyConfig field values and startup behavior are
not observed. Build reproducibility, image size/digest, final inventory counts,
seccomp/landlock interaction and Linux lifecycle timing remain unknown. Resolve
these as explicit gates; do not turn expected behavior into observed evidence.

## Receipt/source-tree consistency continuation

- [x] Add the pure preparation comparator using original archive-receipt-v1,
  independent receipt/manifest/tree pins, complete observation/tree canonical
  consistency and frozen file DTOs; preserve signature declarations separately.
- [x] Run local focused/refusal/container and related fixture tests, Ruff,
  compileall and diff checks. Synthetic matching metadata is not G1 evidence.
- [x] Complete this final source's own three-version CI and independent raw audit
  before merge: PR39 run38049495417, sourceedbe903/tree0df4149, merged into main
  at89ce5716ca86d6bbdba9fefd751d614a12df1baf. Actual release acquisition/signature,
  G2 build and G3 runtime acceptance remain unchecked.

## Staged-source observation continuation

- [x] Add read-only observation of a staged source tree using separately supplied
  staging, patch-set and original-source-tree digests; keep the result explicitly
  detached from build consumption and production admission.
- [x] Bind every patched staged entry to the exact fixed preimage/postimage and
  sizes, and require unpatched source/staged digests to match before observing
  filesystem bytes.
- [x] Check the staging destination's direct child inventory and every manifest
  directory with deadline-aware bounded scans; close every acquired path
  descriptor on verification failure.
- [x] Cover successful no-mutation observation, content/mode drift, missing and
  extra entries, symlinks, forged postimages, extra destination siblings,
  deadline expiry and descriptor cleanup with local fixtures; Ruff, compileall
  and diff checks pass.
- [x] Run the observer on a newly staged real CPython 3.13.12 source tree and
  retain its complete canonical staging DTO and observation record on 5090gpu;
  see `candidate-build-source-receipt.md` (2026-10-22). The staging digest was
  generated during that staging run, and the evidence remains on a remote
  disposable host rather than independently custodied here. This completes the
  observer exercise only; independent archive/signature custody and configured-
  build consumption remain open gates.

## Core `_warnings` source audit continuation

- [x] Retain the exact pinned CPython 3.13.12 `Python/_warnings.c` archive
  member and `Modules/Setup.stdlib.in` template as inert fixtures with
  provenance; confirm `_warnings` has no `Setup.bootstrap.in` or
  `Setup.stdlib.in` declaration.
- [x] Check `MODULE_NAME`, module definition and `_PyWarnings_Init`/`PyModuleDef_Init`
  against the Lunar emitted initializer table, `LUNAR_CORE_BUILTIN_SOURCES`,
  and the synthetic installation descriptor. Keep it in the core source list,
  outside `LUNAR_STATIC_MODULE_SOURCES`.
- [x] Record the conditional `get_warnings_attr()` import of Python-level
  `warnings` as an unclosed profile edge; no profile expansion or build/runtime
  claim follows from this bounded source observation.
- [x] Run the focused fixture/profile/table/build-input regressions, Ruff,
  compileall and diff checks. These source and metadata checks do not establish
  header closure, configured source consumption, compilation, linking, ELF
  contents or runtime behavior.

## Core `_warnings` caller/source continuation

- [x] Pin the exact CPython 3.13.12 `Lib/warnings.py` and
  `Objects/genobject.c` archive members as supporting inert source, separate
  from the finite module-profile member set.
- [x] Trace the `_warnings.c` lazy-import call sites, C fallbacks, Python
  `_warn_unawaited_coroutine()` hook, and the `FRAME_CREATED` coroutine
  finalizer condition. Record `linecache`, `traceback`, and `tracemalloc` as
  conditional source edges; do not expand the startup inventory from this
  source-only result.
- [x] Run the bounded Python AST observer over the pinned supporting
  `Lib/warnings.py` bytes and record its ten supported edges and one unsupported
  dynamic import separately from the finite profile; pair the syntax-only edge
  set with source assertions for selected conditional imports and keep every
  closure/runtime claim false.
- [x] Pin `Python/pylifecycle.c` as inert supporting source and test its
  `warnoptions` and `site_import` startup guards against the candidate metadata;
  do not promote these source/config pins to observed runtime settings.
- [ ] Resolve whether the approved fixed startup/workload can reach these
  warning paths, then bind any required conditional modules to the configured
  build and sealed-target evidence. The source fixtures do not establish
  runtime reachability or make `warnings` production-safe by themselves.
