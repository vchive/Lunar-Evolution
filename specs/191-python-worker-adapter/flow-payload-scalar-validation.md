# Flow payload scalar validation

The retained whole-case diagnostic records 15,868,766 calls to the flow
payload's nested validator, with 6.700 self / 12.201 cumulative seconds.
These overlapping profile timers identify a local cost, not an end-to-end
saving or a successful Linux mixed gate.

Recognize exact scalar types in their existing order with direct identity
comparisons. In each live container iteration, check the child depth and
exact scalar type directly; recurse for containers and unsupported types.
Every occurrence retains the depth-48 boundary. Dictionary keys must all be
exact strings before visiting values. Lists keep live iteration. Empty
containers at depth 48 remain valid, and every child at depth 49 fails.

The flow validator deliberately leaves float finiteness, integer/Unicode
encoding and the 8 MiB limit to its unchanged canonical JSON boundary. Keep
that boundary, its error wrapping and the fresh state walk on every call.
Do not add caches, change observation scopes, or alter filesystem, SQLite,
source, publication, control or timeout gates.

Run the new boundary cases on the original product before implementation.
Then run them with existing flow/admission and policy drift cases, Ruff,
compileall and diff-check. Compare the actual old/new function ASTs in an
independent local differential probe and measure primitive call counts and
bounded alternating local timings. Do not use timing assertions or treat
these local checks as mixed-case acceptance.

## Local validation

The initial 41 boundary cases pass against the original product. The candidate
and related flow/admission/builtin/freeze selection pass 205 cases, raw return
code zero and zero failures/errors/skips. The latter invocation emitted pytest
warnings while cleaning historical temporary directories; its tool output is
truncated, so no complete warning count or warning-free result is claimed.

An independent actual-function AST comparison covers 4,219 cases with no
mismatches, including live list/dict mutation, depth ordering, cycles, foreign
types and byte limits. A separate bounded pure-memory comparison preserves
2,402 value occurrences and identical canonical bytes, reducing nested
validator calls from 2,402 to 642. Nine alternating groups of 60 full-payload
calls record medians of 586.77 and 316.46 microseconds (46.07% local reduction).
The shape-only probe uses a constant serializer and is diagnostic only. No
timing result is an end-to-end estimate or closes the Linux mixed gate.

Ignored primary-workspace evidence under `release-closeout-20261025/` includes
`flow-scalar-baseline-miqfck58/`, `flow-scalar-independent-f_3ca6zn/` and
`flow-scalar-primitive-q16xfc5i/`. The independent review JSON SHA256 is
`5900ad2c74f362d621c0958ba87c72bbd609108eedc7151a91480a569393abfd`.
The final integrated source still needs its own focused union, Linux mixed and CI.
