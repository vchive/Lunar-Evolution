# Provider-free multi-episode context selection

This slice records the controller-only contract for a DRS target retry after a verified
practice episode. It does not launch a Python producer or grant native dispatch authority.
The existing provider-free gateway remains the test oracle.

For each episode, the controller reconstructs the exact `SolverRequest` and memory snapshot
from its own checkpoint. The first target uses the frozen parent snapshot. A failed target
that is judged to need practice creates one practice request with the same parent snapshot.
Only a completed, independently accepted practice may produce the next target request; that
request must carry the new snapshot digest. Episode IDs, request digests, and memory digests
are checked independently, so a sibling cannot reuse another child’s request or memory.

An `unknown`, `timed_out`, `cancelled`, or `abandoned` child is terminal for the current
control flow. The controller does not create a sibling, retry the target, merge memory, or
invoke the gateway again until an explicit durable reconciliation path supplies evidence.
A run deadline is retained across every episode and cannot be refreshed by a retry.

Acceptance is provider-free: the focused regression records the three expected calls for a
successful target→practice→target flow and verifies the memory transition, then exercises an
unknown target and confirms no practice/retry call. It must leave the native producer path,
remote evaluator, model credentials, and production admission disabled.
