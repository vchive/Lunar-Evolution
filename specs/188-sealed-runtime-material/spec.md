# Feature188 — Sealed Python runtime material

Priority: P1. Status: SDD preparation only, based on Feature187 head
`6d20238495d3c6aaa430c4a650674bd83200bc48`. No implementation, execution or platform
acceptance is established. Feature188 implementation must wait for Feature187's
final-head Linux acceptance. This preparation may proceed in parallel with that CI.

Feature171 pins declared files. Feature177 closes selected filesystem membership.
Feature184 proves trusted-host Python/pipe compatibility. None seals the runtime
bytes that a later interpreter loads. This feature supplies one bounded, genuinely
sealed materialization without upgrading those contracts to Python execution authority.

## Contract

- Consume the original Feature177 tree and require caller-owned declared-manifest SHA,
  tree SHA, target and explicit material version. Rebuilding today's tree cannot replace
  those pins. Validate exact bounded DTO/scalar/collection shapes before callbacks,
  serialization or filesystem effects.
- Stream every declared regular file into one new anonymous Linux memfd. Its strictly
  framed canonical table records all logical roots, files, directories including empty
  directories, roles, sizes, offsets and content digests. Do not discover imports,
  execute code, install packages or widen source roots.
- Copy from held no-follow source parents. Compare each original byte and identity pin
  while reading; reverify the original tree before and after copying. A successful copy
  has the exact externally admitted file vector, not a claimed atomic source-tree view.
- Verify the complete frame through the same owned memfd, then require all four kernel
  seals: F_SEAL_WRITE, F_SEAL_GROW, F_SEAL_SHRINK and F_SEAL_SEAL. Missing support,
  partial seals, failed sealing or incomplete verification refuse before any live
  handle is yielded. F_SEAL_FUTURE_WRITE is not a substitute.
- Yield a context-owned live bundle FD and explicit versioned image descriptor.
  The factory retains original ownership, FD identity, bounds and deadline. A detached
  parsed descriptor or numeric FD is never a live ownership handle.
- The live verifier independently requires the original descriptor/frame digest,
  material version, declared/tree pins and target; it checks original object identity,
  frame contents and complete seals. A replaced FD number or same-byte foreign object
  refuses. Caller-forced DTO mutation cannot widen bounds or invoke custom callbacks.
- Use one original absolute monotonic deadline for copy, verification and cleanup
  decisions. Do not refresh or widen it. Release every owned source, chain and memfd
  descriptor on refusal, interruption and context exit; uncertain ownership or cleanup
  remains an explicit fixed refusal. Never close a foreign reused FD.
- Source drift after sealing cannot modify the returned material bytes. It does not
  make the source tree immutable. Verification of the original source can refuse that
  drift while the original sealed material continues to contain the admitted bytes.

## Scope and claims

Protocol: `lunar-python-runtime-sealed-material-v1`.
Scope: `sealed-runtime-material-only`.

Live successful verification may report `material_bytes_immutable=true`, meaning
the material's underlying bytes are protected by the complete kernel seals under
the existing trusted controller/kernel model. Detached JSON is evidence only and
cannot itself establish that a live sealed object still exists.

All observations retain `execution_performed=false`,
`runtime_load_protection=false`, `production_admission=false`,
`archive_contents_complete=false` and `loader_dependencies_complete=false`.
The custom frame's exact membership is not proof of arbitrary zip/whl/pyz members,
CPython identity/ABI, import behavior or transitive native loader closure.
MAP_PRIVATE memory changes do not change sealed file bytes; process memory,
self-modifying code and general containment are outside this claim.

No production selector, native control v2, read grant, attestation, receipt,
publication, RSI or recovery schema changes. In particular, the native child's
existing FD keep-list is not widened to inherit a bundle FD. No CPython is launched.
Library APIs and an optional explicit local CLI operate within one local process;
no service, daemon, multi-host ownership or P2 scheduling is introduced.

## Mechanism and platform boundary

Linux memfd sealing is the only materialization mechanism in this slice. Ordinary
chmod, private copies, held directories and repeated snapshots do not qualify.
A read-only bind mount or loop image with writable backing does not qualify:
another writer can still change the underlying content. No mount, namespace,
verity device, root privilege or host-image installation is added.

Non-Linux hosts and unavailable sealing support refuse before source observation.
The data bundle is not an executable image. Darwin snapshot behavior and old
read-only scopes remain unchanged and receive no new Linux claim.

Validation uses inert files and a bounded, parent-owned local reader fixture only.
No arbitrary project, interpreter, model, provider, WebAgent, remote/company evaluator,
.env or credentials are executed or read.

## Successor boundary

Feature189 is proposed, not implemented: an installation-owned fully static CPython
image with a finite frozen/builtin module closure must consume actual sealed bytes
through a separately validated native launch. It must bind exact build/source,
ELF/ABI, encodings/bootstrap/stdlib/dependency and module-table identities.
The CI-installed dynamic CPython and Feature184 host roots are not substitutes.

A later static image plus one sealed bundle FD requires explicit versioned native
handoff, independent C checks and exact inherited-FD ownership/closure. Python
sys.path/sys.meta_path changes, AST scans or observed imports alone cannot establish
a malicious producer's complete loading boundary. Formal Python admission and real
OpenEvolve/Shinka adapters remain subsequent work.
