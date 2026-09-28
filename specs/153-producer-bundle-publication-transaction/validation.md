# Feature 153 validation

## 2026-09-29 repeated producer admission in the initial population window

The native transaction can append a fresh producer batch to an iteration-zero running
population. It validates strict prior-event schema and archive order, candidate lineage,
complete producer provenance and retained source-manifest digests before evaluation. Fresh
candidate and bundle IDs cannot collide with archived IDs. Each admitted subset appends one
event; existing archive bytes, candidate files/inodes and prior events are preserved.

Staging independently checks canonical admission-event bytes (including JSON number/boolean
types) and refuses dropped history or integrity markers. Repeated publication passes bounded
active-population, independent archive/receipt, delivery and population-resume checks. A rejected
second batch leaves the first state unchanged; exact rejected-terminal retry runs no evaluator.
Pre-stage retry reuses completed native evidence, while missing completion evidence rejects
continuation without replaying the earlier work.

Transaction/staging/recovery/native-intent selection: **68 passed**, 23.18 seconds, JUnit
`/tmp/lunar-repeat-combined-v2.xml`. Final marker-downgrade/staging selection: **18 passed**,
JUnit `/tmp/lunar-repeat-first-marker-v2.xml`. These selections overlap. Ruff and
`git diff --check` pass. All cases use local fixtures and local subprocesses only.

This completes T153-06g, not evolved/seeded population admission, unknown-result reconciliation,
automatic delivery orchestration, an external launcher/scheduler, or real campaign acceptance.
The older entries below describe the restrictions at their original validation checkpoints.

## 2026-09-29 durable deadline and active subprocess controls

The native controlled path now retains the original monotonic deadline, full prepared-journal pin,
boot UUID, and file identity. Same-boot process restart does not refresh allowance. Injected fixture
clocks require the original strongly retained object token. Missing/changed clock evidence or a
changed boot rejects continuation. Publication lock ownership is rechecked at mutation boundaries.

Candidate and evaluator selector loops now poll the same control while running, terminate the
private process group on cancellation/expiry/control failure, and retain a bound interruption
observation before re-raising the stop. Unconfirmed cleanup stays unknown. Stopped candidates
cannot acquire completion authority; stopped evaluators have no authoritative score. Native
transaction regression checks unchanged archive/state and no attempt replay after an active stop.

Focused active-process tests: **8 passed**. Combined native execution/evaluation/process release,
producer controls/deadlines/non-publishing drafts/population selection: **155 passed**. Ruff and
`git diff --check` passed. Counts overlap and are not additive.

No model, network evaluator, WebAgent or external campaign is used by this regression. Full
unknown-attempt reconcile, launcher/scheduler, and real OpenEvolve/Shinka acceptance remain open.

## 2026-09-29 active controls and durable all-rejected terminal

The native transaction accepts a caller-owned active clock, composes tighter parent controls,
and checks cancellation/remaining time before admitting preparation, drafts, staging and commit.
Publication lock waits are polled with the same control; typed timeout/cancellation exceptions
survive lock and terminal wrappers. The final commit checkpoint precedes the durable unknown
marker; after that boundary the commit completes without misclassifying published output.
Budget digests derive from actual native policy even when the optional control is omitted.
An explicit old digest cannot remove a control or silently change execution limits on retry.

All-rejected local evaluations now have a durable `all_rejected/committed` journal, unchanged
archive/state after digests, complete rejected receipts and retained evidence descriptors.
Independent inspection rebuilds receipt content from original native records rather than trusting
portable self-digests. Exact terminal retry returns no evaluations, and partial/missing/tampered
evidence fails closed. The covered rejection slice is successful execution followed by local
evaluation validity zero; unknown/nonzero/timeout outcomes are not promoted to this terminal.

Final isolated-worktree selection: **510 passed / 0 failed / 0 skipped** (60.27 seconds), including
all producer-bundle suites, Shinka handoff, non-publishing drafts, bundle population/controller/CLI,
native evolution, quality/diversity and solve lifecycle. JUnit:
`/tmp/lunar-shinka-20260929-controls.xml`. The selection includes real local file-lock contention,
budget/cancel propagation, no-replay terminal retry and rehashed portable-receipt tampering.
Whole-tree Ruff, compileall and `git diff --check` passed. Earlier focused counts overlap this
selection and are not added to its count.

