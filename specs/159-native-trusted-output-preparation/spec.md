# Feature 159: native trusted output preparation

**Status**: Provider-free read-only preparation slice

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
