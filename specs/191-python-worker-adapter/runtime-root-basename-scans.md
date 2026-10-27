# Canonical runtime root and declaration basename scans

Status: narrow implementation, differential experiment, independent source
review and local focused validation complete; final-source Linux/CI pending.
This continues Feature191's canonical POSIX path contract. Linux mixed and final
source acceptance remain open; runtime and publication admission remain false.

## Contract and scope

`_root_paths` retains its original Mapping/length gate, bounded `items()` loop,
`_label` call, accepted raw types, fresh `str(raw)` and `_path` call, Path
construction, duplicate-label gate and insertion order. Only after every original
Mapping callback has completed, it obtains fresh text from the already constructed
Path values. The final pair loop keeps its original order and refuses equality or
either ancestry direction using a slash-boundary prefix. `/` is an ancestor of
every other accepted absolute path; `/a` is not an ancestor of `/ab`. The returned
sorted dictionary still contains the original Path objects.

`PythonRuntimeFileDeclaration.__post_init__` retains `_label`, `_path` and the
exact role/type membership gate in their original order. At the original basename
point it rereads `self.relative_path`: a role membership callback can have changed
that field since `_path` returned. An exact string with a final component uses
`rpartition('/')` and the original `casefold()`. Standalone `.`, a trailing `/` or
`/.`, and every non-exact-string value retain `Path(value).name.casefold()`,
including foreign PathLike and string subclasses introduced by that callback.
The listed import-hook refusal and its original error code remain unchanged.

These are two pure lexical computations under the existing canonical POSIX
contract; they do not promise extra calls to a caller-replaced Path backend.
No declared validation or Mapping/role callback is removed. Public DTO
revalidation, filesystem/source/control observations, graph absolute ancestry,
budgets, original 600-second limits and online publication are unchanged.

## Validation plan

- [x] Verify that both retained original function ASTs match frozen source
      `4e1847dda1bb0a1fc3d37037b23b6be2863a61fb` before the change.
- [x] Run one pure-memory differential experiment with those actual original
      functions and the candidate, including slash boundaries, Unicode, root
      refusal/order and post-role mutation/fallback behavior.
- [x] Record a small alternating local timing observation. Ratios are local
      observations, not Linux mixed or whole-case performance claims.
- [x] Add independent regression/oracle coverage and run one integrated focused
      selection, Ruff, compileall and diff checks through the integrating agent.
- [x] Complete independent source/oracle review.
- [ ] Complete final-source Linux mixed and full CI acceptance.

The earlier frozen `4e1847dd` Linux mixed attempt retained raw return code -15,
`timed_out=true`, matching pre/post source pins and no JUnit. It is a failed
original 600-second run and is not retried or converted into acceptance here.

## Local experiment

One actual-original-AST experiment exited zero with 4,644 differential comparisons
and no mismatch: 4,383 plain root cases, nine Mapping/raw callback cases, 132
declaration gate cases and 120 role-callback mutation/fallback cases. It includes
post-Mapping changes to an earlier ordinary Path and a fresh per-iteration root
bound, without replacing the Path backend. All other product ASTs are unchanged.
The original root AST SHA256 is
`8901bba2c7891d3b2fa6dbcff0bffa2d30910eb3b70dc2ffeac8a58b366ca0db`;
the declaration post-init AST SHA256 is
`1ff693c506889a99d4f47df04dbd298fa6b9ef9568b45ad8f5c0207a4e14de94`.

Five short alternating local timing blocks measured median candidate/original
ratios 0.06867 for 16 disjoint roots and 0.44010 for four ordinary declaration
paths. These input-specific observations do not predict a whole-case or Linux
wall-time reduction. Source copies, actual retained ASTs, script and raw output
remain ignored under
`release-closeout-20261025/runtime-root-basename-ast-4sfhgojn/`.
Its `measurement.json` SHA256 is
`1025b58f8f44fe17b661a8775aa0d604b8827e3b48cc5919a0daf365ece6f3ae`.
This experiment is not pytest, mixed-case acceptance, CI, merge or admission.

## Integrated focused validation

One seven-file invocation collected 651 distinct nodes: 572 passed, 79 skipped,
zero failures/errors, original pytest rc0, 27.892034 seconds. All 85 new cases
passed. The 79 skips are exclusively the existing material tests' unchanged
`requires actual Linux memfd seals` gate on macOS; they remain required on Linux.
Product/test hashes match before and after. Whole-repository Ruff, compileall
and diff checks pass. Independent source review confirms the two actual old ASTs
and unchanged remaining product ASTs.

The temporary outer wrapper incorrectly required zero skips and therefore
returned 1 after pytest completed. That wrapper result and the original rc0/XML
are retained; neither is rewritten and no test was repeated. Offline skip
classification does not establish Linux material or mixed acceptance.

Ignored evidence: `release-closeout-20261025/runtime-root-basename-focused-v223emfy/`.
Original JUnit SHA256:
`75abe12cabc4a53b406e2369f97af05a9b8ce556c185f178d778d78b7c3ce674`.
