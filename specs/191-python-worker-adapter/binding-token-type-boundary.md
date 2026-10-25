# Binding token exact-type boundary

The binding's private validation cache promises callback-free structural tokens
before the original DTO shape validation. A pure independent probe found that
type-set membership invokes a foreign metaclass hash/equality before that gate.
Valid runtime/tree DTOs tampered through `object.__setattr__` reach this path
through the public constructor; self-referential DTOs also escape with an
unbounded token RecursionError. Twelve probes reproduced these failures without
filesystem or process effects.

Use exact class identity for scalar and approved-DTO token dispatch. Unsupported
types return None without class hash/equality, serialization or collection hooks.
Bound token traversal itself at depth 48 and 100,000 visited occurrences. Exceeding
either bound disables the optimization by returning None; original shape/schema
validation still decides admission and emits its existing fixed refusal. Do not
deduplicate repeated objects, cache failed tokens or change the existing cache's
identity/token comparison and capacity. Valid wire bytes, fingerprints and fresh
filesystem/lifecycle validation remain unchanged.

Apply the same class-identity dispatch to this module's wire type, deadline and
budget scalar gates, so caller-provided types cannot invoke metaclass callbacks
at those preliminary boundaries. Keep fixed error codes and bool rejection.

Acceptance covers foreign hash/equality traps, runtime/tree DTO tampering, warm
cache invalidation, subclass refusal, cycles/deep/wide token fallback, ordinary
valid-token equality and fixed errors from public binding entry points. Include
wire/deadline/budget traps, existing binding/cache tests and static checks. These
changes neither grant production admission nor establish mixed/real runtime
acceptance.
