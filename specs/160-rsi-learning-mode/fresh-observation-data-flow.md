# Fresh observation data flow for the original reserved BRS owner

## Evidence and scope

The mixed three-child case at `11761700250457c06e7a2adc0d41d4082ffca261`
was terminated at its original 600-second allowance with zero retries. Retained
artifact consistency passed; the case did not pass. Its 120 sparse main-stack
samples show repeated reserved-history observations. Sample membership is not
CPU share, invocation frequency, or proof of a causal performance bottleneck.

The control chain can invoke the complete history walker at least five times
inside one timeout callback. The reader itself performs three complete history
SELECTs plus three for each earlier rejection on the ordinary live-wave path.
This continuation removes redundant data acquisition within one observation.
It introduces no new cache and does not enlarge the deadline or change retry
policy. End-to-end performance remains a separate acceptance requirement.

## Transaction boundary

The transaction owns the original BRS full postgate after every successful
evidence callback. A callback's type, attributes and return value confer no
permission to skip that gate. Generic transactions retain the original callback
behavior. The private native callback retains its full source/control checks,
the full gate after argument validation, all native receipt/handoff reads and
pin comparisons; its immediately duplicated final full gate moves into the
transaction. The common timeout path therefore performs four full history walks
instead of five, with the original handoff read and final numeric tail retained.

The common helper covers all eight evidence callback sites:

- preparation;
- original-owner checkpoint;
- generic checkpoint;
- evaluator timeout;
- rejected-terminal replay;
- all-rejected completion;
- postcommit;
- final return.

The original argument validator is deliberately still followed by its full
gate. Its nested context validation is not assumed to be a pure comparison.
Callbacks that fail still propagate their exception and cannot return success.
Locked checkpoint behavior and its callback-free fixed gate are unchanged.

## Complete fresh roots within one history observation

One complete fresh history read supplies explicit inputs to the adjacent-head
selector, original-checkpoint membership validation, prefix reader and pure
historical wire comparison. No arbitrary hook or physical observer separates
the initial read from the pure original/head checks. Public, worker and
finalization prefix readers continue to acquire their own independent history.
The prefix reader retains both complete coherent whole-domain observations,
their independent readbacks, controller-lease checks, all descriptor reads and
all physical inode/byte/mode checks.

The same complete roots may be passed to each earlier rejection's material
reader. That reader still performs its own full read after provenance recovery
and its own full read after physical/native material recovery. Explicit roots
are comparison data, never an execution capability. Standalone calls that do
not receive roots still obtain their own initial history.

A final complete history reselect must equal the initial history after all
physical observations. Equality includes every older row and all payload fields;
matching only the head is insufficient. Nothing is retained for the next call.
The ordinary live-wave path changes from `3 + 3R` complete history reads to
`2 + 2R`, where `R` is the number of earlier rejections. Explicit-state calls
remain bounded by the same `2 + 2R`. The four raw whole-domain snapshots remain.

## Validation and acceptance

Focused tests profile original functions without replacing them. They verify
two complete history reads, four complete raw domain snapshots, reuse of the
same explicit fresh roots only inside a call, and refusal of same-head older-row
mutation after prefix observation. Later calls must read current rows. Genuine
retained rejection fixtures verify the two internal fresh history reads and
physical material checks remain. Original-owner callback fixtures verify a
claimed `owner_checked` attribute/return cannot skip the full postgate and owner
mutation in a callback refuses before prepared effects.

The changed helper and pure input functions are part of the complete original
executable policy graph. Required checks are the joined focused suite, Ruff,
compileall and `git diff --check`, followed by one separately authorized mixed
attempt under its original deadline and zero retries. No timeout performance
or release completion is established by implementation or focused tests alone.
