# Original held-grant binding for pycache diagnostics

Status: implemented software slice; focused tests are prepared for the next
concentrated regression. No native target, solver or accepted runtime is run
by this slice. Full lifecycle task L06 remains open.

`GrantBoundPycacheMonitor.arm_before_target` explicitly selects
`original-grant-bound-pycache-diagnostic-v1`; its default is disabled. The
caller uses it inside the original `hold_producer_grants` context, after the
finite directory layout is ready and before starting any target. It accepts
the actual live `HeldProducerGrantPlan`, a pinned reviewed view and the
original absolute monotonic deadline. A detached grant manifest, matching
hash, copied wrapper or already-closed owner cannot provide the acquisition.
The original held-grant owner itself refuses standard shallow/deep copies and
serialization; failed transfers leave its live context usable. Failures while
allocating or initializing the wrapper release the already-started original
monitor directly and preserve the initial exception.

The entire reviewed writable-root set must exactly match the original plan's
writable-directory roles. The monitor opens its own no-follow directory FDs
and installs original Linux inotify watches. Every original root's device and
inode must match the original held object, including the initial scan/read
boundary. The wrapper retains the same owner and monitor objects and the
original complete grant manifest/FD snapshot; drain, snapshot and finish
validate them before and after observing the original monitor. Owner closure,
root replacement, role/FD changes or acquisition replacement refuses and
releases the original monitor without replacing the primary refusal.

The returned diagnostic can describe `original_grants_authenticated=true`:
its observed roots were bound to the live context-owned grant objects. That
field does not claim independently immutable source execution, process
enclosure, a complete inherited-handle inventory or immutable build custody.
Serialization does not transfer the original acquisition. The entry point
does not accept a terminal DTO, EOF, caller quiescence boolean or arbitrary
empty cgroup as original evidence.

All enclosure, original quiescence, complete coverage, strict-view acceptance
and production-admission fields remain false. Finish retains the existing
`original_quiescence_unavailable` failure; it stops the diagnostic reader only.
Missing native writer enclosure and original native quiescence still keep
`original_pycache_observation` missing. Native attempt defaults, control wires,
grants, terminal/cleanup contracts, runtime acceptance and CLI are unchanged.

Portable tests cover default-off, exact live-owner requirement, detached and
closed owners, and missing/extra/ungranted roots before kernel acquisition.
Separate Linux tests acquire real original grants and inotify, retain transient
cache create/unlink events in both writable roots and a precreated nested
directory, reject actual root replacement and context closure, and prove that
clean final scans and copies supply no missing authority. These tests do not
stand in for the future native-attempt enclosure/quiescence integration.

## Direct native diagnostic wiring

The optional `run_native_trusted_attempt(pycache_diagnostic=...)` accepts an
explicit `NativePycacheDiagnosticRequest`; the default remains `None`.
Its immutable configuration supplies a trusted diagnostic observer and the
finite already-existing directory layout within work/output. It does not
supply a grant digest, writer/quiescence fact, runtime acceptance or a result
receipt. Non-Linux native execution refuses this selection before consuming
the attestation. No scheduler, RSI or CLI option selects it.

The original native attempt derives the diagnostic root paths and manifest
reference from its actual live held grants. The generated finite root-view
wire describes those granted roots only; its empty declared unknown-capability
list does not establish a complete inherited-handle inventory. The existing
full-enclosure missing boundary remains. No directories are created to satisfy
the selected layout and no Shinka lifecycle behavior changes.

After the original registration observer and fresh registration/input/grant
checks, the attempt arms the actual monitor before writing to its target gate.
Initial contamination, incomplete watches or original root disagreement
prevents gate release. The scope stays inside the same held-grant context
through the entire native body. On return or exception it first allows the
existing process/guardian stop and cleanup to run, then finishes the monitor
before closing the original grants. The exact original native monotonic-ns
deadline is passed through; monitoring never renews it.

Only a normal original native completion with remaining deadline permits
the trusted observer to receive the checked original registration context
and actual incomplete diagnostic. The existing registration reader checks the
context before and after delivery. Changed context/config/diagnostic or a
non-None/failed observer return refuses delivery. Timeout, cancellation,
unknown outcomes and active exceptions stop the diagnostic reader without
calling the observer or substituting a new native result. Finish errors cannot
replace an active original exception; a fixed note retains that diagnostic
uncertainty. Target return/terminal/cleanup booleans control delivery ordering
only, never cache-absence authority.

The scope retains the actual original reader and a fixed resource-retirement
entry point so a failed finish callable cannot skip reader cleanup. Descriptor
ownership retires before each close, separately from retained diagnostic
directory identities. A close failure continues closing the other owned
descriptors and records `reader_resource_cleanup_unknown`; a later cleanup
never retries the uncertain number and risks closing a reused descriptor.
Local `_closed` means ownership was retired, not that every close succeeded.
Normal delivery failures surface a fixed diagnostic error with the supplied
exception only as cause; an active native exception remains the original
object. None of these resource actions establishes original writer quiescence.

The native observation dataclass, terminal/control/receipt wires and default
execution path retain their historical schemas. There is no new accepted
pycache DTO or durable recovery proof. Full native writer enclosure and
original descendant quiescence are still missing, all corresponding authority
fields remain false, and task L06 remains open. New focused tests separately
exercise portable configuration and actual inert static C/native Linux
execution; no solver or accepted Python runtime is run.
