# Feature181 executable plan: native original-grant control v2

Implementation plan in the isolated native-grant-objects worktree, based on Feature180
exact head2409206. The original read-only proposal was prepared from Feature179 exact
headc660609 with the in-progress Feature180 owner. Its lifecycle and capability boundaries
remain the implementation contract below. Actual validation and merge status are recorded
in validation.md, HANDOFF.md and final PR evidence; this plan alone is not execution or
publication authority.

## 1. Implement this boundary together

Feature180 already holds root, ancestors and leaves, checks no-follow original bindings,
rejects read/write conflicts and distinct-path leaf object aliases, merges write+CWD,
rejects protected links and detects FD misuse. It deliberately does not change native launch.
Its public leaf accessors cannot yet supply the complete C original-parent graph, create and
hold work/output at their first validation, or validate original input bytes through held
parents. Those are the three necessary owner extensions, not another independent grant DTO.

Feature181 must include all of: those owner extensions; private v2 encoding/parsing; static
and dynamic FD separation; C original-parent checks; Landlock rules using inherited original
leaf FDs; fchdir to the original work FD; two close phases; original-input formal integration;
a new early implementation gate; Linux inert fixture CI and historical compatibility. Host
owner hookup while C still opens string policies does not close the P0 substitution gap.

Keep directory contents/metadata immutability, runtime loader closure, complete egress,
bind-mount alias completeness, bootstrap death/pause independent stopping and P2 multi-host
ownership outside this feature. An original-object rule can remain valid across pathname
mutation; this feature detects original bindings at checks, but cannot make namespaces
immutable or prevent arbitrary host mutation after the last check.

## 2. Minimal Feature180 extensions

### 2.1 Validated detached original lineage

Add an immutable internal `ProducerGrantBindingNode` observation with:

- original canonical absolute `path`;
- original `identity` (`device`, `inode`, `kind`);
- canonical `parent_index` and single component `name` (root: no parent and empty name).

Add a live-owner method/property, e.g. `plan.binding_nodes`, returning a canonical tuple of
all original `_nodes`, parent before child, only after `plan.validate()`. Return no ancestor FD.
It is not a manifest parser and cannot construct an active owner. Existing detached manifest
schema/scope/false execution flag remain unchanged. Node positions are private v2 indexes,
not durable authority. `plan.anchors` remains the only leaf-FD borrowing route.

Add owner construction argument `expected_bindings`, an exact bounded tuple of original
path/identity observations from the already-validated input descriptor. It pins workspace,
batch and input directory without giving any of them a read or write role. These expected
paths must be in the grant ancestor graph, unique and directory-kind, with conflicts refused.
The owner compares each original `_Node` at acquisition, not current `stat()` values used as
new expectations. A raw caller-supplied expectation tuple is a proposal; only the formal
caller obtains its values from validated original descriptors.

This is needed because inserting workspace/batch/input directories as `readonly-directory`
requests would accidentally give broad Landlock read authority. The graph is validation
material, not an access list.

### 2.2 First work/output creation is an owned operation

Add a bounded creation option to the same owner acquisition, e.g.
`create_writable_directories=True` plus a canonical `creation_root=batch`.
Only missing directory components on the requested writable paths under that already-held
batch root may be created. Do not create read/protected paths or unrelated ancestors.
Use `mkdir(name, 0700, dir_fd=held_parent)` and immediately perform named-before/opened/
named-after identity checks and retain that opened FD in `_nodes`. Existing writable
components use the same first acquisition, no preceding `_safe_dir(work/output)`.

For an absent component, an `EEXIST` race must fail closed rather than adopt the intervening
object as the newly-created original. A successful mkdir then replaced before first stat
cannot be proven original by a path lookup: creation must use a bounded create-and-open
protocol that refuses uncertain identity. Linux has no mkdir-returned FD. Keep the actual
security statement precise: the owner begins authority at the first checked opened directory;
creation itself cannot prove an earlier inode without an original observed identity.
If an existing helper returns a created identity before open, compare to it and retain it;
do not claim atomic mkdir+FD identity or a namespace freeze. This matches the existing
creation boundary while eliminating the later close/reopen grant substitution.

The owner must start before nonce/deadline persistence and continue through the attempt's
entire guarded lifetime/cleanup. Same work/output, output nested under work and write+CWD
must remain valid. Directory mtime/ctime/nlink changes due to ordinary output are not drift.
Context cleanup still closes owned nodes only and must preserve an exception from its body.

### 2.3 Protected bytes from held original parents

