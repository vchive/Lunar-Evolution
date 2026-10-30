# Independent configuration review binding

Status: implementation contract, 2026-10-28. This continuation binds an externally
reviewed, finite configuration profile to the original concrete recipe. It does
not approve the retained real CPython observation or claim a successful build.

## Inputs and authority

The configure runner returns all eight original retained outputs, in its fixed
order: `pyconfig.h`, `Makefile`, `Makefile.pre`, `config.log`, `config.status`,
`Modules/Setup.bootstrap`, `Modules/Setup.stdlib`, and `Modules/config.c`.
`GeneratedConfiguration.output_bytes` is added last with an empty tuple default;
existing positional construction and header-only recipe calls remain compatible.

`bind_reviewed_cpython_configuration` requires original output bytes, canonical
external review-manifest bytes, and a separately supplied expected manifest
SHA256. There is no API that generates an approved manifest from an observation.
The trusted caller obtains that pin through independent review; the binder
cannot prove human independence merely by comparing SHA256 strings.

The exact-schema manifest binds the source inventory, complete Zig manifest,
every original output's size/SHA256, the complete header directive inventory,
the finite Makefile variable closure, both active Setup inventories, the original
config.c initializer table, actual concrete compilation/link semantics, and an
independent concrete-stage graph SHA256. A missing section or output is refused.
Outputs use the exact order above, at most 16 MiB each and 64 MiB total; the
canonical manifest is at most 4 MiB. Duplicate JSON keys and boolean sizes are
refused. Make parsing is bounded to 4,096 assigned variables, 64 recursive
references, 1 MiB of total expansion, 16,384 tokens per variable and 65,536 tokens
in aggregate.

## Finite source-owned semantics

This is not a GNU Make importer. Only simple, unconditional, unique `=` or
literal `:=` assignments and recursively expanded `$(NAME)` references for `=`
are supported in the
reviewed variable closure. Required roots cover core/builtin/module role flags,
replacement/platform/performance objects, static module objects/libraries,
module discovery, and the complete declared Makefile link variables. Every
`MODULE_` assignment participates. Unknown expressions, unresolved/cyclic
references, conditional or duplicate relevant assignments, make functions,
shell expansion and response files refuse the profile. Other Makefile text is
covered by the external whole-file pin and is never executed or interpreted.
`Makefile` supplies those parsed configuration semantics; `Makefile.pre`,
`config.status`, and `config.log` receive independent whole-file review pins,
not a claim that this binder interprets their contents.

The binder records every header directive rather than inferring host features.
Only one exact outer `#ifndef Py_PYCONFIG_H` with its matching empty/`1`
definition and final `#endif` is transparent to critical features. Other or
nested conditional critical features, guard branches and repeated guards refuse.
It separately requires the fixed no-dlopen/no-shared/no-IPv6, pymalloc/mimalloc,
computed-goto and 64-bit feature contract. Setup rows must be static and their
C sources must occur in the concrete compilation graph. The fixed source-owned
`Setup.local` enabled/disabled policy is applied when interpreting the two
generated Setup files; a discovery row disabled by that policy cannot silently
add a compiled module. The config.c table must
match the fixed core/bootstrap module set; additional runtime modules remain
explicit source-profile additions. All replacement and Makefile module objects
must occur in the actual graph. Declared libraries must be covered by the fixed
static linker vectors; shared modules, dynamic linker options and unsupported
libraries are refused. Exact reviewed role flags and exact actual recipe roles
are both manifest-bound; the binder does not invent equivalence for arbitrary
compiler options or silently import them into commands.

The common `PY_CFLAGS`, `PY_CFLAGS_NODIST`, `PY_CPPFLAGS`, and
`PY_STDMODULE_CFLAGS` must be supported by every actual compile-role vector;
`PY_CORE_CFLAGS` by configuration/core/freezer/target and
`PY_BUILTIN_MODULE_CFLAGS` by builtin vectors. Only fixed source-owned
adaptations are recognized: the final optimization/debug options must be the
actual `-O2`/`-g0`; `-fwrapv` is covered by actual `-fno-strict-overflow`;
the explicit `srcdir`/`abs_srcdir` Include roots are relocated to the fixed
source snapshot, while `-I.` selects the configuration snapshot. Eight listed
warning-only options may differ: `-Wall`, `-Wextra`, `-Wsign-compare`,
`-Wstrict-prototypes`, `-Wno-unused-parameter`,
`-Wno-missing-field-initializers`, `-Wno-cast-function-type`, and
`-Wno-unknown-warning-option`. Other options need an actual exact argv token;
additional feature definitions, include roots and warning-error policies are
not approved by re-signing a manifest. Full recipe adaptations still require
independent human review of the exact files and exact stage graph.
Replacement, platform and module objects must also reach both static links
through direct object arguments or the original explicit archive membership;
merely declaring an unused compiled object is insufficient.

An independent reviewer must assess the complete eight files, cross defaults,
feature directives, the expanded role flags and any fixed recipe adaptations,
replacement objects, discovery/disabled module decisions, and static library/
CRT/compiler-support closure. Pin equality does not perform that review.

## Recipe composition and non-circular graph pin

The optional recipe parameters are `configuration_outputs`,
`review_manifest_bytes`, and `expected_review_manifest_sha256`. All three must be
present together. The header in the eight originals must equal the separately
pinned `configuration_header`. On this explicit path the original concrete
generator binds the review before returning any recipe. It stages the eight
originals under `configuration/original/` and the exact external manifest as
`configuration/review.json`, with ordinary complete input records. The existing
original runner and dependency consumer therefore see those exact bytes.

The stage-graph pin is SHA256 of `canonical(stages)`, where `stages` is exactly
the concrete recipe's original list of stage dictionaries, original argv and
output declarations. It excludes input inventories, all review metadata and
the review manifest's own pin, so approval is not self-referential. Compiler/
linker dependency instrumentation, standalone-linker and explicit-support
successors pass the optional parameters into the same concrete gate. Their
later finite transformations remain checked by their existing validators; the
concrete-stage pin is not a pin of their complete execution transcript.

Omitting all three parameters preserves existing recipe bytes. Partial selection
refuses. No new boolean can substitute for original bytes or an external pin.
Configured closure, immutable custody, helper runtime closure, installation,
build/runtime acceptance, production admission and online publication remain
false. Full accepted input/build custody and actual configured CPython/static
ELF/sealed-startup acceptance remain separate prerequisites.

## Consolidated validation

Add focused tests for all eight retained bytes; complete profile binding through
the actual recipe; every missing output/section/parameter; mismatched external
pins and re-signed unsupported semantics; header/Setup/object/library drift;
concrete-stage drift; explicit successor parameter propagation; and unchanged
legacy bytes. Synthetic manifests are explicitly fixtures, never approval of
the retained real CPython files. All 101 review nodes and 15 configuration-generation nodes passed in the
root's concentrated Linux union. Its other native-fixture failures and affected
supplements remain recorded separately in `validation.md`; this is not a claim
that the full union or real build/deployment acceptance passed.
