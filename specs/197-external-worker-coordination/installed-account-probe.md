# Fixed installed account transition and denied-access probe

Status: software continuation; no real account, namespace or runtime acceptance
has been performed. The batch owner runs the focused tests after the slice freezes.
The independent durable guardian receiving boundary remains a separate open design.

## Installation and launch

`inspect_installed_account_transition` is an explicit trusted installation API.
Its immutable `InstalledAccountProbeAnchor` holds the original account-profile
anchor and independent helper/source SHA-256 pins. The local installer must review
that relationship; matching source/ELF bytes do not establish accepted build-input
custody. No wire/CLI/environment field selects the helper, account, paths, command,
acceptance flag or authority. There is no automatic anchor or attestation creation.

This API requests no privilege and supports only an already real/effective/saved
root wrapper on Linux. Ordinary users and macOS refuse before installed-file reads.
It composes the existing no-follow held-chain preflight and rechecks original
profile, all six entries and source around observation. The root-owned helper must
be executable by the distinct nonroot child, have no writable group/other or special
mode bits, match both original helper pins and satisfy the bounded x86-64 static
ELF projection with no dynamic tables or interpreter. Existing ACL/capability
metadata refusal remains in force.

The original held helper FD is the sole inherited nonstdio FD and is executed
through `/proc/self/fd/<fd>`, preventing a later name reopen from selecting another
inode. `Popen` drops UID and primary GID and clears supplementary groups before
exec; it uses no shell, PATH, host interpreter, caller environment or candidate.
The child receives an empty environment, private umask and no key/config/state
FDs. The independently installed C helper immediately closes all FDs above 2,
sets no-new-privileges, checks real/effective/saved UID/GID, empty supplementary
groups, zero effective/permitted/inheritable/ambient capabilities and empty env.
Unsupported `close_range` or native operations fail closed.

## Fixed active observation

Only the three original key/config/state paths and the unchanged original absolute
monotonic deadline cross a bounded pipe protocol. The helper opens those paths
without reading any file or directory body and closes any successful descriptor.
Only EACCES/EPERM for every role establishes a diagnostic denied-access observation;
missing paths, symlinks, successful opens and other errors refuse. Its exact 64-byte
response includes numeric identity, denial errno and fixed probe operation facts.
No path, key, config, candidate content or arbitrary prose appears in the report.

Input, output, process wait and native poll use the original absolute deadline.
There is no renewed budget or retry. The parent bounds output to 64 bytes, requires
EOF/exit zero, validates all fields and rechecks held originals before returning.
A failure attempts stop/reap of the exact original Popen without additional grace;
it grants no whole-group cleanup authority. This pipe path is not durable guardian
evidence and makes no hard-time guarantee for filesystem calls or Popen itself.

An `observed` report establishes only this fixed diagnostic's transition and access
facts. Candidate execution, namespace/runtime/isolation acceptance, production
admission, online publication and remote cleanup authority remain false. A real
installed account test, accepted static runtime/build custody and namespace path,
plus independent guardian persistence/ACK design and abnormal-disconnect cases,
remain necessary. The existing `installed-helper-v1` static preflight stays read-only
and does not become execution authorization or ready-for-acceptance.

## Batch selection

`tests/test_external_worker_account_probe.py` exercises the complete host composition
with mocked numeric root facts and a real bounded pipe peer, strict identity/errno
and size failures, independent helper/source drift, same-byte inode replacement,
post-observation drift, unchanged deadline and unsupported/unprivileged refusal.
These are software fixtures, not genuine account transitions. Linux additionally
compiles the native C with warnings as errors and runs only wrong-argv/expired-origin
negative smoke. That smoke binary is never accepted as the installed static helper.
No test creates accounts, changes credentials, invokes sudo or reads secret contents.
