# Explicit real-output configuration review v2

## Purpose and selection

The retained CPython3.13.12 configuration has a commented outer header guard,
two genuinely absent Make variables and a shared-mode standard-library discovery
template. These are not accepted by the v1 finite contract. Keep that contract,
schema, profile, direct binder and all existing review pins unchanged.

Add `configuration_review_v2.py` with schema
`lunar-cpython-configuration-review-v2` and profile
`cpython-3.13.12-zig-0.16.0-x86_64-linux-musl-v2`. The independently supplied,
canonical manifest and expected SHA256 explicitly select v2. The concrete recipe
uses a dispatcher which validates the independent input pin before selecting
the exact schema. A refused v1 manifest is never retried as v2. Existing optional
eight-output review parameters carry this selection through existing generators;
omitted review and v1 selection retain identical recipe bytes. V2 alone adds
the actual source `Objects` and `Python` include directories to every compiler
vector, after the original fixed include roots and before runtime additions.
Selection validates the independent review pin and exact schema before building
those vectors; the later binder still verifies the complete approved stage graph.

The v2 manifest retains every v1 binding and adds `make_absences`,
`make_absent_references`, `stdlib_discovery_rows` and `adaptations`. It binds all eight original files,
source/toolchain pins, header directives, bounded Make closure, effective static
Setup rows, original config.c table, concrete role semantics and stage graph.
No production API creates an approved manifest or expected pin from observations.

## Finite syntax compatibility

Only the exact source-owned `Py_PYCONFIG_H` outer guard may close with its lexical
block comment. Preserve that original directive in the review facts. All critical
feature, nesting, branch, duplicate guard and whole-file pin checks remain active.

The two optional variables are exactly `PLATFORM_OBJS` and
`PERF_TRAMPOLINE_OBJ`. Distinguish absence from an explicit empty assignment in
the manifest. An absent optional root must not occur through actual
`LIBRARY_OBJS` references, directly or indirectly; any other unresolved variable
still refuses. Include `LIBRARY_OBJS` in the bounded simple-assignment closure
and compare its object requirements with the actual fixed graph. Do not evaluate
Make functions, scripts or recipes, and do not supply generic empty defaults.

Record absent referenced leaves separately as `make_absent_references`, retaining
name, exact referring parents and source-owned semantics without synthesizing
assignments or entries in `make_variables`. The only permitted edges are six
unassigned user override leaves through their exact stock `PY_*` expressions,
and the nine fixed bootstrap `MODULE_*_LDFLAGS` through the exact stock
`LOCALMODLIBS` sequence. The direct recipe executes no Make and consumes no
ambient Make command-line/environment overrides; its actual compiler/link
vectors remain independently bound. Present leaves retain their original value
and all ordinary validation. Unknown missing leaves, changed parent expressions,
alias references or conditional assignments refuse. These fifteen referenced
absences are distinct from the two optional absent object roots.

The parent source-owned driver already forbids stock `Modules/getpath.o` and
`Python/frozen.o` and fixes separate freezer/target replacements. Record exactly
these existing replacements in v2 adaptations and verify actual compilation and
link reachability for each role: stock getpath maps to `Modules/getpath_noop.o`
from original `Modules/getpath_noop.c` in the freezer, and to
`installation-owned-strict-getpath.o` from the fixed fixture getpath source in
the target. Stock frozen maps to `installation-owned-finite-frozen.o` from the
fixed generated or explicitly selected runtime frozen source in the target;
the freezer's original `Programs/_freeze_module.o` supplies its frozen-pointer
placeholders. No manifest-selected alias, other object replacement or stock
object inclusion is allowed. This relation describes the existing reviewed
graph; it neither modifies that graph nor proves its runtime behavior.

Keep reverse coverage for every baseline core/builtin object, including
`Modules/config.o`. The fixed pipe source/object is an explicitly recorded
Make-external addition only when it actually reaches both static links. Existing
runtime opt-in may add only the exact source-owned `_NATIVE` pairs, complete
multi-unit groups, and Shinka-only complete SQLite group. Such additions require
the actual runtime config/frozen translation units and fixed solver link shape;
output naming alone cannot authorize them. Record `fixture_pipe_addition` and
`runtime_native_additions` separately in `adaptations`. Unknown source/object,
wrong role, incomplete groups, missing baseline objects or missing link reach
remain refusals. No new runtime API or compiler command is introduced.

