# Callback-free admission bridge inputs

## Scope

Continue the explicit provider-free admission bridge. Canonical JSON serialization
is not a substitute for checking input shape: nested collection/scalar subclasses
can execute callbacks before canonical reparse, and a mutable DTO instance can
shadow its serializer. Reject these inputs before serialization or owner hooks.
Keep the bridge wire and explicit DRS/BRS ownership APIs unchanged.

## Contract

Before JSON encoding, accept only exact JSON builtins and string keys. Before DTO
serialization, allow the existing exact native plan, request, prepared journal,
candidate and handoff-pin DTO types, their declared fields, and exact builtin
collections. Extra instance attributes and serializer shadows refuse. Hook labels
must be exact strings equal to the existing fixed protocol identifiers.

The finite shape walk bounds depth, node count, collection length, aggregate text
and integer size before canonical encoding. Type comparisons use identity and
never invoke a foreign metaclass's equality or hash callback. Existing canonical
byte limits, digest validation, identity links and prepared-phase checks remain
mandatory after the shape gate.

Refusal uses fixed bridge error codes and has no filesystem, ledger, process,
evaluator, budget or owner-hook effects. These checks do not automatically connect
the live scheduler or accept a sealed runtime; `production_admission=false` remains
the current boundary.

## Validation

Focused regressions exercise nested dictionary/list/scalar subclasses, hostile
keys and metaclasses, serializer shadows, oversized aggregate text/collections,
deep input and oversized integers. They assert rejection before JSON encoding or
callback execution. Existing bridge, adapter and prepared-boundary fixtures retain
their canonical wires and successful explicit owner-hook behavior.

Final integrated local validation on Python 3.13: bridge and native prepared-boundary
suites pass 46 cases with zero failures, errors or skips. Ruff over `src tests tools`,
compileall and `git diff --check` pass. The separate final-source Ubuntu matrix
remains necessary for CI acceptance; these tests do not execute sealed CPython.
