# Feature 153 validation

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
