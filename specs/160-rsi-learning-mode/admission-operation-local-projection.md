# Admission operation-local projection

## Scope

Reduce repeated pure staging identity parsing inside one existing ledger operation.
The implementation must not cache a DTO or a validation decision between calls,
remove a SQL/FS observation, or change admission authority, budgets, ownership,
checkpoint order, state transitions, or the final independently retained rows.

## Contract

- A staging history walk may reuse only its own immutable scalar/byte projection
  of a previously checked entry. Current entries must have an exact plain JSON
  shape before equality, and the complete current entry must match the previously
  validated entry. Current per-checkpoint policy, capacity and state-machine
  checks remain in their existing order.
- Foreign request/memory parser or digest helpers must keep the original parsing
  path. No hook results or caller-owned DTOs become reusable authority.
- Reuse ends when the function returns or raises. A second invocation reparses the
  original input, and changed entries follow the existing validation path.
- The admission state reader continues its second fresh checkpoint SELECT and
  the original fresh JSON decode until a small, independently reviewable raw-row
  binding proves that helper-mutated history state cannot be adopted. The mutable
  staging history result alone is insufficient for that optimization.
- Public returned dictionaries remain independently mutable. There is no new
  persistent cache, global validation result, or publication gate exemption.

## Validation

Focused regression coverage must establish per-call parse reduction, fresh
parsing on a second call, refusal of changed identity/ready/phase/policy/capacity,
callback-free equality, foreign-helper fallback, and preservation of the
admission reader's fresh SQL/decode behavior after a staging helper mutates its
input. An AST differential oracle retains the original staging walk. A small
provider-free probe may count original/new parser calls without running a mixed
case, launching a process, or reading any remote evaluator.

Root runs the centralized focused tests, Ruff, compileall and diff checks after
the implementation is frozen.

## Implementation and bounded evidence

The first implementation changes only staging identity parsing. Admission state
SQL/decode is deliberately unchanged because its mutable staging-helper output
cannot safely stand in for the second fresh decode.

The four direct request/memory parser and digest methods are pinned by descriptor,
code, defaults and keyword-default identity. Rebinding or in-place drift disables
reuse. This is a finite direct-helper check, not a transitive Python dependency
authenticator. The scheduler dependency projection includes the guard and staging
walker; the BRS policy pins the immutable helper table and guard before its
existing scoped policy cache.

One independent pure probe used 16 plain checkpoint states, a real SolverRequest
wire, empty memory wire and a capsule-ready reference. Parser calls fell from
15 to 2 for both request and memory; digest calls fell from 30 to 4. A second new
walk repeated the same 2/4 counts. Five alternating batches of 40 walks measured
median process CPU of 1185.400 versus 874.925 microseconds (1.355x) before the
final exceptional-projection fallback adjustment. That adjustment affects only
failed post-parse rechecks. This local probe does not establish mixed-case time
or acceptance. The input history remained unchanged.

Evidence is retained under
`.lunar-evolution/validation/parallel-batch-20261027/admission-local-projection-pure-v1o4eas5/`.
No pytest, Ruff, compileall, mixed case or remote process was run by this change's
implementer. AST parsing and equivalence checks confirmed the retained original
walk oracle and unchanged admission state-reader AST against commit `72c2f973`.
