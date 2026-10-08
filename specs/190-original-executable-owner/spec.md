# Feature190 — Original owned Linux executable bindings

Status: implementation, 2026-10-08. P0 prerequisite for Feature189's
native target delivery; this is not runtime acceptance. Feature188 source
`c5973a7b4ad026182b11e6d65af946ae6d15bd30` / tree
`61d6f966278f5e698e5c033b4aa1d0644324e22a` passed final run37747759152:
three versions, 22 phases, current11984/92 platform skips, material274/0 skips,
zero failure/error/retry. Root independently verified the raw evidence (report
SHA256 `6260a06a004037052ce36cd9abee71d10ae61748335b8be8136543a9818de45e`).
Merge `4f8576d02f2b3be191f71d8c869e48f704dc7a4a` has the identical tested tree.
G0 is satisfied; first failure run37747268959 remains separate evidence.

## Concrete problem

`sealed_linux_executable` currently yields `LinuxSealedExecutable(fd, sha256,
size, binding)` and closes the saved source/sealed numeric FDs in its finalizer.
Closing/reusing the yielded number can redirect that finalizer to a foreign
object. A source-close error skips the sealed close and can mask the primary
exception. `prepare_trusted_executable_pair` copies numeric-FD DTOs without a
private original-pair binding or live check before native `Popen`.

## Contract

- Keep the public `LinuxSealedExecutable`, `BoundExecutable` and
  `TrustedExecutablePair` fields/properties, public helper signature and existing
  `linux-sealed-memfd` binding spelling. DTO construction, equality, cloning,
  public fields and detached records do not create an owner.
- The shared Linux sealing factory privately retains its original acquired
  source, sealed anchor and deliberately duplicated borrowed descriptor. Record
  acquired identity before exposure; bind a live DTO by exact object identity
  to the original owner for its creating context only. A private anchor must not
  be added to native `pass_fds`; only the existing borrowed executable role is
  delivered. Use `F_DUPFD_CLOEXEC` with a minimum borrowed number of3, preserving
  stdio. Close the source once its original verification/copy work is done.
- Independently verify actual sealed image bytes with position-independent,
  bounded reads against the original external SHA/size, exact original object
  identity, executable mode, CLOEXEC and all four seals. A same-byte foreign
  memfd, ordinary unlinked file, closed/reused public number or forced public DTO
  mutation refuses live validation. Complete seals do not prove original owner.
- Preserve the existing 128 MiB ceiling, source byte/identity pin checks and
  shebang behavior. Do not loosen source admission to fit a static image. Do not
  admit a Feature188 data frame as an executable or extend native v2 FD/schema.
- Store the original deadline and original trusted monotonic callable in the
  owner. All copy/verification/pre-spawn decisions use that deadline; a verifier
  accepts no replacement deadline or clock. Preserve legacy positive-infinity
  helper compatibility; Feature189's actual fixture separately requires a finite
  budget. NaN/boolean/negative-infinity values are not accepted owner budgets.
- Guard acquisition, read/write, hash, fsync, sealing, seek, duplication and yield
  with the original deadline. It is a cooperative controller check, not kernel
  syscall preemption. Expiry must not prevent release of still-owned resources.
- Cleanup independently attempts every still-owned role, ignoring public DTO
  changes. Known foreign reuse is never closed. Closed/uncertain descriptors
  remain fixed cleanup-unknown evidence; do not retry an uncertain `close` by
  number or derive a replacement owner from current bytes/stat/JSON. Preserve
  every primary `BaseException`, adding only a fixed cleanup note when needed;
  absent a primary, uncertain cleanup raises a fixed binding error.
- If interruption occurs before identity capture for an unpublished private
  acquisition, a first release of that acquisition is justified only by the
  trusted controller's no-private-rebind assumption. A later stat is not an
  original-identity proof. If that relation is uncertain, retain fixed cleanup
  uncertainty and an explicitly possible leak; never promise unconditional
  zero-leak cleanup. Known foreign objects remain unclosed in every case.
- The trusted-pair factory privately retains original bootstrap/target live
  handles and its original public projection. A Linux-only internal live check
  rejects manufactured/cloned/mutated pairs and validates both original owners
  before control encoding, immediately before actual native `Popen`, and before
  the guardian's separate bootstrap executable handoff.
  The legacy direct `producer_process` caller likewise checks its factory's
  original live handle immediately before its `popen_factory` call.

## Limits and compatibility

No Darwin snapshot behavior, native C control-v2 format/keep-list, receipt,
attestation, registration, durable process-recovery schema or publication policy
changes. Registration's detached DTO validation is not relabeled live ownership.
Existing process/guardian cleanup remains responsible for already-created children
when executable binding refusal unwinds; owner checks never invent process/PID
authority or reopen a parent FD after controller restart.

The trusted controller must not concurrently close/rebind private acquisition
numbers or race `fstat` with `close`; this cannot make those actions atomic in
Python. A duplicate of the exact same held object replacing a public number can
retain the same dev/inode/type: general FD-generation/open-file-description
identity is not claimed. This feature proves the bounded original-object owner
under that controller assumption, not protection against hostile process memory,
arbitrary controller threads or target FD-number reuse after exec.

No static CPython build, import/frozen/module closure, runtime-load protection,
production Python admission, solver campaign, service, provider, model, WebAgent,
remote evaluator, company platform or credential work belongs to this feature.
Only independent final-source Linux evidence may complete Feature190. Feature189
cannot borrow earlier sealing or host-Python evidence as this owner's acceptance.
