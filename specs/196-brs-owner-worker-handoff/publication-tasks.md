# Feature 196 — owner publication task split

This tracking is subordinate to `publication-boundary.md`. PB-01 closes only the
worker mutation facade; no owner publication or native BRS availability follows.

| ID | Slice | Deliverable / dependency | Exit condition |
| --- | --- | --- | --- |
| PB-01 | Worker mutation refusal | Keep the named worker symbol/signature with unconditional fixed refusal; reject the original BRS invocation (entry/source hooks, active/dispatch and nested suppression) in generic and DRS mutation facades before plan parsing. Retain a negative invocation marker through finally; grant no new authority. Leave read-only resume and pin-only ready/ACK unchanged. | Real selected-worker tests before/after ACK show zero parsing/callback/transaction/ready/write effects and original ACK/result path still completes; DRS/direct generic compatibility passes. Implemented; 261-case integrated local focused acceptance and static checks passed. Independent audit and final-source CI recorded separately. |
| PB-01s | Native scheduler bypass refusal | At the original scheduler provider boundary, refuse the BRS invocation before input/context callbacks or the separate direct transaction route. Do not disable standalone pin-only admission. | Implemented in combined slice; 261-case integrated local focused acceptance passed, including 14 scheduler join cases. Final-source CI pending. Actual worker scheduler regression cannot reach producer/transaction; DRS scheduler/pin-only channel compatibility passes. |
| PB-02 | Pre-publication bridge specification | Freeze receipt/output/handoff request/response while claim/episode are naturally started/running, handoff lifetime, exact owner/worker pins, callback/lock ordering and bounded evidence. The owner transaction creates the prepared journal/anchor. Completed-return receipt cannot be used as a publication grant. | Design in `owner-publication-bridge.md`; implementation remains open, with no manufactured DRS context or new authority. |
| PB-02a | One-shot mailbox transport | Exact original-handoff/owner-worker/captured-head request/response transport. Independent of admission ready/ACK; no controller/scheduler or publication authority. See `publication-mailbox.md`. | Implemented in successor candidate; 872-case integrated Linux focused/install/static acceptance passed; independent evidence/source review passed; final CI remains open. Complete online owner integration stays open. |
| PB-02b | Private producer-only preparation | Run the original receipt/output/handoff stages and stop before transaction, evaluation, admission and lineage. Recheck original handoff file/control pins after final hooks; returned DTOs carry evidence only. | Implemented with 158 local scheduler/join cases; the later frozen Linux foundation `e30f5f8` passes 450 distinct cases and independent raw/source review. These overlapping results are not summed. Online mailbox/owner composition and final CI remain open. See `prepublication-preparation.md`. |
| PB-03a | Pure checkpoint delta/readback helpers | Extract one-field lineage delta and already-observed head/payload comparison. Preserve original DRS facade, strict serializer, capacity, CAS/readback and context/root-binding order. Bind both live helpers explicitly in policy fingerprints. | Implemented at `3c0d74e`; 15 new plus 2 original success/rejection cases pass with zero failures/errors/skips; static, install/source and raw evidence reviews pass. No BRS owner, policy migration or online publication authority is added; complete PB-03 and final-source CI remain open. |
| PB-03b | Private BRS before/prepared checkpoint primitive | Exact original BRS owner captures a first `before` descriptor, then verifies the actual adjacent prepared admission-reference CAS and writes its own prepared evidence-pin CAS. Reuse pure delta/readback helpers, strict checkpoint capacity and shared ready-capsule/snapshot accounting. | Implemented at `309ce16`; **40 = 37 new + 3 original** local focused cases pass with zero failures/errors/skips, all seven exit records zero, static/install/source verification passed. That source pins policy only at construction; PB-03c adds the original durable pin. No staged/terminal/rejection/reconcile/successor or native dispatch authority. See `publication-validation.md`. |
| PB-03c | Persisted original BRS checkpoint policy | For new exact-sidecar, single-worker BRS runs, retain a dedicated non-authorizing policy in the original create-run payload, run fingerprint and all checkpoints. Validate complete history and reject legacy missing pins without migration. Preserve DRS/provider-free/multiworker field selection. | Implemented at `399958c`; **402 = 21 new + 381 original** frozen local cases pass with zero failures/errors/skips, nine exits zero and 2,038 tracked source files unchanged. Independent code review passed. No public flag, wire/SQL schema or execution grant. Final integrated-source CI remains separate. See `prewave-policy.md` and `publication-validation.md`. |
| PB-03 | Owner bridge and lineage composition | After PB-02, integrate the private BRS primitives and original persisted policy with the online mailbox/controller/scheduler lifecycle. Success retains existing before/prepared/staged/terminal; rejection retains original C1/provenance-P/C2. Reuse existing native transaction and exact captured-head CAS/read-back. | Real owner thread alone performs lineage/publication; worker only submits/waits; no DRS gate relaxation, duplicate evaluation or schema/cap widening. **Open**: PB-03b/PB-03c close only the before/prepared checkpoint primitive and original policy persistence. |
| PB-04 | Unknown/recovery | Define original-pin inspection/reconcile for each missing or ambiguous success/rejection boundary; preserve durable marker and stale owner head. | No launch/evaluation/publication retry, current-file adoption, repair, budget refresh or successor. Not implemented. |
| PB-05 | Serial ordinal transition | Fresh next handoff only after exact native terminal/result and complete preceding owner lineage acknowledgment. | Original reservation/M0 retained; nonce/journal/claim/receipt uniqueness and exact verified head. Not implemented. |
| PB-06 | Policy/memory composition | Keep existing owner success/rejection memory/result policy separate from immutable candidate publication. | Rejection changes no published head or memory; workers never promote memory. Not implemented. |
| PB-07 | Independent acceptance | Focused exact inventory/raw XML, static checks, installed-source identity, independent review and final-source CI. | Actual observed counters/hash only; no design-only task marked complete. |

PB-01 can be implemented independently because it grants no new authority or
publication path. PB-02/PB-03 cannot be safely treated as a completed-return facade;
they require the pre-publication online lifecycle above. PB-04/PB-05 depend on that
contract and complete durable acceptance.

PB-03b/PB-03c retain `production_admission=false` and `online_publication=false`; the
genuine selected-service fixture keeps `producer_multi_episode_publication=false`.
PB-03c adds `producer_brs_checkpoint_policy` to the original pre-wave run policy,
its fingerprint and each checkpoint. PB-03 must still compose the online owner
transaction and result delivery. Staged/terminal, rejection
C1/P/C2, read-only reconcile, serial successor and policy/memory composition stay
open. The original failed development/review runs are retained separately from the
40-case and 402-case source acceptances, which are never added into one counter.

P2 remains separate: external worker transport/authentication, multi-machine ownership
and distributed services. Public native BRS, serial multi-child publication, sealed
runtime and real local producer/CLI acceptance remain open P1 work in the release
backlog; this refusal slice does not reclassify them as P2. No service API or automatic
repair is implied.