Linux current leaf anchors are O_PATH, so `pread(anchor.fd, ...)` cannot validate content.
Add an internal owner operation `validate_protected_materials(materials)` with bounded exact
original expected bytes/metadata for the formal config/request/memory leaves. The operation:

1. validates the owner, role and the original parent/leaf binding;
2. opens `node.name` O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC relative to the held original
   parent FD (never absolute resolve, `/proc` reopen or refreshed expected identity);
3. compares named-before/opened regular kind, original dev/ino, nlink=1, exact mode0400,
   original size, mtime_ns, ctime_ns;
4. reads at most the existing module-specific MAX+1, compares exact retained original bytes
   and original SHA; compares opened-after/named-after metadata; checks owner again;
5. closes this temporary reader in all cases, without converting it to a grant or allowing
   its numeric FD to escape into pass_fds.

Accept only the exact protected material set needed by the native input descriptor. The
owner's nlink/identity rules still apply to any protected grant. Do not put file bytes in the
wire, detach hashes and then call them immutable, or borrow the reader as lasting authority.
The checks detect content drift at their actual observation times; they are not file sealing.

Factor strict manifest extraction in `producer_launch_inputs.py` / `rsi_native_inputs.py`
(or an internal pure helper) without exposing an authority-producing parser. Input roots and
files must come from the descriptor returned by `_native_launch_inputs`, already validated
against intent/attestation/bootstrap and equal to the retained original descriptor at the
existing revalidation gates. Validate exact canonical manifest shapes/names/digests first.

Original source data:

- config: `manifest_json.files == [config.json metadata]`, retained `config_json`;
- RSI: exact ordered files request.json and memory.json, retained request_json/memory_json;
- both manifests: original workspace_identity, batch_identity, inputs_identity;
- metadata: device/inode/size/mtime_ns/ctime_ns/sha256; existing mode0400/nlink1 contract.

Manifest.json and launch-binding files remain host-only evidence. They are not currently
`read_paths` and must not become producer read grants merely to verify their identities.
Preserve the existing strict validators for their self-bound inode, bytes, directory mode0500,
exact directory members and launch binding. No-marker launch remains possible with no
protected materials; it still receives original work/output/CWD grants.

## 3. Private v2 frame: concrete order and caps

Use a separate explicit encoder, e.g. `encode_native_bootstrap_control_v2(...,
held_grants: HeldProducerGrantPlan, bootstrap_fd: int, reserved_fds: tuple[int,...])`.
Do not accept a detached manifest in place of a live owner; call validate before and after
borrowing/encoding. Keep v1 encoder and wire unchanged for explicitly scoped fixture APIs.
The formal caller explicitly selects v2 and cannot downgrade on an error.

All integers big-endian, unsigned, exact Python int (reject bool), parsed with checked bounds.
No host struct padding, platform-endian layout or arbitrary Landlock access masks.

Field order:

1. 4-byte magic `LNB1` (same envelope family, version distinguishes body).
2. u16 version=2; u16 flags=0 (unknown flag bits refuse).
3. 64 ASCII lowercase launch SHA; 64 intent SHA; 64 original target executable SHA.
4. u32 target_fd (>2, <=INT_MAX; v2 requires inherited sealed target route).
5. u32 bootstrap_fd (>2, <=INT_MAX; supplied original pair bootstrap FD, reserves that role).
6. length-prefixed UTF-8 target_path (diagnostic/existing target binding, max4096, no NUL).
7. u32 isolation_kind=1 (fixed Linux original-grants + current Landlock/seccomp profile).
8. u32 node_count (1..256).
9. For each node: u32 parent_index, u32 kind (1=directory,2=regular), u64 device,
   u64 inode (>0), u32 component_len, component UTF-8 bytes.
   Root node index0: parent_index=0xffffffff, kind=directory, component_len=0.
   Others: parent_index<i, directory parent, component nonempty, no slash/NUL/dot/dotdot,
   component at most4096 bytes; derived absolute path at most4096 bytes and depth<=64.
10. u32 grant_count (1..81; actual read<=64/write<=16/CWD<=1 request caps imply <=80
    distinct legal grants because CWD must merge into an existing write grant).
11. Per grant: u32 node_index; u32 role_mask; u32 inherited_leaf_fd (>2, <=INT_MAX).
12. u32 cwd_grant_index (<grant_count, references the exact write+CWD record).
13. u32 argc (1..64); argc length-prefixed UTF-8 nonempty strings, each<=4096, no NUL.
14. End of frame; reject extra/truncated bytes.

