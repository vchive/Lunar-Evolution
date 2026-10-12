# Implementation plan

1. Keep the retained source immutable and path-free in the controller fingerprint.
2. Map the existing read-only replay report into `SolverResult` using canonical parsing.
3. Represent missing receipts as unknown evidence and refuse all drift before result reuse.
4. Add a generic controller cached-result validation hook for explicitly opted-in replay gateways.
5. Cover complete, unknown, request mismatch, drift, and cached-result replacement fixtures.

The implementation remains provider-free and does not widen the production admission boundary.
