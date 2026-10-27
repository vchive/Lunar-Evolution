# Canonical runtime-tree component scans

Status: implementation, local focused validation and independent source review
complete; integration/final-source acceptance pending. This continues Feature191's
canonical POSIX path contract and grants no runtime or publication admission.

## Contract and scope

Every `_relative` call still invokes `_text`, then the current declared `_path`,
then applies the original tree depth bound. Canonical relative text has no empty,
`.` or `..` components: its depth is slash count plus one, except the accepted root
`.` has depth zero. `_name` still invokes `_relative` before checking that the
accepted text has one component. Its single-component check can use absence of `/`.

The graph validator retains its `_relative` call for every original path before
computing that path's parent and name. For non-root canonical text, one
`rpartition('/')` yields both components; a separator-free name has parent `.`.
Only these three pure lexical computations change. Graph root/ancestor pathlib
handling, graph membership, directory ordering, all digest/DTO validation, fresh
filesystem/source/control observations, callbacks, budgets and deadlines remain.

As in the preceding declared-path lexical slice, this contract specifies canonical
POSIX text and exact refusal codes. It does not promise additional calls to a
caller-replaced `Path` implementation. Existing oversized-value tests continue to
require refusal before any pathlib parsing. This does not authorize removing an
explicit configuration or source callback, or trusting a caller-owned DTO/cache.

## Evidence and validation plan

The retained historical whole-case profile records 1,058,854 tree `_relative` calls
and 356,626 `_name` calls. Their direct pathlib `parts` edges total 2.605 and 0.805
cumulative seconds, respectively; graph parent/name edges each have 166,413 calls.
These imperfect threaded profile values select a hotspot, not wall-time savings.

One AST-only, pure-memory feasibility experiment compared the actual original
helpers and graph edge loop with the proposed computations: 2,300 input/bound/graph
comparisons, zero mismatches. Three short alternating timing blocks measured median
candidate/original ratios 0.2826 for `_relative`, 0.1851 for `_name` and 0.1412 for
the relationship loop. This is not whole-parser, Linux-case or end-to-end evidence.
Its ignored `measurement.json` SHA256 is
`08bfa2006d62a0c216cee676830cb0b88dfed1945ef11578214b3aaeac8f7fbc` under
`release-closeout-20261025/tree-canonical-path-feasibility-ynhpz_h3/`.

- [x] Replace only the three lexical computations, retaining original gate order.
- [x] Add a separate test module with the original helper/graph AST as oracle;
      cover malformed text, Unicode, foreign values, dot/depth bounds, and graph
      membership/parent/name behavior. Do not change the original tree suite count.
- [x] Run the new module and original tree, detached tree parser and binding parser
      normalization modules together once; retain exact JUnit evidence.
- [x] Run focused Ruff, compileall and `git diff --check`.
- [x] Obtain independent read-only source review without repeating tests.
- [ ] Integrate final-source acceptance.

The one four-module focused run passed 212 unique cases: 17 new component-scan,
151 original tree, 27 detached tree parser and 17 binding normalization cases,
zero failures/errors/skips. Product bytes were unchanged after this run. Ruff then
required an explicit fixed-AST `exec` explanation and parameterized immediate test
helper calls; after those test-only edits, the final 17 new cases passed again in
0.33 seconds. These 17 are a subset of the 212, not an additional acceptance total.
Final Ruff, compileall and diff checks passed. All three retained oracle function
ASTs independently match the pre-change HEAD functions exactly.

Raw JUnit, stdout/stderr, return codes and final source pins remain ignored under
`release-closeout-20261025/tree-component-focused-yg3wij5p/`. This focused result
does not replace mixed-case acceptance, CI, merge or production/runtime admission.

The unrelated private JSON decode/one-shot hypothesis was rejected before
execution because fresh decoded mutable graphs were not proven unobservable to
ambient callbacks/threads. This lexical slice makes no such ownership assumption.
