# PB-06 — policy/memory composition boundary

This slice makes the existing BRS publication and RSI memory policies explicit at their shared
boundary. It is provider-free and does not enable public native BRS. A selected worker and its
result delivery can carry evidence, but neither can create, activate, or revoke an RSI memory
admission.

## Evidence and ownership

`BRSImmutableCandidatePublication` is an owner-created, content-addressed projection of one
request-bound native candidate and its publication receipt. It includes the request and frozen
memory pins, the selected-candidate digest, the publication receipt, and the captured owner
lineage head. Rebuilding the detached candidate/publication records and recomputing this digest
happens before policy evaluation. A worker result, ready/ACK, terminal status, or rejection record
is not accepted as a publication object.

`BRSPolicyMemoryComposer.compose_success` separately requires:

- the request's memory digest to equal the detached parent snapshot;
- the candidate snapshot to be a new snapshot whose parent digest is exactly that parent;
- all inherited items to be byte-identical and exactly one new approved item tied to this episode;
- an independent passing verifier with matching episode, contract, evaluator, environment, and
  item receipt pins;
- the immutable owner publication and its captured lineage head.

The output is a `candidate_pending` decision. It is an evidence decision, not an activation or
publication capability. `admit_candidate_shadow` can append only the existing governance edges
`observed -> verified -> candidate -> shadow`; it never touches `RSIMemoryStore` and cannot append
`approved` or `active`. The existing `MemoryPromotionAdapter` remains the only explicit transfer
regression promotion boundary.

`compose_rejection` is a separate policy path. It records the rejection receipt and reason for
that request but emits no candidate snapshot, publication digest, or verifier receipt. Rejection
therefore cannot move a published head, invalidate an unrelated publication, or become a memory
promotion token.

All decisions and publication projections are canonical, digest-bound, and reconstructable. Snapshot,
policy, compatibility, source episode, and admission reason drift are refused; exact replay of the
same shadow admission is read-only.

## Non-goals

This document does not define external worker authentication, multi-machine ownership, official
or remote evaluation, a new persistence schema, or automatic transfer regression scheduling.
Production/public BRS remains disabled.
