# Feature 173 — Original native deadline file binding

Missing-terminal recovery currently accepts a valid, self-rehashed deadline sidecar without
an independent pin to the original narrower parent/RSI budget. Formal native admission must
retain the original canonical bytes and file identity before spawning the gated bootstrap.

## Contract

- Publish the existing deadline record once, create-only and fsynced. Keep its publishing FD
  through publication and capture canonical bytes/hash, size, device/inode, permissions and
  mtime/ctime from that same FD, checking the named regular, single-link file.
- Native consumption uses exact schema version 2 / `lunar-native-trusted-attestation-consumption-v2`.
  Both nonce and batch claims include identical `deadline_binding`; their original digest is
  consumed by the existing registration/handoff chain. Cooperative producer v1 is unchanged.
- Recheck the frozen pin before/after claims, spawn, registration, gate release, evidence and
  terminal publication. Recovery checks the original chain and pin before and after observation.
  Equivalent JSON whitespace, valid deadline rehash, same-byte inode replacement and stat drift fail.
- Unknown cleanup requires the full handoff, current boot, original lock and process start identity.
  Every controller signal ownership check also rechecks the pin. Drift after TERM forbids further controller signals and
  trusted cleanup/recovery publication; the already-sent signal cannot be undone.
- Recovery keeps the original absolute deadline. Its exact v2 receipt includes the original
  deadline and binding digests, remains `execution_outcome=unknown`, and never retries work.
- Legacy v1 complete terminal remains read-only evidence under its old bounds. Legacy v1 unknown
  is explicitly `native_trusted_recovery_legacy_deadline_unanchored` and cannot acquire new cleanup
  authority. Partial publication is retained, never repaired or downgraded.

## Boundaries

This extends Features156/157/169, without changing native C control/guardian protocol, budget
mapping, read grants, candidate evaluation or commit semantics. It does not implement descendant
tree-drain, complete containment/egress, Python runtime sealing, remote attestation or P2 services.
The host-owned journal chain detects limited evidence drift; it does not resist a host adversary
rewriting the entire authority chain. Validate only local inert/C/bootstrap/provider-free fixtures.
The existing native guardian retains its original control-frame deadline and lifeline teardown
authority over its own group. Host-side evidence drift checks do not change that C protocol.
