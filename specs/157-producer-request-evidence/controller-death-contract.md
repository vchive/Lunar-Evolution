# Controller death and durable broker recovery

This local, test-only Feature 157 slice validates the existing HTTP worker lifeline
together with the durable broker journal. It adds no transport or recovery authority.
The explicit active-cancellation path remains covered by its separate contract.

`ControllerHttpTransport` owns the anonymous lifeline writer. Its trusted HTTP worker
inherits only the reader, with other descriptors closed and an empty environment.
`http_transport._guardian` exits the entire worker when the writer disappears, including
when the worker is blocked waiting for response headers. The worker also checks the
lifeline before initiating outbound HTTP I/O. Abrupt controller death therefore requires
no recovery process to find a PID or send a signal to stop that local worker.

The fixture runs an actual request broker and host journal in a separate controller
process, with a real loopback server. It exercises two interruption boundaries:

- Admission is fsynced, but the controller is stopped before sending request IPC to the
  HTTP worker. Killing only the controller PID must terminate the worker without a POST.
- The server has received the admitted POST and withholds response headers. Killing only
  the controller PID must close the peer connection and terminate the worker before the
  original request deadline.

The fixture's worker PID and process group are diagnostic observations, never durable
recovery authority. Post-death verification accepts an absent process or an exited zombie;
it does not claim that the dead controller or the recovery caller reaped an orphan.
Any fixture-owned group cleanup happens after these assertions, outside recovery.

A journal containing an admission without a terminal event remains unknown even when
the fixture observed local worker termination. The controller could not fsync an I/O-stop
acknowledgement before dying. Recovery must retain the original admission, exact launch
identity, request count budget, request deadline and wall deadline, and bind the retained
journal's device/inode, hash and byte count. It must not append a terminal, return a
provider response, refresh an execution budget, start transport I/O, relaunch, or signal
a process. A separate bounded read-only audit deadline is not a new request budget.

Acceptance checks byte/inode inventories before and after both successful read-only
recovery and rejected hash, byte-count, identity-budget or same-content inode replacement
bindings. Recovery cannot classify this missing terminal as completed, cancelled or a
confirmed timeout. No inference is made about a remote provider's execution or billing.

This does not close all T157-05/06 requirements. Complete native producer crash cleanup,
durable ownership reconciliation, complete egress coverage and real external-project
trust remain separate work. The local fixture cannot authorize publication or a resumed
producer after controller death.

Local validation on 2026-10-02: the crash/recovery/HTTP focus passed 34 cases on Python
3.13; all six new crash cases also passed on Python 3.11 and 3.12. Ruff, compileall and
diff whitespace checks passed. Ubuntu and the complete combined suite are tracked by
the main integration run, separately from this local slice.
