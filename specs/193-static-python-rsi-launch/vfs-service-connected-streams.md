# Finite original service listener with accepted stream connections

Status: specified for the explicitly selected VFS lifetime backend. The original
six-command inert attempt remains failed and partial. Its freeze-0 raw records
end at `acquire-after`, locating the refusal at the original `service.verify()`
inside VFS acquisition. Those records do not retain the particular stat or
`net/unix` body that caused the refusal, so its exact historical branch is unknown.

An independent Linux AF_UNIX fixture, with no product import or Podman contact,
confirmed a separate parser defect: one service-owned listening stream socket
and its accepted connection can both appear under the same pathname. Their
flags/state pairs are respectively `00010000/01` and `00000000/03`. The legacy
predicate rejects the accepted row even while the unique original listener and
its owned FD remain valid. This fixture must never fill missing historical
observations or promote the failed original report.

## Explicit selection and unchanged ownership

Keep the old `_socket_owner(pid, socket, checkpoint)` behavior and the old
two-positional-argument `ServiceRoot` call unchanged. Add only private, exact-bool
`connected_streams=False` selection to `_socket_owner` and
`_connected_streams=False` selection to `ServiceRoot`. Only the lifetime backend
passes `True`; its original constructor and every original `verify()` repeat the
same profile. Existing pidfd, start ticks, root, namespace, socket pathname UID,
socket object identity and original service FD ownership checks remain required.
The proof schema and all report/claim versions stay unchanged.

The profile uses the original bounded `net/unix` read and a 4096-entry limit for
the table rows and original FD scan. For every row containing the exact pathname as a field, require
exactly eight fields with that pathname in the eighth field, a valid 8- or
16-digit hexadecimal Num with a colon, an eight-digit hexadecimal reference
count, zero protocol, and a positive decimal inode smaller than 2**64. Duplicate
inodes in relevant rows refuse. There must be exactly one stream listening row
with flags `00010000`, type `0001`, state `01`. Other relevant rows may only be
stream connected rows with flags `00000000`, type `0001`, state `03`. Reject
missing/duplicate listeners, malformed related rows, other socket types,
unknown flags or states; do not merely skip rows that fail the listener check.

Prove that the same original service FD table owns the selected listener inode.
Multiple dup FDs referencing that one inode are allowed. Re-read a matching
original FD link and the original socket name after the scan; require the same
listener link and exact original socket object identity. Re-read the bounded
table and require the same unique listener inode; accepted connections may
change while still satisfying the exact finite classification. A connected row is
never accepted as the source-owned listener. Return the existing exact socket
proof fields, so the original `ServiceRoot.verify()` comparison continues to
reject listener, pathname or owner substitution. No replacement process,
alternate socket, retry, extra deadline or old-report reinterpretation is added.

## Implementation and concentrated verification

Change only `podman_vfs_root.py` for the private finite parser/owner path and
`podman_custody.py` for its lifetime-only selection. Add a separate focused test
file with explicit kernel/FD doubles, plus the minimal existing lifetime seam
adjustment needed to assert both private options. Do not modify the original
inert harness or replay its failed attempt.

Tests cover accepted-first and accepted-last row order, unique original owned
listener, same-service dup FDs, malformed fields/inodes, duplicate inodes or
listeners, missing listener, wrong type/protocol/flags/state, a foreign FD table,
socket name or winning FD link replacement, bounded scan/cancellation, and
constructor/verification reuse of the profile. Legacy calls retain their strict
accepted-row refusal and old keyword seam. Run the completed slice with all
affected focused files once under root's unified regression, then Ruff,
compileall and diff checks. A fresh source-bound inert attempt requires new
source/configuration review and must keep the failed original attempt intact.