Parse `Modules/Setup.bootstrap` with the unchanged effective-static parser.
Interpret fixed `Modules/Setup.local` policy separately. Parse the original
`Modules/Setup.stdlib` only as discovery records retaining original mode, name
and complete row text. Never expand its `$(srcdir)` text or add compilation
units. Any shared/active discovery outside the exact fixed disabled set refuses.
Do not rewrite original mode markers. Effective enabled module/object names
still come from the fixed policy, original bootstrap, actual Makefile and
original config.c, with exact source/object/link closure and no shared modules.

## Explicit semantic adaptations

Record every adaptation in the independently pinned manifest. The sole new
warning-only difference may be `-Wunreachable-code`; arbitrary flags, feature
defines, include roots and `-Werror` variants retain their refusals.

Stock `LINKFORSHARED = -Xlinker -export-dynamic` is not consumed by Lunar's fixed
static link graph. Permit only that exact stock vector as an explicitly recorded
unconsumed Make executable variable. Never append it to real commands, admit
other dynamic options or ignore a real dynamic link/module requirement.

Any static-musl `-ldl` adaptation requires a fixed target, explicit libc linkage
in both original concrete links, independently reviewed upstream/static-support
evidence and exact external review facts. Do not accept arbitrary `-l` aliases
or claim that a current cache hash authenticates libc. If those finite grounds
are missing, retain a semantic refusal after parsing; syntax success is not an
approved configuration. Later direct-link transformation still requires its
separate pinned explicit support profile and genuine exact depfile comparison.

## Validation and remaining acceptance

Develop the v2 binder, original-generator dispatch and independent test file in
parallel, then run one combined focused batch with the original v1 tests and
generator compatibility tests. Include real-shape header/absence/discovery facts,
negative feature/object/dynamic/library/flag/pin/graph cases and unchanged v1 and
omitted-review bytes. Fixtures remain synthetic external-review declarations.
Follow with Ruff, compileall and diff checks. Never use ignored local originals
as an implicit CI fixture or automatically approve their digests.

The local originals remain a configuration observation requiring independent
whole-file/semantic review. This slice alone does not execute configure, CPython,
a generated ELF, models, solvers or evaluators. Full configured/static ELF,
immutable input custody, sealed startup, owner/lifecycle, producer/CLI and actual
system-account acceptance remain separate; production admission and online
publication stay false.

## Observed validation

Final software tree268d44f8744fee6f6fa3ec60652a3f12ef5c5f13 contains2753source
files.30complete affected files passed1223unique tests:1163 on Linux3.12 in
35.752073s and60 on Darwin3.13 in1.231840s, including128new cases. Zero failures,
errors, skips or retries. Both snapshots retain identical source bytes and Git
executable-bit projections before/after; full POSIX permissions are not asserted.
Ruff, compileall and diff checks pass. Existing83focused groups/65zero-skip remain;
source-group expected count849, overall fixed expected sum7588.

The first8c8708d2 batch retained423pass/5ENOSPCfail/756setup errors because the
external harness left temporary storage at inode-exhausted/tmp; the new v2 bodies
did not execute. The outer local shell also failed on a readonly variable after
the original execution. No originals were overwritten. The final run explicitly
sets Linux TMPDIR/basetemp on/dev/shm and moves the complete60case file containing
literal/tmp socket fixtures to the authorized local host. Old tests stay unchanged.

Independent observations of the eight actual originals first retained the missing-
reference refusal, then identified all15finite leaves and the missing real include
directories. Final pure parsing and fixed-plan diagnostics pass:190variables,
15separate references,2absent roots,699header directives,49discovery rows and
163Make objects covering161baseline/two stock replacements. These observations
are after-the-fact diagnostics, not an approved review manifest, expected pin,
actual generated recipe execution or configured-build acceptance. Final receipt
SHA25676e87664b033857804650e39058d76f6cd6d3f507c5d6885d6fdbb440178c91a.
The evidence is retained under primary ignored `validation/configuration-v2-20261030/`.
This continuation requires its own complete PR197 CI/source gate before integration.
