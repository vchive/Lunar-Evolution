# Bounded external-result preflight

Status: provider-free implementation merged on main through PR82 (`d530f9f`),
with the documentation status update carried by PR84. The post-merge main CI run
`38331781593` is still pending at the time of this update; the earlier bridge head
`6770650` is superseded by `94a2ec2`. This slice narrows the OpenEvolve/Shinka handoff boundaries; it does not launch a
producer, authenticate an external worker, or grant runtime/production admission.

## Contract

When `admit_openevolve_result(..., binding=...)` is used, the adapter validates the
caller-owned binding before opening or reading `external_root`. The preflight parses
the canonical `PythonProducerBinding` and compares five identity pins:

1. producer id is exactly `openevolve`;
2. evaluator fingerprint equals the caller's evaluator fingerprint;
3. producer fingerprint equals the caller's producer fingerprint;
4. binding contract digest equals the supplied `AlgorithmProblemContract` digest;
5. an explicitly supplied producer run id equals the binding run id (omission is
   normalized to the binding run id).

Any mismatch returns the fixed `result_binding_mismatch` error before external-root
I/O or evaluator invocation. The preflight uses exact binding type and canonical
reparse; it performs no filesystem, process, network, budget or journal effects.

The preflight is only an early ordering gate. After the result and candidate bytes
are read, the existing `verify_python_producer_result_binding` remains mandatory and
continues to verify the complete result envelope, including producer identity,
producer fingerprint, contract, run id, status and material digest/metadata. The
external producer score remains provenance only; local evaluation remains the result
authority.

The parsed binding is retained as a detached snapshot for the final verifier. Before
verification, the caller-supplied binding must still serialize to the exact canonical
wire captured at preflight; drift is refused. This closes the preflight-to-publication
TOCTOU window without reusing mutable caller state as authority.

For `export_shinka_result(..., binding=...)`, preflight runs before `_root` and
SQLite access. It requires the fixed `shinka` identity, the matching caller
producer ID, producer fingerprint, contract digest and optional run-id. A matching
foreign producer/binding pair is refused. Omission of run-id is normalized to the
binding run-id. Drift returns `shinka_binding_mismatch`; the post-read full result
binding verifier remains mandatory.

## Failure matrix and evidence

The focused regression covers OpenEvolve foreign run-id/evaluator drift and Shinka
foreign run-id/contract/producer drift, including mutually matching foreign binding
and caller IDs. It asserts that external-root access and the evaluator are not
called on refusal. The latest local three-suite selection passes 60 unique cases,
with zero failures, errors or skips. This count is local evidence only; the merged
code still awaits completion of the post-merge main CI run `38331781593`.

This contract does not close the remaining P0/P1 runtime gates: sealed CPython
installation/startup, real process lifecycle and interruption observation, actual
OpenEvolve/Shinka campaigns, or production CLI acceptance.