Fixed role masks: protected-file=1, readonly-directory=2, writable-directory=4, cwd=8.
Only legal complete masks are 1,2,4,12. Protected files regular; all other grants directory.
Exactly one mask12 is required for this v2 launch; cwd label is derived from that node graph,
so no independent unbound target_cwd string exists. Caller target_cwd must equal that path.
A node can have only one grant; role merging occurs in the owner. Grant records sort by
canonical derived path, node graph sorts by canonical full path (root first). Every node
must be root or on a grant's ancestor chain; refuse duplicates/orphans, inconsistent kind,
invalid indexes and cycles (parent<i already prevents cycles).

Retain total MAX_CONTROL=65536 bytes. Also retain host owner request/path caps (read64,
write16, total requests81, total request path bytes65536, 256nodes, depth64, per-path4096).
Encoding must reject the complete final frame if it exceeds65536; C must independently cap
before allocation and enforce each count/string/path cap. This explicitly does not promise
that all independently maximum-sized argv, grant paths and ancestor sets fit simultaneously.
No need to raise MAX_CONTROL or add a new larger inherited-FD budget. If wire subcaps are
wanted later, document them as an intentional contract change, not an accidental truncation.

Deriving absolute paths from parent+component means each original ancestor component is
encoded once. Do not serialize each full path for all 256 ancestors, nor pass all host
ancestor FDs. Only the <=81 owner leaf FDs join pass_fds. C opens its own bounded temporary
no-follow graph to check original identities against the serialized original graph.

C compares device/inode without narrowing truncation; reject values not representable by the
actual ABI where conversion is necessary. Filesystem stat errors including EOVERFLOW refuse.
Actual CI remains Linux x64; don't claim i386/ARM runtime coverage from source arithmetic.

## 4. C validation and authority roles

Parse/structural validation occurs before FD-changing operations. It validates exact enum
sets, role counts, path grammar/canonical indexes, read/write overlap and distinct-path
same-object grant aliases, independently of Python. Protected below write is refused;
read-only directory/write subtrees intersecting in either direction are refused. Write/write
nesting and exact write+CWD sharing remain valid. Parent-only nodes confer no filesystem
access. Bind-mount completeness and directory subtree content remain out of scope.

Validate each inherited leaf with fstat and F_GETFL: live fd>2; expected dev/ino/kind;
protected nlink1; O_PATH or readonly access only, not O_WRONLY/O_RDWR/O_ASYNC. Direct fixture
O_RDONLY grants are useful for proving cleanup; normal Linux owner grants remain O_PATH.
No caller arbitrary FD or inode table bypasses the formal descriptor/input/attestation caller.

C graph checking opens `/` O_PATH|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC, compares root identity,
then walks nodes in parent order with `fstatat(...,AT_SYMLINK_NOFOLLOW)` / openat(O_PATH|
O_NOFOLLOW|O_CLOEXEC[|O_DIRECTORY]) / fstat / named-after comparisons to the original table.
Retain the bounded walked FDs during each checking pass and close them on every exit.
For grant nodes, compare the original inherited leaf fstat to both original table and walked
named node. Recheck complete original root-parent-child links, not just immediate dirname.
No `realpath`, `resolve`, original-expectation update, or fallback to current path grants.

Checks should run pre-ready (so malformed/obviously stale acquisition is not registered),
post-release in the parent immediately before fork, and again in the child before rules/CWD.
The existing host also revalidates just before Popen and gate release. The C checks do not
extend deadline or bypass controller lifeline; apply existing check_controller_guard at
bounded loops/entry/exit to avoid setup consuming unlimited post-gate time.

Map roles to fixed rights, never numeric rights from Python:

