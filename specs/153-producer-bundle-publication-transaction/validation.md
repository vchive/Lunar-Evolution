# Feature 153 validation

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
tests** at the current checkout. The full current product regression passes (**7,2xx passed, 1
skipped**; the exact count is emitted by the local pytest run) with only pre-existing temporary
directory cleanup warnings. Ruff, compileall, diff, and legacy-name scans pass. T153-06 remains
intentionally deferred: this feature does not start a launcher, scheduler, external producer,
provider, or real campaign.
