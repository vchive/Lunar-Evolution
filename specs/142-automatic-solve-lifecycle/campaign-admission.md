# Fresh campaign admission

This provider-free slice implements the admission portion of T038. It does not launch the
automatic solve, consume a provider request, evaluate generated code, resume, or retry. T038 is
not complete until the native invocation and supervision are wired to this admission.

`prepare_acceptance_campaign(registration_path, seal_path, checkout_root=..., campaign_parent=...)`
uses the existing registration preflight, then queries the actual Git `origin` for exactly
`refs/heads/main` using a bounded, noninteractive `ls-remote`. The observed remote commit must
equal the preflight HEAD and local `origin/main`. A stale/manually moved local tracking ref alone
cannot satisfy this gate. Endpoint values, Git diagnostics and credentials are never returned.

Before any mutation, all twenty registered materials and manifest/seal bytes are read again and
checked against their pins. A second read-only preflight must match the first checkout and
registration identity. Admission uses no alternative origin ref or injectable remote claim.

After these checks, the controller holds the campaign parent's no-follow directory chain and
atomically creates the exact registered root with mode 0700. An existing root is never reused,
replaced or deleted. The controller binds its device/inode and the parent identity, retains the
manifest, seal, preflight, remote observation, and material snapshots with create-only writes and
fsync, and publishes a digest-bound `admission.json` last. Successful admission is `prepared`,
with `provider_started=false`; it is not an execution success or acceptance counter.

Each created file retains its inode and metadata fingerprint. Before and after publishing the
admission, bounded descriptor-relative reads must verify every retained byte, original fingerprint,
single-link/private-file modes, the materials directory identity/mode, and the exact inventory.
Missing, extra, replaced or altered evidence cannot produce a successful return. Admission does
not make the root immutable; the future runner must revalidate retained evidence before using it.

Any failure after root creation leaves that root reserved, including incomplete evidence. A new
call refuses it rather than repairing or granting a fresh slot. The future runner must handle an
incomplete admission as failed/unknown under the one-slot protocol. The admission does not
establish that remote main or the checkout can never change later; the future runner must recheck
its identities immediately before invocation, with code imports bound to the committed product.

## Provider-free single-attempt claim

### Formal native invocation, 2026-09-28

The public runner starts one fresh isolated Python interpreter. Before importing product
modules, it reads every registered Python source with no-follow regular-file checks, verifies
the complete package inventory and each size/digest, and installs a loader that compiles those
verified bytes (never a cached bytecode file or another installed package). The child repeats
the clean checkout/remote/material admission and claims the only attempt. Unknown package
imports fail closed. A changed checkout never causes a fallback to an installed version.

The preparation callback publishes the runtime/observation binding before candidate generation.
All provider exchanges share one request/token ledger; failed or unknown exchanges prohibit
continuation. An independent postrun audit, not the CLI status, owns the acceptance counts.
Failure after claim retains bounded failure evidence and never launches a replacement attempt.
`python tools/run_acceptance.py --help` is the explicit entry point; importing the runner does
not run a campaign. Provider credentials remain in the child environment only.

`claim_acceptance_attempt(revalidated, campaign_parent=...)` is the narrow handoff between
launch-time revalidation and a future native runner. The caller must supply an unchanged
`status=ready`, `launch_allowed=true` result from `revalidate_acceptance_campaign`. The helper
rereads the canonical `admission.json`, checks its digest, campaign-root and parent device/inode,
and compares the persisted admission to that result. It then publishes
`attempt-started.json` with a create-only `O_EXCL` write, mode `0600`, fsync and post-write
inode checks. A second claim, forged admission, missing revalidation, or existing claim fails
without replacement or repair.

The receipt is a local claim boundary only. It records `attempt_claimed=true`,
`provider_started=false`, and `provider_call_made=false`; the helper does not invoke a provider,
model, evaluator, candidate, or network endpoint. A future runner must consume this receipt and
perform the actual single provider attempt with the existing lifecycle, runtime-binding and
observation evidence gates. This slice therefore does not close T040 or claim real acceptance.

`stage_acceptance_attempt(registration_path, seal_path, checkout_root=...,
campaign_parent=...)` is the controller-owned provider-free composition of fresh admission,
launch-time revalidation, and the create-only claim. It compares the revalidated admission
to the receipt returned by this admission before claiming, then verifies the complete
post-claim inventory before returning. A failed preflight leaves no new campaign root; a
failure after reservation leaves the root untouched and unavailable for another launch. A
successful return is the persisted `attempt-started.json` claim, still with
`provider_started=false` and `provider_call_made=false`. The native solve invocation,
shared deadline, request broker, recovery and postrun audit remain separate T038/T040 work.
