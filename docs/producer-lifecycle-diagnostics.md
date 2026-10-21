# Producer lifecycle diagnostics

`lunar_evolution.producer_lifecycle_diagnostics` is the provider-free acceptance projection for
the P1 owner/lifecycle boundary. It consumes detached phase observations and reports whether the
following evidence slots are present:

- startup owner registration and a terminal receipt;
- active cancellation with owner-checked cleanup;
- an absolute deadline, including an explicitly preserved cleanup-unknown outcome;
- parent loss with read-only recovery and no relaunch;
- owner-checked cleanup;
- restart recovery that remains read-only and does not start a second attempt.

The projection is deliberately not a launcher or a recovery command. It does not spawn, signal,
relaunch, open a ledger, invoke an evaluator, or publish a result. A complete report is labelled
`offline_verified` and always retains `production_admission=false` and `online_publication=false`.
Missing or unsafe phase evidence is `blocked`; an `unknown` timeout or parent-loss outcome is
accepted only when the original uncertainty is durably preserved and no retry is claimed.

The module is intended to sit between retained Feature 156/158 process receipts and the future
Linux runtime acceptance matrix. It makes the required interruption cases explicit without
turning provider-free fixtures into real producer acceptance.
