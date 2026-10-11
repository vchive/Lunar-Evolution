# Controller-bound publication and recovery

## Bounded continuation

Compose the existing explicit durable admission reference with standalone publication.
This slice requires an already pinned row/reference; it neither creates the first pin nor
changes controller flow state. Automatic scheduler pinning stays open: its late evidence
is unavailable before the prepared publication boundary, current native scheduler inputs
do not include Python runtime/handoff material, and BRS mutation ownership needs a separate
design. Do not invent those inputs or claim production admission.

Expose `run_rsi_python_bundle_publication` and `resume_rsi_python_bundle_publication` in
`rsi_python_publication.py`. Both require the exact controller, run and episode IDs, and
the caller-retained admission-record SHA256. Read the verified checkpoint reference for
that episode, require its record identity to match, and capture the complete canonical
reference once. Derive workspace, native plan, prepared journal and publication identities
from that retained reference; do not accept replacement identities or latest-file adoption.
The caller supplies the existing admission plan and, for publication, strategy and drafts.
Plan digest must match the original prepared journal before transaction/evaluator I/O.

## Required gates

Entry, stage/timeout and final-return checks require the unchanged captured reference,
same retained row and original proof/sidecar/handoff/prepared/anchor files. Use the existing
controller read-only reference gate and evidence validator; do not acquire a mutation lock,
repair evidence, change checkpoint heads, reserve budget or refresh deadlines. A new facade
always supplies the evidence gate. Omitting an optional continuation callback must not
remove that gate. Standalone generic publication retains its behavior and golden wires.

Each ledger observation uses a nested, per-ledger, per-thread read-only connection scope.
SQLite opens with URI `mode=ro`, without creating directories/databases or switching journal
mode. Missing evidence between the file check and SQLite open must refuse without rebuilding
it; replacement with an empty database must refuse without modifying its journal mode.
The scope ends before publication work or caller callbacks, so ordinary ledger writes retain
their existing behavior. It does not provide a transaction across the database and proof files.

The transaction gains an optional read-only evidence revalidator. Invoke it after caller
checkpoint and timeout callbacks return, before subsequent evaluator/staging/commit work;
invoke it at all successful terminal/final return boundaries. Preserve existing cancellation,
absolute deadline and commit-critical-region semantics. A refusal before commit adds no
publication; a refusal after an existing commit/unknown marker preserves durable evidence
and does not roll back, repair, retry or acknowledge uncertain effects.
Sample caller cancellation predicates before the final evidence observation. After observation,
check only the retained absolute deadlines and, when explicit control is bound, its local cancel
flag; do not replay caller cancellation, guard, budget or stage-observation callbacks after that
gate. Ordinary checkpoints without explicit control capture their parent timeout callbacks before
evidence, independently of the numeric timeout wrapper. Numeric timeouts are reduced by the
observation elapsed time exactly once. Post-commit verification does not add a new budget gate.

Recovery wraps the existing read-only standalone reader with entry/final reference checks.
Use the original prepared journal to establish immutable authority, allowing only its existing
verified publication projections. Unknown/missing terminal behavior stays unchanged.
Do not insert the admission record digest into the same prepared journal: the record already
binds that journal's digest, so this would create a digest cycle and alter original bytes.

## Focused verification

Use local inert fixtures for successful publication and read-only replay, required row/reference
loss or replacement, wrong expected identity/plan, file drift, mutation by caller checkpoint or
timeout callbacks, and terminal-return drift. Check that entry failures do not call the evaluator
or change ledger/files/budget. Check later refusals retain only effects already durable.

Add a crash regression that injects failure after the first candidate replacement succeeds in
the commit critical region. Keep the unknown marker and partial material; recovery must refuse
without evaluator retry, budget change or file repair. This closes one real interruption window,
not the complete CPython process/runtime/journal matrix.

Run focused tests, relevant compatibility tests, Ruff, compileall and diff checks. Final source
still requires complete three-version CI and independent audit. `production_admission=false`;
no actual CPython/toolchain acquisition/build/execution, real solver campaign, WebAgent or
remote/company evaluator is permitted. Separate file reads and SQLite remain non-atomic
against a hostile concurrent writer; coherent rewrite of every trusted pin is outside this model.
