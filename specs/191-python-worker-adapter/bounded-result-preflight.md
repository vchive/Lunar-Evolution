# Bounded external-result preflight

Status: provider-free implementation on PR82 (`6b4e841`), with final CI and merge
pending. It is documented alongside the corrected PR80 prepared-boundary bridge
head (`94a2ec2`); the earlier bridge head `6770650` is superseded. This slice narrows the OpenEvolve handoff boundary; it does not launch a
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

## Failure matrix and evidence

The focused regression covers foreign run-id and evaluator fingerprint drift and
asserts that `_external_root` and the evaluator are not called. Independent replay
runs 77 unique cases (8 binding-export, 49 adapter, 20 OpenEvolve handoff), with
zero failures, errors or skips. This count is local evidence only; PR82's required
CI and merge are still pending.

This contract does not close the remaining P0/P1 runtime gates: sealed CPython
installation/startup, real process lifecycle and interruption observation, actual
OpenEvolve/Shinka campaigns, or production CLI acceptance.
