# Local account-isolation preflight

Status: implemented software slice, awaiting the shared focused regression. This
is read-only local inspection, not account provisioning or isolation acceptance.
It continues `account-guardian-followup.md` without changing channel-v1, the
single controller or native guardian framing.

## Trusted input and fixed CLI

`external_worker_account_preflight.inspect_account_isolation` accepts an exact
`InstalledAccountProfileAnchor` supplied by trusted installation code. Its bounded
JSON contains schema `lunar-installed-worker-account-anchor-v1`, fixed
`profile_path`, independently recorded `profile_sha256`, `profile_identity`,
`profile_chain`, and independently recorded `protected_identities` for key/config.
The caller must retain the original installation reference; inspecting the current
filesystem cannot create one. It is not an execution or admission capability.

The explicit installed CLI is:

```sh
python -m lunar_evolution.external_worker_account_preflight --inspect-installed
```

`tools/external_worker_account_preflight.py` is an equivalent explicit entry point
when the package is installed/on PYTHONPATH. It reads only the fixed private
root-installed `/etc/lunar-evolution/worker-account-anchor.json`; no CLI argument,
environment variable, public request or channel chooses UID/GID, key, runtime,
helper, profile, argv or an acceptance boolean. The bootstrap file and all its
ancestors must be root-owned and not writable by group/other. The bootstrap is an
installer trust root, not a generated current-state fingerprint. It must be
provisioned by the trusted administrator; this command never writes it.

The profile has exact schema `lunar-installed-worker-account-profile-v1`:

- `accounts.wrapper` and `accounts.candidate`: numeric `uid`, `gid` and sorted
  unique complete `groups`, including the primary group. Local account database
  primary identity and supplementary memberships must match. UIDs/GIDs differ;
  candidate UID cannot be root and candidate cannot belong to a key/config/state
  group. Running the inspector as the candidate refuses.
- `entries`: exactly key, config, state, runtime, helper and isolation_profile.
  Each has an absolute canonical `path`, original ancestor `chain`, and original
  `identity`. Runtime/helper/isolation_profile also have an independent `sha256`.
  State is a directory; all other entries are single-link regular files.
- `isolation`: exactly Linux, transition `installed-helper-v1`, and sorted
  namespaces `["mount", "net", "pid", "user"]`. This finite declaration does not
  establish that a helper or namespace operation has been accepted.

Directory identity is `dev, ino, mode, uid, gid`, including the root directory
and every ancestor. File identity additionally records `nlink, size, mtime_ns,
ctime_ns`. Each chain array has one entry per absolute path component before the
leaf, including `/`. Key/config identities must also match the independent
protected identities from the anchor. A protected inode cannot become a profile,
runtime, helper or isolation-profile input to hashing.

## Observations and refusal

The inspector holds directory descriptors, opens each next component relative to
its parent with NOFOLLOW, and compares the named original entry to the held FD
before and after observation. It rechecks all retained chains and entry identities
before returning. It does not use ordinary path stat as a stable-chain substitute.
Same bytes in a different inode, symlink/parent replacement, hardlinks, aliasing,
permission/ownership changes, added fields and digest drift refuse. Ancestors must
be owned by root/the wrapper and not writable by group/other. No candidate-write
mode permission is permitted. Key/config/state must be private; runtime/helper
must carry executable mode, without privileged special bits. A helper needing
setuid/capability authority is explicitly not supported by this first profile.

Key/config file bodies and state contents are never read. Profile reads are at
most 256 KiB; each of three nonsecret pinned artifact reads is at most 128 MiB.
Only FD-relative metadata and bounded artifact hashes are observed. There is no
candidate launch, credential switch, sudo, SSH, chmod/chown, shell, target
process/env/argv inspection, or writes. Xattr metadata is checked on entries and
ancestors. Observed ACLs or file capabilities refuse; unavailable metadata remains
unknown. Absence of these names is only a metadata fact, not proof that every
filesystem ACL/access mechanism or effective capability has been excluded.

The finite report distinguishes `configuration_absent`, `unsupported`, `refused`
and `unknown`, uses fixed codes, contains no paths/secret data, and emits fewer
than 4 KiB. On a non-Linux platform no installed files are opened. Missing
bootstrap is configuration_absent; missing an originally pinned installation file
is refusal. Output cannot renew deadlines or write a successful acceptance record.
The CLI returns 2 while evidence is absent/unsupported/refused/unknown.

## Remaining acceptance boundary

Even when every static pin and local account observation matches, the report
remains unknown: accepted native runtime/build/custody, account-transition safety,
effective capabilities, filesystem ACL access semantics and actual namespace
operations have no accepted consumer in this slice. `ready_for_acceptance` and
`isolation_accepted` are separate fields and both remain false. No boolean can
promote them. Native runtime acceptance, candidate execution, credential changes,
production admission and remote cleanup authority also remain false.

The next independent software integration must consume the reviewed installed
native runtime and transition/namespace evidence without caller assertions. Real
acceptance then needs a fixed no-secret probe under the distinct identity, denied
key/state access and no inherited secret FDs/environment. Environment provisioning
and abnormal guardian durable evidence remain separate; this implementation does
not claim that existing 5090gpu restrictions changed or run any remote probe.

## Focused validation

`tests/test_external_worker_account_preflight.py` covers numeric group drift,
identity replacement despite equal bytes, hardlinks, leaf/parent symlinks and
replacement, post-observation changes, protected content never read, artifact
hash drift, private-mode refusal, unknown ACL evidence, observed ACL/capability
refusal, unsupported/missing configuration, strict schema and a fixed explicit
CLI. Tests use fixture files and mocked numeric account metadata only; no account
is created or switched. The current development task performed AST parsing only;
root runs focused tests, Ruff, compileall and diff checks with the full batch.
