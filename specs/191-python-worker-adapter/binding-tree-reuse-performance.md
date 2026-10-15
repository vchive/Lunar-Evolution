# Fresh tree reuse inside binding parsing

Status: local semantic comparison, focused validation and static checks passed;
independent review and integration remain pending. This continues Feature191's
existing pure parser contract and grants no runtime admission.

## Existing redundancy and scope

Baseline `bbfba929ba75f3e12b26019f9c2990fb9acb3233` already contains the earlier
binding canonical projection (`66251b0` / `d35d21d`) and detached runtime tree
parser reuse (`482a58f` / `dcc67bc`). This slice does not repeat either change.

The binding parser first parses the runtime tree from strict bounded JSON. Its
public binding constructor then immediately calls `_reparse_tree`, which again
validates, serializes and parses that fresh tree. No caller owns that tree or
can mutate it between those operations: its exact DTOs and primitive fields are
created entirely by the trusted local child parsers.

Only the binding parser now assembles its exact frozen DTO without invoking the
public constructor. It retains the same header checks, full runtime reparse,
nonzero tree digest check, full intent/attestation reparses, binding identity and
budget joins, binding digest and exact canonical byte comparison. It reuses only
the tree that the same parser call has already fully validated, before return.

The original join checks are shared as private methods on `PythonProducerBinding`,
alongside header and digest checks. This keeps their source in the existing class
identity projection; no new module-global helper or caller-supplied validated
flag is introduced. Public construction and `__post_init__` keep their original
order: header, runtime reparse, full tree reparse, intent reparse, attestation
reparse, join checks, binding digest. Public `to_dict`, `to_json`, `digest` and
`dataclasses.replace` continue to use that complete caller-owned DTO path.

There is no object cache, cross-operation reuse, launch grant or new API. Tree
graph, digest, member and capacity validation still occur in the original child
parser. Sidecar/configuration/source hooks, source reads, inode/content pins,
fresh observations, request/deadline/budget state, checkpoint history and CAS
are unchanged and retain their existing authority boundaries.

## Validation

- [x] Run the 47 new semantic cases against the original baseline product module;
  all pass, proving that the cases express its existing behavior.
- [x] Run 236 distinct focused candidate cases with zero failures, errors or
  skips (51.44 seconds). These include the same 47 new cases, earlier binding
  and tree parser matrices, binding/store tests, scheduler input/gateway tests
  and RSI identity/drift suites. The 47 are a subset, not an additional 47.
- [x] Verify exact byte/text roundtrips for both fixture cases and fractional
  deadlines, exact class/fields/digest and public constructor reconstruction.
- [x] Verify simultaneous malformed tree, identity, launch-shape, budget,
  deadline and binding-digest faults retain their original fixed refusal codes
  and precedence, including the launch UInt64 shape bound.
- [x] Verify all five public construction/revalidation/serialization gates
  reject mutated tree digests and same-wire callback-bearing directory or
  declared-file collections before invoking their callbacks.
- [x] Verify the exact original raw byte capacity refusal, existing no-effects
  traps and scheduler inode/configuration/between-observation drift regressions.
- [x] Run focused Ruff, `compileall src tests` and `git diff --check`.
- [ ] Complete independent review, integration and that final source's own CI.

JUnit, baseline/candidate import origins, scoped source hashes, commands and pure
profiles are retained under the implementation worktree's ignored
`.lunar-evolution/reports/fresh-tree-reuse/`. Baseline new-case XML is
`baseline-new-tests-attempt01.xml`; candidate focused XML is
`candidate-focused-attempt01.xml`. Neither run failed; the evidence is retained
under its actual source and is not substituted for release acceptance.

### Decoder portability follow-up

The original 47/236 local results above are preserved as observations of their
original source and interpreter. A later Linux Python 3.12 integration run
exposed a test assumption: its JSON decoder accepts the 2,000-level array used
by two cases, after which the unchanged binding schema gate returns
`python_producer_binding_schema_invalid`. Other interpreters may reject that
array during decoding with `python_producer_binding_json_invalid`. The array is
an invalid binding in either case; 2,000 is not a cross-version hard depth cap.

This tests-and-documentation follow-up preserves the exact raw byte limit
assertion, permits only those two fixed codes for the real deeply nested array,
and adds deterministic decoder `RecursionError` injections for both bytes and
text. Each injected decoder failure must map to the existing `json_invalid`
code. Product parsing, public construction, serialization and source pins are
unchanged. New baseline/candidate XML, logs and source maps are retained in a
separate `fresh-tree-decoder-portability/` report directory; they do not replace
the original evidence or the Linux integration failure.

Follow-up local validation uses CPython 3.11.15: all 49 semantic cases pass
against unchanged baseline `bbfba929`, and 238 distinct candidate focused cases
pass (54.88 seconds), including those same 49. Both have zero failures, errors
or skips. Focused Ruff, `compileall src tests`, `git diff --check` and an
independent read-only review pass. These new counts apply to this follow-up
only; final integrated Linux/cross-version acceptance remains separate.

## Bounded performance evidence

Both single-call cProfile measurements use the same existing inert 26,195-byte
binding, SHA256
`683298d530f99ae0770c9f0bfc0c980a8f51dea633da688897979bfb72b65993`.
Both return the exact original bytes and binding digest
`043e36972cf697f2126a26742631b28e1e494193edbc2b8f568ac30af26f310f`,
with filesystem/process/network effects forbidden during parsing and public
roundtrip checks.

Tree parser calls decrease 2 to 1 and runtime-manifest parser calls 5 to 3.
`_reparse_runtime`, `_reparse_intent` and `_reparse_attestation` each remain one
call. The measured parse time is 0.038749 to 0.018475 seconds, including profiler
overhead and machine load. No timing threshold is added to tests; these numbers
establish neither steady-state throughput nor an end-to-end improvement.

No controller flow, long mixed regression, real model, solver, evaluator,
producer or target runtime was run. Production admission remains false.
