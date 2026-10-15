# PB-03d — private BRS staged/terminal checkpoint primitives

This slice extends the ephemeral original BRS checkpoint owner from the adjacent
before/prepared-reference/prepared-evidence sequence to two success evidence CASes.
It consumes already retained descriptors, snapshots and transaction files; it does
not create, evaluate, stage, commit, publish or repair candidate evidence.

The exact owner thread retains the original run lock, running run/episode, started
claim with no result, original policy/history, request/memory/plan, frozen checkpoint
head/payload, selected handoff/channel and live source/configuration gates. Each
checkpoint changes only `producer_publication_lineage`, uses the captured-head CAS
once, and advances shared/captured state only after exact head/payload readback and
the original producer-binding validation. Any exception poisons the ephemeral owner;
an ambiguous durable write preserves its original stale capture and durable files.

`checkpoint_staged(wire)` is available only after prepared-evidence and accepts the
same first batch plus the exact staged descriptor, after snapshots, source pins,
projection digest and three staged evidence pins. It validates original immutable
journal fields/candidate mapping, real preflight/manifest/material/handoff evidence,
all snapshot bytes, unchanged before sources and actual staged sources, and the full
deterministic population transition projection. The published head stays absent.
The staged projection uses exact source bytes from verified manifest materials,
because new candidates are not yet installed at their live code paths. Added
archive DTOs must equal their manifest-bound `record.json`; coherent replacement
archive/state hashes do not substitute for that binding. Terminal repeats this
record/material check against the live candidate tree.
For bundle-backed records, the parsed bundle digest must equal both the record's
bundle evidence and the original prepared candidate's bundle digest. Its contract
and entrypoint/code path must agree, and every source size/SHA must match both
the publication descriptor and the bundle declaration. Generic retained candidates
remain supported. These consistency checks do not add native receipt authority.

`checkpoint_terminal(wire)` is available only after the staged CAS and accepts the
same staged batch plus its exact success descriptor, published journal, terminal
files and live head source pins. The common terminal reader verifies the complete
original evidence and transition projection. Live archive/state must have the exact
after bytes and source identity; the publication marker must be absent. The one
lineage head is the verified terminal descriptor. This does not settle the native
episode, complete its claim, promote memory or permit a next ordinal.

The existing terminal schema requires a task created for the selected episode.
Both success entry points reject unless the original plan's `task_id` equals the
original request's `episode_id`, before any staged checkpoint write. Legacy root
task bindings such as `task-1` retain their before/prepared support and cannot be
rewritten or adopted into this success path. The fixture creates the per-episode
task in the original launch intent before the sidecar or run exists. Shared DRS
reader behavior is unchanged; this slice does not close general BRS composition.

Full projection verification requires the original gateway's native context and
exact `PopulationStrategy`. The constructor freezes the original producer config,
inputs, native context, strategy, strategy context/config/authority and workspace.
Missing native context remains compatible with before/prepared but cannot acquire
one later or use staged/terminal. No caller-supplied strategy or DRS flow context is
accepted. Live identities/configuration and the original bound sidecar/ledger are
checked again before each success checkpoint. This is a read-only dependency pin,
not a production capability.
Nested non-slotted configuration, authority and contract DTOs are checked against
their exact trusted class fields before the first snapshot and every live reuse;
instance serializer/field-table shadows are refused before callbacks. Projection
dependencies, native context helpers, seed classification and the original family
repertoire data are included in the policy pin.

Tasks:

- [x] Freeze the optional original native strategy and explicitly fingerprint new
      live verification dependencies without changing DRS publication policy.
- [x] Validate strict adjacent staged and terminal deltas and complete evidence.
- [x] Reuse the original captured-head CAS/readback without head refresh or retry.
- [x] Add inert genuine-owner tests for both success checkpoints and gate failures,
      including source/inode drift, missing original native inputs, phase skips,
      competing CAS and ambiguous readback. Forbid external execution/transactions.
- [ ] Run the focused owner/policy/kernel tests, Ruff, compileall and diff checks;
      retain initial failures and report exact source/observed counts.

Development qualification is not final acceptance. The expanded module currently
collects 70 cases; development selections passed 14, 6 and the 5-case genuine
bundle declaration selection (success, changed source size/SHA, changed digest,
and mismatched entrypoint). The earlier 97bb774 Mac/Linux runs predate this last
bundle consistency fix and are retained without promotion as final acceptance.
Earlier fixture/discovery failures and the later family-proxy/classmethod-pin
failures are retained under ignored development evidence. Final Mac/Linux runs
must use one immutable integrated source, their own editable installs and temporary
roots, raw stdout/JUnit/exit records, distinct collection inventory and unchanged
tracked source snapshots. No counts are promoted from older source runs.

`online_publication=false`, `production_admission=false` and the public native BRS
refusal remain unchanged. Online mailbox/controller/scheduler composition, rejection
C1/P/C2, reconcile, serial successor and policy/memory composition remain open.
