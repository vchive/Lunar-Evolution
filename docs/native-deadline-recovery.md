# Native original deadline recovery

Formal native attempts freeze one effective deadline: the intent wall budget narrowed by the
parent deadline and, when present, the original RSI input deadline. Registration, broker and
guardian use this same budget. Recovery does not allocate another interval.

New native attempts retain a v2 attestation consumption claim in both the nonce ledger and
batch. Its `deadline_binding` pins the deadline file's complete canonical bytes, self digest,
device/inode, size, permissions and mtime/ctime. The publisher holds the original writing FD
until the file and directory are fsynced and the name still refers to that FD. Registration
and handoff consume the claim's digest before releasing the target gate.

`recover_native_trusted_attempt(..., cleanup=False)` remains read-only. A missing terminal
returns recovery-required; a valid deadline rehash, whitespace change, identical-byte inode
replacement or metadata/link drift refuses recovery. Restoring equivalent-looking JSON is not
evidence of the original admission. Keep the retained material for diagnosis.

Explicit `cleanup=True` requires the original full registration/handoff, current boot, lock and
process identity. It rechecks the original deadline before every controller signal, after the
identity observation and before/after recovery receipt publication. Drift discovered after TERM
stops further controller signals and trusted receipt publication; it cannot undo the sent TERM.
The existing C guardian's original deadline/lifeline teardown remains independently active.

Successful cleanup still produces an **unknown execution outcome**, with the original deadline
and binding digests. It cannot establish a successful solve, admit a candidate, refresh a budget
or retry a producer. Replaying a retained recovery receipt rechecks the original file pin.

Older v1 complete terminal records keep their existing read-only verification bounds. Older v1
missing-terminal records report `native_trusted_recovery_legacy_deadline_unanchored`; they cannot
receive new cleanup authority or be upgraded by generating a descriptor after the fact. Partial
claims/registration are retained, never automatically completed or downgraded.

This is a host-owned local evidence boundary. It does not implement remote attestation, cross-boot
resume, descendant tree supervision, complete containment/egress or immutable Python imports.
