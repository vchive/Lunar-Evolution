# Feature 196 — owner publication task split

This tracking is subordinate to `publication-boundary.md`. PB-01 closes only the
worker mutation facade; no owner publication or native BRS availability follows.

| ID | Slice | Deliverable / dependency | Exit condition |
| --- | --- | --- | --- |
| PB-01 | Worker mutation refusal | Keep the named worker symbol/signature with unconditional fixed refusal; reject active BRS worker scope in generic and DRS mutation facades before plan parsing. Leave read-only resume and pin-only ready/ACK unchanged. | Real selected-worker tests before/after ACK show zero parsing/callback/transaction/ready/write effects and original ACK/result path still completes; DRS/direct generic compatibility passes. Implementation present in isolated branch; validation pending. |
| PB-01s | Native scheduler bypass refusal | At the original scheduler provider boundary, refuse a live BRS worker before the separate direct transaction route. Do not disable standalone pin-only admission. | Actual worker scheduler regression cannot reach producer/transaction; DRS scheduler/pin-only channel compatibility passes. Tracked separately from PB-01 implementation. |
| PB-02 | Online prepared bridge specification | Freeze live selected prepared request/response, original claim/running episode, handoff lifetime, exact owner/worker pins, callback/lock ordering and bounded evidence before implementing. Completed-return receipt cannot be used as a publication grant. | Independent design/source audit; no manufactured DRS context or new authority. Not implemented. |
| PB-03 | Owner bridge and lineage composition | After PB-02, add BRS-specific owner composition. Success retains existing before/prepared/staged/terminal; rejection retains original C1/provenance-P/C2. Reuse existing native transaction and exact captured-head CAS/read-back. | Real owner thread alone performs lineage/publication; worker only submits/waits; no DRS gate relaxation, duplicate evaluation or schema/cap widening. Not implemented. |
| PB-04 | Unknown/recovery | Define original-pin inspection/reconcile for each missing or ambiguous success/rejection boundary; preserve durable marker and stale owner head. | No launch/evaluation/publication retry, current-file adoption, repair, budget refresh or successor. Not implemented. |
| PB-05 | Serial ordinal transition | Fresh next handoff only after exact native terminal/result and complete preceding owner lineage acknowledgment. | Original reservation/M0 retained; nonce/journal/claim/receipt uniqueness and exact verified head. Not implemented. |
| PB-06 | Policy/memory composition | Keep existing owner success/rejection memory/result policy separate from immutable candidate publication. | Rejection changes no published head or memory; workers never promote memory. Not implemented. |
| PB-07 | Independent acceptance | Focused exact inventory/raw XML, static checks, installed-source identity, independent review and final-source CI. | Actual observed counters/hash only; no design-only task marked complete. |

PB-01 can be implemented independently because it grants no new authority or
publication path. PB-02/PB-03 cannot be safely treated as a completed-return facade;
they require the prepared-stage online lifecycle above. PB-04/PB-05 depend on that
contract and complete durable acceptance.

P2 remains separate: concurrent/multiple native children, external worker transport
and authentication, multi-machine ownership, public native BRS/CLI enablement,
sealed runtime and real campaigns. No service API or automatic repair is implied.