- protected-file: READ_FILE only; input config/request/memory do not need EXECUTE;
- readonly-directory: current read/execute/read-dir rights for explicitly supplied runtime
  directory fixture/API grants (formal current attempt doesn't add runtime directories);
- writable-directory: current write_access including its ordinary read/execute/write rights;
- cwd: no extra rights, references the same directory as its writable grant.

Keep the current mutation filter `read_count` meaning as count of protected+readonly grants;
adding readonly grants must still trigger the existing input mutation restrictions. Preserve
all Feature179 fd-control filters, architecture/x32 gates and existing network/process filters.
Refactor Landlock rule source to accept validated original anchor fd+fixed role/kind. Do not
call open(path) for v2 rules. v1 path-rule API stays only in legacy fixture/Darwin scope.

## 5. FD lifecycle and the existing closed-number trap

Current C closes control immediately after read and gate immediately after release, then
validates broker/target and creates target hash duplicate/exec-error pipe. For v2, initial
static alias validation must happen before closing control/gate: otherwise a declared grant
can point at an already-closed number that a later open reuses. Do not treat closed control/
gate numbers as permanently live reserved slots after allocations.

Static reserved roles: stdio0/1/2; live control/gate/frame/lifeline; original bootstrap/target;
both broker endpoints. Every inherited grant is numerically distinct from them and other
grants. Validate role types and original bindings before any inherited reserved FD is
closed or dup2 is used. Host validates owner against *all* its live pipe ends and pair FDs
immediately before encoding and Popen. C independently validates its inherited live subset;
bootstrap FD is explicitly carried to remove ambiguity in reserving that implementation FD.
Existing PIPEFS, broker access direction and distinct pipe object checks remain unchanged.

A v2 direct fixture must explicitly supply the reserved executable binding FDs, owner and
original graph; a proposal doesn't silently promote v1 fixtures. If direct v2 needs an absent
bootstrap binding, add a documented fixture-only sentinel/mode and keep formal encoder
strict, rather than accidentally permitting formal missing-bootstrap control.

After hash duplicate and exec_pipe creation, compare grant FD set again against every newly
live target duplicate and exec-error read/write FD, before fork and in child before dup2.
New allocations normally cannot alias already-live grants; tests still verify this invariant
rather than relying on that intuition. Preserve current guardian EOF/deadline/prctl child
checks and original target seal/hash validation.

C walked graph FDs and Landlock ruleset are bootstrap-owned temporary allocations. Do not
invent inherited authority for them or close arbitrary supplied numbers on parse error.
Use validated inherited-role ownership and original identity when cleanup could race host
misuse; ordinary process exit still closes that process's remaining descriptor table.

## 6. Two close phases, CWD and parent copies

Phase1 in child before rule installation: a bounded generic close-extra helper receives the
current target/exec-error/broker keep set plus validated original grant leaf FDs. At most
85 keep entries (81 grants+4 current entries). Clear bootstrap implementation FD, arbitrary
sentinel/file/directory/socket descriptors and all protocol/lifeline copies as today. This
helper must reject duplicate/stdio entries before close_range, sort safely, and fail closed
if close_range unsupported. Keep original four-entry wrapper for v1 fixtures.

After phase1, child reacquires the temporary checked node graph, validates inherited original
grants again, builds Landlock from those original leaf FDs, and fchdir(original CWD grant FD).
Calling fchdir before temporary anchors are closed is necessary; calling chdir(c.cwd) is not
a valid fallback. CWD path is diagnostic while actual directory authority is the held FD.
Install current filters and close all temporary walked graph/leaf anchors. Then perform
phase2 close-extra with only target/exec-error/broker (original four-entry handoff contract).
Do not depend only on CLOEXEC to demonstrate that config/readable-directory FDs disappeared.
Existing seccomp allows close/close_range, so phase2 can follow filter installation; isolate
rule/CWD ordering must be tested. If fchdir remains Landlock/permission-sensitive, perform it
immediately after graph validation and before restrict_self; no syscall permits path retarget.

Parent closes its own inherited grant and bootstrap copies once child fork succeeds and it
has no further graph checks. Parent does not close child-owned copies or alter inherited host
FD numbers globally. Host original owner closes on attempt context exit after quiescent
cleanup; it retains original parent nodes for final checks. Error paths before/after fork must
not leave a target running, falsely emit target_started, renew nonce, or publish success.

## 7. Formal lifecycle integration points

1. Admission gates before broker/cancellation/budget/input/filesystem/nonce/spawn:
   preserve the existing input-mutation -> fd-handoff -> fd-control rejection order for old
   Linux descriptors, adding new implementation to each accepted set. Add last gate requiring
   `LINUX_GRANT_OBJECT_IMPLEMENTATION="native-bootstrap-linux-grant-objects-v1"`, refusal
   `native_trusted_attempt_grant_objects_required`. A Feature179 fd-control-only descriptor
   passes old three gates and reaches only this new refusal. Latest Linux build defaults to
   the new implementation; historical load/recovery do not re-label older descriptors.
2. Existing _native_launch_inputs and composed deadline retain their current behavior. Pure
   helper extracts original leaf expectations/materials and workspace/batch/input pins.
3. _safe_dir(batch,create=True) may remain for host evidence preparation; remove first
   _safe_dir(working/output,create=True). Enter recovery lock and the owner while acquiring/
   creating original work/output + merged CWD + exact inputs, before deadline/nonce persistence.
   For inputs, compare owner expected batch/workspace/input parent pins. For no-input launches,
   the first checked owner graph is the original grant acquisition, not prior approval evidence.
4. Preserve current input self-bound validators, then owner/material validation before
   _persist_deadline and consume_trusted_bootstrap_attestation. A pre-consumption drift refusal
   does not claim the nonce or spawn anything.
5. Enter existing prepare_trusted_executable_pair; create all protocol/lifeline/broker pipes
   before v2 encoding so encoder can validate the complete host reserved FD set. Current
   control encoding is before pipes and must move. Do not use mutable policy strings to
   derive the v2 grants after this point.
6. Revalidate original inputs, owner/materials, unchanged deadline and recovery lock before
   Popen. Popen(pass_fds) merges protocol/pair/broker/lifeline with validated leaf FDs; only
   bounded original leaves are inherited. Host cwd bootstrap setting must not expose a
   substituted grant: use stable host cwd (e.g. original root or `/`) and rely on child
   fchdir held work, rather than Popen(cwd=str(working)) resolving mutable work prematurely.
   Keep target expected working path in v2-derived graph for diagnostics. Changing controller
   global cwd or preexec_fn in threaded controller is inappropriate.
7. Registration/session remains original schema; pre-ready C validation failures go through
   current consumed-attempt unknown/failure cleanup semantics, not forged success evidence.
8. Immediately before release retain existing _revalidate_native_launch_inputs, plus owner
   graph/material validation, deadline/recovery lock checks. Any post-consumption drift is
   terminal/recovery-required as appropriate and never replayed with fresh grant expectations.
9. C parent/child enforce v2 as above. Continue owner lifetime through receipt/stream/broker/
   cleanup, without adding live FD numbers to receipts or producer argv/env.

The no-input and both mutually exclusive input-marker positive paths must remain available.
RSI/config marker exclusivity is not changed in Feature181. Formal Darwin remains current
v1 sandbox route; host owner APIs can be tested there, but no claim of Darwin original-FD
sandbox enforcement. New Linux capability selectors must be included in
native_bootstrap_command child-supervision negotiation and build selector validation; explicit
older selector builds stay possible for compatibility fixtures only.

## 8. Minimum implementation file map and focused verification

- producer_grant_anchors.py: lineage/expected-binding, first-owned write creation, internal
  original-material validation extensions; no detached authority parser.
- producer_launch_inputs.py / rsi_native_inputs.py: strict pure original expectation/material
  extraction without changing original schemas or granting host-only evidence paths.
- native_bootstrap.py: explicit v2 encoder, new selector/default/export/command acceptance.
- native_bootstrap.c: strict parser/graph/roles/reserved phases, fd-grant rules/CWD/closure.
- native_producer_isolation.h: original FD role entry point preserving existing filters.
- native_trusted_attempt.py: new early gate and coherent original-lifetime integration.
- __init__.py only intentional exports; docs/specs181/workflow and focused tests.

Owner focused inert checks: expected original ancestors; parent/root drift; partial-create/
reader cleanup; bytes/mode/mtime/ctime/hash mismatch with same original inode; graph accessor
closed/misused FD; canonical bounded graph; normal output timestamps and work/output alias.
Do not rerun Feature180 tests just to discover identical API findings during design.

Python wire checks: valid field order; fixed bounds at/over caps; bool/unknown role/index/kind;
component slash/dot/NUL/depth; huge frame refusal; same-owner closed plan and FD reuse;
reserved bootstrap/target/protocol/broker alias; ancestor graph-only directories not grants;
wrong caller cwd; neither detached manifest nor hand-built proposal becomes live owner.

Linux native inert checks: positive original input/work/output/mergedCWD; work/input/ancestor
rename/symlink/alias/overlap refusals with no target marker; drift between ready/release and
parent/fork child setup; correct role/type/dev/ino; static closed-number alias and dynamic
allocated-FD regressions; inherited unexpected sentinel removed in phase1; temporary O_PATH
AND O_RDONLY config/parent/grant descriptors absent after exec; original target/broker
inherited contract remains correct; original-held CWD observed; actual Landlock isolation,
FD-control and native sealed broker composition; original deadline/nonce/registration refusal
ordering. Prove original object receives permission, not merely error code from a parser.

Historical tests: v1 encoding exact bytes, direct fixture scope, older gate ordering,
readonly load/recovery never upgrading evidence, Darwin path sandbox unchanged. Run focused
pytest, Ruff, compileall and diff check after changes; actual Linux full final-head CI and
raw XML/log/tree audit before merge. Host tests/BPF simulation alone cannot certify this C
integration. No model, remote evaluator, WebAgent or real solver campaigns are required.
