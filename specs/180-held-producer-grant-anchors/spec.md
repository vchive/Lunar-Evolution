# Feature180: held producer grant anchors

Status: independent host API, preceding native control v2 integration.

Current policies retain path strings, and the native boundary opens those strings later.
The next formal integration needs live original objects rather than refreshed inode numbers.
This feature supplies a bounded, context-owned acquisition and revalidation API. It does
not change policy v1, native control v1, formal capability gates, launch/recovery, or grants.

## Contract

- `ProducerGrantRequest(path, role, expected_identity=None)` uses a canonical absolute
  string, one of `protected-file`, `readonly-directory`, `writable-directory`, `cwd`.
  Protected files require an original `ProducerGrantIdentity(device, inode, kind)` supplied
  from already-validated evidence. Other roles may supply it, or capture their first object
  on context entry. Capturing a new directory is not proof of earlier formal approval.
- `hold_producer_grants(requests)` accepts an exact tuple, up to 64 read, 16 write, 1 cwd
  requests, at most 81 requests, depth 64, paths <=4096 UTF-8 bytes, aggregate <=65536 bytes,
  and at most 256 distinct held nodes including ancestors. Validate before filesystem I/O.
- Walk every component with no-follow directory FDs, compare named/opened identities,
  and keep original ancestors and leaves open. Root itself is pinned. Never resolve symlinks.
  Non-regular/non-directory leaves, links, missing nodes and unexpected identity fail closed.
- Protected files are regular files with nlink=1 at acquisition and every revalidation.
  Identity is device/inode/kind, not a bytes/mode/content immutability claim.
- Merge different roles for the exact same path, including write + cwd; reject duplicate
  path/role requests, inconsistent expectations, distinct-path same-object aliases, and
  protected files at or below a writable directory and read-only directory subtrees
  intersecting a writable directory in either direction. Cwd requires an exact write
  request. Root is not a writable/cwd grant. Read-only runtime directories remain supported.
- `plan.validate(reserved_fds=())` checks original held FD identities and original root/
  parent/child pathname bindings, then rejects any leaf FD colliding with caller-reserved
  FDs. It never refreshes the authorization after drift.
- `plan.anchors` and `plan.pass_fds` return only live leaf grants after validation. Ancestor
  pins stay private to the host owner. `plan.manifest` is detached observation only: schema
  v1, scope `host-held-grant-anchors`, `execution_enforced=false`, canonical SHA, no FD
  numbers. It conveys no launch, recovery, memory, success or publication authority.
- Context exit revalidates on success and attempts cleanup of every still-identifiable
  owner FD on success or error. OS failures refuse clean success; cleanup continues for
  other descriptors. An exception from the body is preserved. Closed plans refuse access.
  Borrowed FD numbers are not caller-owned and must not be closed/replaced by the caller.
  Defensively reject reuse with a different device/inode/type and do not close that distinct
  object. Same-object reopen, FD generations and hostile same-process FD manipulation are
  outside the contract; identity checks cannot prove an unchanged open-file description.

## Acceptance

Disposable host fixtures cover original-inode mismatch, rename replacement, leaf/ancestor
symlinks, cwd substitution, hardlinks, conflicting expectations, overlap/alias, FD misuse,
bounded input, legitimate input/work/output and write+cwd role merging. Cleanup is verified
after body, acquisition, and exit-validation failures. No producer is executed.

## Limits and following feature

This API alone does not close the formal P0 gap. Follow-up must acquire work/output anchors
at their original creation/validation, derive protected expectations from the original
validated manifests, pass a versioned bounded table to C, independently check FD/path/type/
reserved-role bindings, install Landlock from original FDs, fchdir the held cwd, and close
all temporary anchors before exec. Historical evidence must keep its original scope.
Contents, modes, descendants, bind-mount alias completeness, runtime loading, egress,
bootstrap death/pause independent stopping, and distributed ownership remain separate.
Only local inert/provider-free fixtures and existing CI; no models, WebAgent, evaluator,
real campaigns, `.env` or credentials.
