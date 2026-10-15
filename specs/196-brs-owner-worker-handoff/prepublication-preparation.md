# PB-02b — private producer-only Python preparation

This slice supplies the missing stop boundary between receipt/output/handoff creation
and owner publication. It does not grant BRS publication authority or wire the public
RSI provider. The original BRS provider refusal remains in place.

Status: private seam implemented; 67 new cases and 91 existing scheduler/join/outcome
cases pass locally (158 distinct, zero failures/errors/skips). The later frozen Linux
foundation `e30f5f8` passed 450 distinct cases, including these scheduler/parser and
checkpoint boundaries. Its exact XML, all 14 exits, own editable imports and all
2,036 source/Git blobs passed independent review. These overlapping source results
are not added together; the successor integrated-source run and CI remain separate.

The private scheduler entry accepts the existing launch inputs, one handoff supplier
and one evidence revalidator. It has no strategy, prepared observer, lineage owner,
publication callback or retry input. Its one attempt runs the normal strict receipt
and output projections, then validates the original creator's handoff file pin using
the same execution/admission/launch/contract bindings as the existing DRS join.

Before launch and before returning, the caller's revalidator runs under the original
lifecycle budget. After the return revalidator, the original file pin and execution
digests are checked again; current-file adoption is forbidden. A failure preserves
existing process/receipt/output/handoff evidence and returns no preparation result.
Cancellation and deadline exceptions retain their original types. No transaction,
evaluation, prepared journal, admission pin or lineage checkpoint is performed.

Full canonical receipt/output snapshots include nested owner/trusted evidence,
draft source/metadata and envelope data, rather than relying only on cached SHA
attributes. The receipt is strictly reparsed. Original and composed control fields,
clock/observer/lock identities and cancellation callback membership are frozen;
hook or observer drift refuses. Local cancellation remains allowed. The final stage
observer is followed by another read against the same original file pin, covering
metadata changes and same-bytes inode replacement. Preparation data remain mutable
DTOs after return; a later owner must independently reconstruct/revalidate them and
check its own original lifecycle before admitting a new stage.

The result contains the normal preparation-only run and a detached strict handoff
sidecar. It is evidence for a future original-owner request, never a publication or
completed-child capability. Original policy persistence is implemented separately in
`prewave-policy.md`. Online mailbox/worker composition, the complete owner transaction,
rejection C1/P/C2, recovery and ordinal transitions remain separate PB-03–PB-05 work.

Frozen Linux evidence is retained in ignored
`.lunar-evolution/reports/p1-integrated-linux-e30f5f8-20261015/`. The original
394-case Linux run at `200b6bb` had two decoder-depth oracle failures and remains
preserved. The tests-only portability follow-up accepts only the original schema or
JSON refusal at natural decoder depth and adds forced-RecursionError cases; it does
not change product parsing. The final 450-case source includes that follow-up.

Provider-free tests must cover the real handoff writer/reader with inert attempt,
receipt and output stages: stage ordering; transaction absence; bad bindings/pins;
supplier or return-hook mutation; cancellation/deadline at each new hook; and the
unchanged historical public scheduler join. No process/model/solver is executed.
