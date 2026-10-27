# Feature 197 next slice: original native context and read-only lifecycle inspection

Status: proposal only, not implemented or accepted. This continuation records the reviewed implementation boundary. It does not close the outstanding remote lifecycle, partition or account-isolation tasks.

## Current boundary

One authoritative local controller/SQLite assignment remains the authority. Assignment generation stays 1, the original started claim remains started, an unknown external assignment remains unknown, and inspection never launches or reassigns work. HMAC establishes the key holder's origin for exact bytes; it establishes neither OS boot attestation nor process ownership, target termination, cleanup, isolation, result admission or publication.

The existing SSH test discarded an already sealed response. It did not interrupt SSH before the original remote native attempt reached terminal. `external_worker_wrapper` currently persists only original wire intent and optional signed response. It has no independent original native workspace/launch/intent/attestation/artifact binding. Its Popen PID is the trusted byte-channel launcher, not proof of the candidate's native process identity.

The native stack already persists original registration, original deadline, process terminal and cleanup and verifies their consistency with the original installed launch context. The independent guardian holds an original group pidfd and reacts to original lifeline/deadline failure; its death path signals and exits without publishing a durable terminal/cleanup record. Do not synthesize such a record from watcher exit 78 or SIGKILL success.

## Smallest useful implementation slice

Implement a worker-local, explicit read-only inspection of an already registered original native attempt. The trusted installed native launcher must first pin the original native context under the existing create-only worker episode intent. Only that pre-gate binding is an eligible lookup key. The public request must not supply a workspace, arbitrary artifact, executable, environment, attestation or PID. Native context cannot be reconstructed from the current SolverRequest or late receipt.

The minimum pin composes existing identities rather than creating another process-ownership protocol: original WorkerOriginContext and request/profile digests; original native run/parent/task/launch/journal/intent and attestation/bootstrap-descriptor/artifact digests; the private native workspace and held entry identities. Parent/child/task identity mapping must be explicit and checked against the original assignment; matching only episode_id is insufficient. The reference must be present before the original native target registration gate is released. This is a trusted-launcher integration seam, not a claim that the current wrapper has such context.

Inspection resolves that fixed private record and invokes existing `recover_native_trusted_attempt(..., cleanup=False)` and `audit_native_trusted_lifecycle(...)` on the worker host with the already installed original context. It must revalidate the original bytes, deadline and no-follow entry identities before and after observation. It returns diagnostic distinctions for context unavailable, process terminal missing, drift, process-only terminal and complete existing lifecycle audit. Missing original records never become a newly captured original process binding.

The existing BRS capture helper validates four complete terminal/receipt files and requires a NativeRSIExecutionPlan. It is not a pre-birth capture API and is too strong for an interrupted preterminal attempt. Reuse its entry-pinning rules where appropriate; do not fabricate a BRS plan, extend a captured unknown from later files, or run its local PID observation on the controller for remote IDs.

## Authority and wire limits

Keep the existing external-worker channel-v1 response schema unchanged for this slice. `inspect` continues to return only receipt/unknown/missing. A worker-local explicit diagnostic command/file can expose the existing native lifecycle projection for operators, but must not be consumed as controller-observed local evidence or remote cleanup authority. A future separately reviewed bounded diagnostic wire can carry authenticated assertions; authentication alone still cannot raise authority.

Every diagnostic includes or retains publication_eligible=false. Controller inspect retains native_success=false, remote_cleanup_verified=false and publication_authority=false. No successful receipt, completed audit, observed empty numeric PGID, guardian exit code, HMAC, SSH exit or host interpreter execution changes those values. No side effect, cleanup=True, signal, relaunch, new attestation, timeout renewal, lease expiry or takeover occurs during read-only inspection.

## Prerequisites and non-goals

The pre-gate context pin is eligible only behind the actual trusted installed native launcher and an accepted candidate/account isolation boundary. Current fixed inert producer acceptance does not meet that requirement. Do not expose the signing key/account to untrusted candidates, and do not substitute host Python for the accepted installed static/native runtime. Unsupported runtime/kernel/privilege support must refuse or remain unaccepted.

A genuine hard-disconnect acceptance must separately show original deadline behavior and original native lifecycle/cleanup observations across SSH loss, wrapper death and trusted launcher death. If the native terminal never existed, inspection remains recovery_required/unknown even if the guardian probably stopped the process. Durable crash cleanup proof needs an independently reviewed native evidence path; it is not supplied by this slice.

No background service, new controller, scheduler, NFS SQLite, remote evaluator, lease/TTL takeover, self-modifying agent, arbitrary command endpoint or default microservice architecture is introduced.