The independent worktree remains `codex/shinka-native-publication`; RSI files/implementation were
excluded. No model, WebAgent, remote evaluator or real OpenEvolve/Shinka campaign ran. Full
unknown/interruption recovery, evolved/seeded/repeated population admissions,
launcher/scheduler integration and the three-phase release runner remain open. Same-boot durable
deadline restoration and active-subprocess cancellation were subsequently implemented in the
integration worktree; see the current validation above. This does not complete P1 production acceptance.

## 2026-09-29 offline native transaction and prepared intent

The Shinka SQLite fixture now traverses export, explicit grouping, Feature 152 plan, native
non-publishing draft execution/evaluation, atomic stage/commit, archive/state read-back, native
population resume and portable delivery inspection. Local scores determine admission; producer
scores are provenance only. A valid low-scoring import remains archived without displacing an elite.
The supported initial window rejects offspring history, seed/prior producer admission, terminal
state, live strategy drift and mutated source/provenance before the first candidate execution.

The complete prepared journal is durably created before execution. Every transaction draft binds
its digest. Exact pre-stage retries reuse retained completed evidence without rerunning execution
or evaluation; changed task/run/parent/budget and missing or changed intent fail closed. Stage,
commit and recovery independently bind the retained prepared intent to the actual publication
journal; dropping evidence/binding/intent or changing the request cannot downgrade the check.

Validation used an isolated checkout on `codex/shinka-native-publication`, excluding the separate
incomplete RSI commit and its untracked dependencies:

- Native transaction, prepared intent, non-publishing draft, receipt, retained recovery and native
  publication-intent selection: **64 passed**.
- Shinka export, admission/preflight/publication/staging, bundle population, native evolution and
  quality/diversity selection: **319 passed**.
- Final changed publication-intent/staging/recovery/retained-recovery/transaction selection:
  **44 passed** after the last review fixes.
- Ruff (`src tests tools`), compileall and `git diff --check` passed.

These selections overlap; their counts are not a unique total. A preceding working-tree current
product pytest run also exited successfully, but predates the final intent changes and is not
used as final release qualification. The three-phase historical/frozen release runner was not
rerun. No model, WebAgent, real OpenEvolve/Shinka campaign or remote evaluator was invoked.
Shared transaction deadline/cancellation, durable all-rejected terminal state, full unknown-attempt
recovery, evolved-population import and launcher/scheduler production integration remain open.

## 2026-09-28 preflight-to-stage binding

Staging reparses the read-only preflight receipt before any write, then binds its run/task,
admission plan, archive/state prefix, authority digest, and ordered candidate IDs to the
publication journal. Under the publication lock it also checks the retained archive record
count before creating the stage. A stale or cross-batch receipt fails closed without a stage
or publication marker. Focused provider-free tests cover every mismatched field, a mutated
receipt digest, and record-count drift.

T153-01 and T153-02 provide the provider-free canonical journal, deterministic candidate IDs, and
zero-write admission preflight. T153-03/T153-04/T153-05 are now implemented. The staged
transaction writes candidate source trees, record/receipt sidecars, archive/state snapshots, and a
system-owned marker below the derived producer-batch directory. Publication takes an exclusive
workspace lock, verifies every staged byte and any recorded device/inode/mtime/ctime identity,
changes the marker to a durable unknown state before the first move, and removes it only after the
terminal journal and after-digests are durable. Known rejected items may remain in a mixed journal
while admitted items are published as one batch; an all-rejected batch has no archive/state side
effect.

Resume accepts only the exact plan, authority, preflight, journal, and ordered admitted subset. It
rechecks staged or published trees and rejects unknown markers, prepared journals, stale bytes,
identity drift, duplicate publication, or terminal evidence changes without invoking a producer or
evaluator. The native archive reader also fails closed while the durable publication marker exists.

The combined Feature 153 journal, preflight, staging, recovery, and marker selection passes **40
tests** at the current checkout. That historical entry did not retain an exact full-suite count, so it is not used as current
release qualification. The dated checkpoints below record the native integration separately.
This feature does not start a launcher, scheduler, external producer, provider, or real campaign.
