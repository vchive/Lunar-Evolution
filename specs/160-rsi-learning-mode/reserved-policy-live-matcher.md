# Reserved policy live matching

## Contract

Keep the existing finite policy graph, every independent live observation, and
its original refusal behavior. A policy projection must still inspect current
module namespaces, classes, functions, defaults, annotations, globals, closure
cells, builtins, runtime aliases and configured limits. It must not reuse an
earlier validation result, omit an observation, or extend a deadline.

## Implementation

The original `freeze` builds the held immutable baseline. `matches_frozen`
compares current exact scalars, lists, tuples, dataclass Fields and string-keyed
plain dictionaries directly with that baseline. It preserves container type and
identity, scalar tags, sequence order, Field attributes, node/depth/length limits
and opaque object identities. Proxy, set and heterogeneous-key shapes retain
the original freeze path.

Each dictionary comparison builds a temporary lookup only from the held exact
string keys. It then observes live items, checking each key's exact type before
looking in that trusted temporary dictionary. It never performs keyed lookup
in a live dictionary that could acquire a foreign colliding key concurrently.
The lookup is discarded after this observation; the baseline remains immutable.

The matcher and its original captures are checked before invocation alongside
the original helpers. A changed helper, code object or capture must refuse.
The original policy protocol and source-derived identity remain in force.

## Validation

`test_rsi_brs_reserved_policy_matcher.py` compares acceptance with the original
freeze gate for supported and changed shapes, including exact bool/int tags,
same-content replacement containers, unordered dictionaries, ordered sequences,
Field mutation, foreign hooks, colliding keys, cycles and resource bounds.
Existing policy drift tests cover the composed projection and matcher code.

These tests and any local timing are ordinary software evidence. They cannot
close the original 600-second Linux mixed acceptance, full CI or production
runtime requirements. Performance improvement remains unverified until measured.
