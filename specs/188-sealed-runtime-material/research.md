# Mechanism decision

This is a design comparison, not an implementation or platform measurement.
Feature188 selects one bounded framed Linux memfd with complete write/grow/shrink/
seal seals. It produces truly immutable material bytes while retaining false
runtime-load and production-admission claims.

| Option | Evidence and limitation | Decision |
| --- | --- | --- |
| chmod/private copy/held directories/two snapshots | Rechecks observations or restricts normal writes; another source writer can still change bytes after the check | Not an immutable mechanism |
| Read-only bind mount or namespace view | Blocks writes through that view, but other writable mounts, namespaces or already-open writers can change the backing inode | Insufficient alone |
| Read-only squashfs/EROFS/loop image with writable backing | Internal namespace is read-only; external backing image/device mutation is not prevented by one hash or a read-only mount flag | Insufficient alone |
| fs-verity/dm-verity or genuinely trusted immutable image | Can verify immutable contents under a retained trusted digest; still needs original device/mount/namespace/membership ownership and explicit installation/kernel support | Valid later alternative; not added by188 |
| Fully static CPython and finite frozen/builtin closure in one sealed target image | Can avoid external loader/module reads, but requires an installation-owned build recipe, actual ABI/runtime evidence and no hidden dlopen fallback | Proposed189 first Python fixture |
| Static CPython plus one framed sealed bundle and native importer | Can consume immutable per-project module/resource bytes; requires explicit versioned FD handoff and native seal/table checks | Proposed successor delivery shape |

A read-only host-image declaration is not sufficient. A future image route must
retain the trusted verity/root digest and backing ownership, reject namespace/
overlay/bind substitution, and refuse unsupported kernel or filesystem setups.
It must state its privileged-host trust assumptions; this feature adds no mount,
CAP_SYS_ADMIN, loop device, namespace or service dependency.

Fully static libpython is not necessarily a fully static executable. PT_INTERP
or DT_NEEDED implies an external native load path; absence of those fields does
not prove CPython identity or no runtime dlopen. Static glibc NSS/gconv paths and
dynamic builtin dependencies require closure or refusal. A controlled static
libc/build recipe is an installation prerequisite rather than runtime discovery.

Feature189 must freeze encodings/bootstrap modules before initialization performs
path discovery and bind all required stdlib/builtin/resource bytes. Python-level
sys.meta_path/sys.path mutation, observed imports and AST scans do not enforce
a malicious program's complete load boundary. Current work/output read/execute
grants can also permit loading code from writable work; arbitrary Python projects
and native extensions require a separately closed native policy.

The current CI-installed CPython and Feature184 trusted-host roots remain a
compatibility fixture. No automatic pip/build/import probe may convert them into
the production static artifact or a trusted immutable image.

Feature188 therefore closes an actual material-bytes gap and leaves the actual
runtime consumer gap explicit. A C reply pretending to be Python, descriptor
self-hashes, source inspection or Darwin skips cannot close that consumer gap.
