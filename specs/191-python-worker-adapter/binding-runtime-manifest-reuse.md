# Binding parser runtime-manifest reuse feasibility

Status: deferred after local feasibility review; no product or test change.
This is a narrow continuation of Feature191, not a new admission capability.

## Observed cost and scope

An unchanged normal-owner C1 `[1]` test at source
`1e6f10f804495a3c1e8f41fc3f04968f01c11d02` passes under stock cProfile in
17.77 seconds. Its binding parser calls `_reparse_runtime` 132 times with
0.779513 cumulative seconds on that direct edge. This is a local, nested
whole-test observation. It does not explain or resolve the mixed-case timeout;
the mixed flow has an enclosing policy observation scope that this fixture does
not reproduce.

The parser first parses strict bounded JSON into a manifest, closed tree, launch
intent and attestation. It then validates outer metadata and scalar budgets.
At assembly it keeps this order: header, runtime reparse, nonzero tree digest,
launch reparses, identity/budget joins, binding digest, exact canonical wire.
Public construction, `__post_init__`, serializers, `digest` and `replace` retain
their complete caller-owned DTO gates.

## Required contract

Any future local reuse must preserve exact type/shape checks, nested field and
capacity bounds, every slot/manifest/binding digest, detached DTO ownership,
canonical bytes and text, fixed refusal codes and multi-fault precedence.
Foreign or replaced runtime parsers must use the existing `_reparse_runtime`
path. No public trusted flag or new cross-call cache is allowed. Filesystem,
source/policy, inode, budget, history and CAS observations remain independent.

Checking only the initial parser's identity and code does not establish that
its result stays private. Later tree/intent/attestation parsers, or replaced
constructor/validation helpers, can retain or mutate the earlier DTO. Reusing
that object directly would remove a real caller-alias revalidation boundary.

## Constructor reconstruction experiment

A pure in-memory comparison uses the existing 2,072-byte inert manifest and
100 independent cache-miss inputs. The tentative reconstruction preserves the
original exact-type gate, full declared shape gate, original `__post_init__`
and full `to_json` capacity gate. It explicitly reconstructs target, roots,
directory pins, files, import roots, entrypoint and manifest through their
dataclass constructors, so DTO nodes are detached without another JSON decode.

| Measured local slice | Total, 100 inputs | Median per input |
| --- | ---: | ---: |
| Existing `_reparse_runtime` | 0.038040 s | 0.000364 s |
| Tentative detached reconstruction | 0.032692 s | 0.000318 s |

The candidate/original total ratio is 0.8594 on this one small fixture. No timing
threshold or end-to-end performance claim follows. Its ordinary valid outputs
are equal and serialize to the same bytes, but this experiment does **not**
prove foreign serializer/helper equivalence. In particular, the existing path
decodes and checks the serializer's actual output; reconstructing fields can
produce different behavior when `to_json` or nested `to_dict` implementations
are replaced. Retaining that behavior would require more guards or a broader
parser refactor, beyond the measured narrow opportunity.

## Decision and validation

Do not implement the optimization in this slice. The modest local saving does
not justify a longer trust mechanism or weaker canonical/refusal semantics.
Keep the existing product path and its tests unchanged. Revisit only with a
smaller equivalence-preserving design and a useful measured benefit.

The stock profile's original XML, pstats, raw output, return code and unchanged
2,364-file source snapshots are retained in ignored validation evidence under
`release-closeout-20261025/stock-original-owner-c1-confirmed-python-ufk2qqcu/`.
The separate pure comparison is retained in
`release-closeout-20261025/runtime-detach-memory-comparison-_hseugs8/comparison.json`.
The earlier missing-pytest startup failure remains preserved separately. No
model, producer, evaluator, remote worker or mixed selector ran for this review.
Only this design note changes; Markdown whitespace is checked with
`git diff --check`. Product focused tests, Ruff and compileall are not applicable
to this documentation-only outcome.
