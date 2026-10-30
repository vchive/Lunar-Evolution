# File-pin parser local reuse: deferred after cost check

## Decision and scope

The proposed optimization would skip only the second, constructor-time validation
inside `parse_python_producer_admission_handoff_file_pin` when its original input
is an exact `PythonProducerAdmissionHandoffFilePin`. The parser's first validation
would still run on that call's fresh scalar projection, and the result would be a
new exact DTO. Dict, bytes, text and bytearray inputs would retain their current
constructor path. Public construction, explicit `__post_init__` and `to_dict`
would retain fresh validation.

**Status: deferred; no product implementation or behavior change.** The reduced
guard prototype already costs more than the duplicated work it could remove. Keep
the existing public constructor path rather than widening the guard architecture
for this small local saving.

## Required semantic boundary

Skipping the constructor is unsafe under live changes to the class alias,
`__new__`, `__init__`, `__post_init__`, `_payload`, slot descriptors, attribute
lookup or their in-place function metadata. The same applies to validator,
canonicalization, hashing, JSON backend, referenced constants and builtins.
Checking a function's identity alone does not detect changes to `__code__`,
defaults, keyword defaults, closure contents or mutable backend bindings.

A valid implementation would need a guard before source projection and another
after the first validation. A changed guard must fall back at the existing public
constructor location without re-entering the parser or repeating its first
validation. That preserves the current constructor's errors and observable live
hooks. It must also preserve the reserved-policy graph and prove that cloning
cannot invoke an unpinned descriptor or attribute callback.

There must be no cross-call cache, cached authorization result, weaker scalar
validation, or skipped filesystem/source/budget checks.

## Diagnostic cost check

Source: `3e1a04eb2a3854caac15d5859a8d5b799b9f0f15`;
`python_producer_admission_handoff.py` SHA-256:
`c01b1c7421e9e953d3291a4f5be8849166c9d005c29f7810d002b254a32d772b`.

Local Python 3.13.12, seven alternating-order repeats of 10,000 calls each, after
warm-up:

| Operation | Median per call | Validator / canonical calls |
| --- | ---: | ---: |
| Existing exact-DTO parse | 16.05 microseconds | 2 / 2 |
| Constructor only | 8.32 microseconds | — |
| Validation only | 6.46 microseconds | — |
| Unsafe clone without guards | 8.41 microseconds | 1 / 1 |
| One reduced guard | 5.73 microseconds | — |
| Two reduced guards plus clone | 20.62 microseconds | 1 / 1 |

The guarded diagnostic is about 28.5% slower than the existing parse. It checks
only a subset of the necessary graph: selected function metadata, class methods,
MRO and slot descriptors, key module globals, JSON backend and builtin bindings.
It does not implement full mutable metadata/content checks, complete backend
recursion, post-clone drift proof or reserved-policy integration. These numbers
are a local implementation-cost observation, not a claim that every possible
guard implementation has the same cost.

Ignored evidence is retained under:

`.lunar-evolution/validation/release-closeout-20261025/file-pin-guard-cost-prototype/`

- `prototype.py` SHA-256:
  `9ac2bd3c4bbc5276127624988ac3a1d3b4f600663b43a0b01faf3319fa4531f3`
- `result.json` SHA-256:
  `4d2376a752b0322edab131e5f26a1f6109ed8e14e4e13971209fa73e3e69da68`

The diagnostic does not replace mixed-child acceptance, CI, or the original
failed-run evidence. No evaluator, model, producer, filesystem capture or network
operation is performed by the measured parse/guard functions.

## Revisit criterion

Revisit only if a simpler boundary removes the need for broad live-mutation
equivalence, or profiling demonstrates a larger bounded saving that justifies
the guard and policy surface. Retain the existing fresh validation meanwhile.
