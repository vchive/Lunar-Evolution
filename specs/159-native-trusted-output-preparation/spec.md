# Feature 159: native trusted output preparation

**Status**: Provider-free preparation plus restricted offline-import publication bridge; production egress and delivery remain open

## Problem

The native trusted runner can prove the pinned bootstrap and target process reached a verified
terminal state, but its process-only receipt says nothing about the producer's output bundle.
The cooperative direct-process adapter already verifies a multi-file bundle, but its process
path does not establish the trusted pre-gate boundary. Reusing that adapter would conflate two
different execution authorities.

## Outcome

`prepare_native_trusted_output` first recovers and verifies the exact native process terminal.
Only a zero-exit, gate-released, target-started, owner-cleaned terminal can proceed. It reads the
intent-derived `producer-result.json` under a byte bound and no-follow double-identity checks,
rejects duplicate JSON keys, compares producer, contract and declared request limits, then uses
the existing explicit-group source verifier, native draft projection and admission-plan builder.
The returned value binds the process terminal digest and exact envelope-byte digest to those
read-only results.

## Authority boundary

This is current-state preparation after the process terminal. It does not establish that output
bytes existed before the original wall-clock deadline, nor does a producer-declared request count
establish host-observed outbound traffic. The result is explicitly `publication_eligible=false`.
It writes no receipt, journal, archive, candidate, or campaign and does not run an evaluator.
The production runner must capture and durably bind output evidence within the same attempt and
join controller-owned request evidence before publication can use this result.

## Same-attempt capture progress

The native runner now reads the envelope and every declared source material after process cleanup
but before its original wall deadline, using bounded no-follow stable reads. It persists their
byte hashes and file identities in an exclusive receipt chained to the verified process terminal.
When the isolated target used the host broker, the closed request journal is independently replayed
within that deadline; its identity, exact byte hash, size, admitted count and declared-count match
are bound to the capture receipt. Read-only recovery rejects changed output or journal bytes.

This receipt remains `publication_eligible=false`. Its broker coverage is explicitly
`brokered_requests_only`; the remaining Feature 157/158 isolation and request-enforcement proof,
plus evaluator/archive publication integration, must be completed before publication.

Read-only preparation now has an explicit `require_same_attempt_capture` mode for the native
path. It recovers the durable capture before inspecting candidate files and again after building
the multi-file drafts and admission plan. Missing, changed or invalid capture evidence fails
closed; incomplete broker evidence or a mismatch between the producer declaration and host
admissions also fails. The result carries the capture digest and distinguishes brokered-only
request observation from declaration-only inspection. This mode still grants no publication
authority, since complete outbound coverage and the downstream execution transaction remain open.

## Restricted offline-import bridge

Feature 159 now provides a separate `offline_import` bridge for local, provider-free material.
It does not change the preparation receipt's `publication_eligible=false` meaning. A caller must
provide a one-shot authority whose token is retained only as a digest and whose fields bind the
launch, attestation, executable identity, process terminal, same-attempt capture, broker journal,
preparation receipt, source grouping and Feature 153 admission plan. The bridge reopens and
revalidates those records before invoking native local reevaluation and Feature 153 staged
publication. The authority is written with create-only semantics and consumed only after a
`published` or `all_rejected` terminal. Transaction failure, authority replay, field drift,
missing evidence and production scope are rejected.

This path is deliberately limited to offline import. Brokered-only request coverage is not a
complete egress proof, and the bridge does not enable production launcher/scheduler use,
cross-process unknown reconciliation, or automatic parent delivery.

## Acceptance

1. A verified successful native terminal and a valid explicit two-file group produce a native
   multi-file draft and admission plan with process and envelope digests.
2. Missing, failed, tampered or uncertain process evidence fails before reading output.
3. Symlink, replacement, duplicate-key, malformed, over-limit or identity-mismatched envelope
   bytes fail with bounded path-free codes.
4. Changed, missing, undeclared or unsafe grouped source bytes fail through the existing source
   verifier; producer score claims remain provenance only.
5. Preparation performs no publication or evaluation and never reports host-observed request
   coverage.
