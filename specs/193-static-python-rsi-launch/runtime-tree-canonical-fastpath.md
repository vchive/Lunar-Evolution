# Bounded detached runtime-tree JSON encoding

## Scope and evidence

The existing runtime-tree canonicalizer streams Python `JSONEncoder.iterencode`
chunks to preserve its 8 MiB early limit. A retained whole-case profile contains
26,951 canonicalizer calls, with 51.873 seconds cumulative time out of 548.898
seconds overall. Its direct generator advances total 48,435,742 calls. These
overlapping cumulative times are diagnostic evidence, not additive savings or a
new performance acceptance result.

This change only removes repeated Python chunk traversal for conservatively
bounded small JSON graphs. SQL reads, current digests, lineage, DTO validation,
filesystem evidence, launch authority and publication authority remain unchanged.

## Contract

The existing `_canonical(value)` interface and streaming implementation remain.
Before streaming, a private probe may build a call-local independent graph from
exact dictionaries with exact string keys, exact lists/tuples, strings, booleans,
`None`, and integers whose magnitude fits 64 bits. Each string contributes a
conservative `2 + 6 * len(value)` byte bound; each supported integer contributes
21 bytes. Container punctuation and keys are included. All mutable containers
are copied; immutable scalar leaves may be shared.

Punctuation is charged for every actual copied item, without trusting an earlier
container length. A source list that grows during copying therefore cannot add
unaccounted commas to the C encoder's private input.

The probe has independent depth and node limits. A float, subclass, unknown
value, cycle, exhausted work limit or bound above the current 8 MiB limit selects
the original streaming path. The probe never reports a product refusal. In
particular, an overestimated bound does not reject a valid smaller encoding, and
an oversized prefix followed by an invalid value keeps the stream's original
first refusal. An unsupported value before that prefix keeps its earlier JSON
refusal.

Only a fully detached graph with a complete bound at or below the limit reaches
the standard C encoder. Custom or rebound encoder methods/backends, a replaced
public encoder alias, and per-instance method shadows use the original streaming
implementation. The result retains the exact canonical UTF-8
bytes, fixed error codes, and final byte limit. Lone surrogates still produce
`json_invalid`; no malformed string gains acceptance.

The three encoder methods and the streaming factory retain their original code,
positional-default tuple identity, and keyword-default dictionary identity plus
key/value identities. This includes original `None` keyword defaults and detects
in-place primitive value changes without invoking caller equality.

## Validation and acceptance

Focused tests retain the original helper as an AST oracle and compare bytes or
fixed refusals for UTF-8, escaping, signed integers, floating-point fallback,
surrogates, exact size boundaries, invalid/oversized ordering, cycles, work
fallback, subclasses, backend rebinding and mutation after detachment. Existing
tree parser, shape, component and ancestry tests remain required.

Before performance acceptance, compare the same retained call-local tree wire
against the original helper in an isolated micro run. Keep source bytes and
output SHA-256 pins, separate cold/warm runs, and report wall time, CPU time and
call counts. Do not infer whole-case savings from this micro result. Then use one
new actual-source mixed run with the existing 600-second whole-case gate; keep
the preceding timeout evidence. No remote evaluator or external benchmark source
is needed or modified.

The scheduler's existing code-dependency projection explicitly fingerprints
`_canonical`, `_bounded_exact_json_snapshot` and `_json_fast_encoder_current`;
the snapshot config includes the current depth/node/manifest-byte limits. The
existing BRS structural code/default checks and exact-int limits precede scoped
policy-cache hits. These finite projections add no validation-result cache.

The parent-owned16-file batch passed778 cases with matching2523-record source
inventories; Ruff, compileall and diff checks pass. A retained-AST micro run used
builder-produced10-file/15,752-byte and266-file/93,086-byte DTO wires. Outputs
agree; median CPU improved340.176→198.431µs and1753.208→1110.836µs across five
alternating warm batches. Source bytes remain fixed; original failed interpreter
startup and pytest collection-only records are separately retained. These are
local comparisons. The new clean source's original-budget mixed/CI remain open.
