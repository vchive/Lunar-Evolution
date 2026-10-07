# Feature 176 — Linux input mutation gates

Status: local implementation and Darwin compatibility validation complete;
actual Linux CI and final integration pending. Extends the local
Linux boundary in Features 157/172/174 without new process or receipt authority.

The current boundary denies ordinary writes and chmod to exact read inputs, but
does not negotiate Landlock's truncation capability and leaves other metadata
mutation APIs available. Add a bounded Linux read-input mutation gate.

## Required behavior

1. Query the kernel with `landlock_create_ruleset(NULL, 0,
   LANDLOCK_CREATE_RULESET_VERSION)` and require ABI >=3. Query errors or ABI 1/2
   return ENOTSUP before policy installation or target exec. Never silently use
   a weaker filesystem ruleset. Known UAPI REFER/TRUNCATE values must remain
   handled with old build headers; the actual kernel query gates support.
2. Handle REFER and TRUNCATE. Exact regular read grants have neither writable
   nor truncation authority. Work/output directory grants retain TRUNCATE so
   ordinary output open/truncate/ftruncate operations continue working.
3. If any read grant exists, seccomp denies ownership mutation APIs including
   supported legacy 32-bit aliases; timestamp APIs including time64; and all
   set/lset/fsetxattr and remove/lremove/fremove xattr variants, including modern
   setxattrat/removexattrat with known-number fallbacks. Existing chmod
   denial remains. Denial uses EPERM for the entire target, including output
   metadata mutation. This is deliberately not path-sensitive metadata control.
4. With no read grants, preserve the prior metadata behavior. Normal work/output
   creation, read, write, truncate and anonymous-pipe/process compatibility remain.
5. Darwin policy and execution behavior remain unchanged. Unsupported ABIs and
   headers retain their fail-closed boundary. Actual Linux fixtures distinguish
   unavailable syscalls/filesystem xattr support from filter enforcement.
6. New Linux builds default to implementation version
   `native-bootstrap-linux-input-mutation-v1`. Formal attempts require that version
   before budget persistence, nonce consumption or spawn. Keep the historical
   `native-bootstrap-linux-subreaper-v1` constant and read-only artifact/evidence
   scope; both versions negotiate the unchanged `linux-subreaper-v1` child flag.
   The original trusted descriptor, binary hash and launch chain bind capability;
   no control-wire or new C flag is added.

## Boundaries

This does not establish complete filesystem/FD/egress containment, immutable
grant inode/path binding, regular-file ioctl closure, runtime/import sealing,
bootstrap-death/pause supervision or all-request authority. It does not close
inherited writable file/socket descriptors. No target-FD/control protocol, success
receipt, cleanup, recovery, evaluator, publication or broker rights are added.
Historical evidence cannot acquire the new capability merely by relabeling it;
new descriptor versions and artifact hashes select the implemented boundary.

Tests use inert local owned files, static C targets and provider-free fixtures.
No model, WebAgent, remote/company evaluator, campaign or `.env` access.
