# Feature 170 — OpenEvolve trusted local launch

This is an incremental P1 slice of Features 160/169. The existing OpenEvolve strategy gains
an explicit process-local native execution injection. Legacy configuration and invocation stay
compatible. This slice proves composition with a local C producer, not a Python project campaign.

## Contract

- Before launch, freeze the complete contract, strategy budget and producer identity in an exact
  read-only config manifest. Bind its bytes/inode to the original intent, attestation and bootstrap.
  The producer-config and RSI argv protocols are exclusive in this first version.
- Use `workspace/.producer-runs/openevolve/` for native evidence so the canonical `evolution/`
  seed transaction remains empty or contract-only. Freeze canonical/runtime directory identities,
  original absolute deadline, command, launch and bootstrap in a create-only admission claim.
- The existing strategy invokes the formal native lifecycle with `strategy=None`. Require its
  same-attempt execution receipt, original deadline, owner cleanup and controller-owned broker.
  Require exactly one group, one material and one single-file candidate.
- Generic producer evidence cannot establish score. Invoke the local exact evaluator once and
  retain an independent admission checkpoint before the existing atomic OpenEvolve seed commit.
  Keep generic source-bundle dependency/protocol environment separate from native execution pins.
- Started, interrupted or unknown claims never relaunch, refresh a deadline/nonce/journal, repeat
  evaluation or retry publication. They require explicit recovery; this slice does not settle
  uncertain calls into success. A missing final acknowledgement remains recovery-required.
- Completed replay revalidates launch inputs, native receipt/output, local admission checkpoint,
  canonical source/record/receipt/archive/state/commit marker and file identities. It performs no
  evaluator, provider, launch, publication, writes or signals. Trusted state without its explicit
  injection, or a trusted injection on legacy completed state, refuses protocol downgrade.
- Caller cancellation and the original total deadline guard launch, evaluation and admission.
  The existing atomic commit is a critical region; no post-commit timeout can erase success.

## Limits

No real model, WebAgent, remote/company evaluator, real OpenEvolve/Shinka campaign, `.env` or
credential access is permitted during validation. Python interpreter/loader/stdlib/packages/
source/resources inventory, full containment/egress, distributed ownership, remote scheduling
and model adaptation remain separate work. Host broker credentials never enter producer inputs
or persisted execution plans. Trusted local hashes do not protect against historical deletion
or rollback of the complete trusted workspace.
