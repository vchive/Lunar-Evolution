# Fixed-source broker pin refresh — 2026-10-30

## Observed failure and scope

Final-source CI 40909497309 preserved 28 OpenEvolve/Shinka preparation failures
per Python version. The source-only preparer correctly refuses the stale full
broker pin: its approved source was 17,877 bytes with SHA256
`cc5bb8b98a8c8a3e2d803843774351391dc00725e1c9231e18eb83680241c144`;
the current reviewed host source is 29,029 bytes with SHA256
`ab9d1f33200b2fd95dfa27816a01ac3eabe2523159fd45c53c32a2930bfddfe7`.
The change adds host observation/ownership accounting, outside all selected
target-client definitions. This is an integration defect, not an upstream
archive change, external solver execution or failed model evaluation.

## Contract

Before refreshing the explicit full-source pin, compare every one of the 17
selected constant/definition source segments with the independently pinned
historical source from main. All segments and the complete generated target
are byte-identical. The target remains 8,143 bytes with SHA256
`5c0474648bf173f0d24a0fcc12e6d1eedc0d9b4169c3cab4d22def2ed38d43b0`.
Transport bytes and SHA remain unchanged.

Update only the reviewed full broker size/SHA; Shinka continues to share the
same strict preparation implementation. Preserve rejection of any unreviewed
source-byte drift. Add the independently historical target size/SHA assertions
to the existing exact-segment test, retaining all original AST/import, argument
and source-only claim checks. No generated source, archive, fixed entrypoint,
profile/schema or runtime default changes.

Prepared manifest source metadata necessarily records the newly approved host
source, so its digest changes. An old manifest pin is not authority for this
new manifest. No source preparation or test pass enables runtime/installation/
production admission or online publication.

## Validation

Run complete OpenEvolve and Shinka preparation, entrypoint and snapshot fixture
files together with the pending ancestry, native fixture and aggregation fixes.
Use local synthetic archives and inert fixture brokers only; do not call models,
actual solvers, WebAgent or remote evaluators. Preserve original CI failures.
Run Ruff, compileall and diff checks; final complete CI still gates main.


## Coherent focused verification

Frozen tree `28f7164b2ea5a5af061ca2f0b07cdcb7b4e5128d`, 2,741 tracked files:
ten complete affected files on Linux/Python3.12.3 passed408 cases with zero
failure/error and one Darwin-only skip, 409unique collected, 39.026092 seconds,
one dispatch and zero retry. Complete ancestry files on Darwin/Python3.11.15
and3.13.12 independently passed the same37 cases without skips, in1.076127 and
1.010370 seconds. Do not add repeated identities across versions. Source bytes
and modes stayed unchanged; exact collection/JUnit and module origins are
retained. Ruff, compileall and diff checks pass. Original unsuccessful CI
results remain unsuccessful; new complete CI is still needed before main.
