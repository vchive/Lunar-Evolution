# Feature 191 — bounded local interruption and recovery matrix

## Contract

Observe the existing controller, Python process recovery and publication entry points
against actual local SQLite rows and retained journal/proof files. This slice adds
acceptance tests rather than a launcher, solver, wire format or additional validation
layer. Runtime files contain inert fixture bytes. `production_admission=false` remains
mandatory. No CPython execution, toolchain, provider, network, WebAgent or remote evaluator
is permitted.

An interrupted attempt retains its first uncertain boundary. Reopening a controller or
repeating the original run cannot authorize a second dispatch, callback, cleanup,
evaluation or publication. Retain the original checkpoint, planned/consumed/remaining
budget, absolute deadline, producer pin, admission reference and existing publication
effects. Recovery must not remint missing proof, advance a checkpoint, reserve an
unknown retry, refresh a deadline, acknowledge unknown effects or repair evidence.

## Matrix

1. A gateway interrupted after running episode/intent persistence and before result
   persistence, with original Python admission pinned: fresh controllers must refuse
   ordinary resume, resume after the original deadline and replay of the same run request.
2. Verifier, judge and curriculum response loss after durable callback start: producer-bound
   controllers must quarantine resume and the original run request before any new work,
   including after the deadline. No implicit reconciliation reservation is allowed.
3. Actual process files at claim-only, registration-only, unknown-terminal,
   mismatched-journal and uncertain-cleanup boundaries: existing no-cleanup recovery must
   refuse repeatedly without changing existing recovery locks, receipts or retained files.
   A complete native fixture receipt
   lacking runtime/broker observations remains unknown and cannot confer publication.
4. Actual publication prepared state without a current projection, malformed current or
   staged journal, unknown journal, immutable journal mismatch, published state with
   missing staged evidence or missing/mismatched terminal and
   interruption after candidate/archive/state moves but before terminal persistence:
   fresh controller-bound recovery must refuse without retry, rollback or repair. The
   final interruption differs from the existing first-candidate rename regression; the
   unknown marker and every already-durable material must remain unchanged.

Use real existing persistence/read/recovery operations. A process receipt fixture is
not an observed process identity or evidence of sealed runtime acceptance. Preserve the
first failing JUnit separately, fix only demonstrated defects within the existing
contract, and run a newly named final JUnit, Ruff, compileall and diff checks. The final
source still needs independent review and three-version CI.

## Demonstrated defect and local validation

The first run exposed one production error-contract defect: a missing or malformed
durable publication journal leaked `ProducerBundlePublicationError` through controller
recovery instead of returning its fixed recovery code. The existing recovery reader now
converts journal parser failures to
`ProducerBundleRecoveryError("producer_bundle_recovery_journal_invalid")` for durable,
staged and terminal journal reads. This changes neither successful publication nor the
wire format and adds no new admission authority.

The final matrix contains 24 parameterized cases covering all four groups above. The
first failing report is retained separately from the corrected-fixture and final
reports under `.lunar-evolution/reports/python-interruption-matrix-20261012/` in the
primary checkout. The final report records 24 passes with no skips on Python 3.11.15.
The compatible inert `test_producer_bundle_recovery.py`,
`test_python_producer_recovery.py` and `test_rsi_python_publication.py` tests record
75 passes with no skips. Ruff, compileall and `git diff --check` also pass. This is
local evidence only; it does not confer production admission.

## Scope limits

This is a bounded local matrix, not the full live scheduler/runtime interruption matrix.
It does not validate actual gate delivery, process death, runtime journal generation,
sealed CPython, native broker lifetime, real solver lifecycle/export or hostile coherent
rewrite of every trusted file. Those remain separate P0/P1 acceptance work. Authentication,
multi-host ownership, service scheduling and remote evaluation remain deferred.
