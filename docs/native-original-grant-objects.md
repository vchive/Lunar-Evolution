# Linux original grant objects

The Linux formal bootstrap selects `native-bootstrap-linux-grant-objects-v1` and
requires the private v2 control and `linux-held-grants-v1` negotiation. The earlier
FD-control descriptor is refused before budgets, input staging, nonce consumption or
spawn. Historical read-only artifact loading and explicitly scoped v1 fixtures retain
their original behavior. Darwin continues to use its original snapshot/path policy.

The host holds work/output directories from their first checked acquisition, creates
missing writable components only below the held batch directory, and retains those
objects through cleanup. Original input manifest identities pin workspace, batch and
input ancestors without granting them access. Protected config/request/memory bytes
are checked through temporary readers relative to held original parents; their mode,
link count, size, times and digest must still match the retained original snapshot.

Before ready and after release, the C bootstrap independently checks the bounded
original graph, exact roles and live FD/channel separation. In the child it closes
unrelated descriptors, checks the original graph again, uses the inherited original
leaf FDs for Landlock and `fchdir` for CWD, then closes grant and temporary descriptors
before target exec. Writable/CWD sharing and nested writable directories remain legal;
protected/read-only overlap and observed conflicting object aliases are refused.

Checks detect namespace/content changes at their observation times. They do not freeze
host namespaces or writable directory contents. Creation authority begins at the first
checked opened object: Linux mkdir does not atomically return an inode-bound FD. Borrowed
FDs must not be closed/replaced by the caller; same-object reopen or hostile same-process
FD manipulation is outside that contract. Arbitrary unobserved bind-mount aliases,
immutable runtime/loader closure, full egress and independent stopping after bootstrap
death/pause remain separate work. No multi-host service is introduced.

Only inert local filesystem, C, pipe and provider-free fixtures are used for this feature.
Actual Linux execution evidence comes from the final-head Ubuntu CI, not macOS skips.
