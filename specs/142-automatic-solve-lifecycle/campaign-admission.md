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
