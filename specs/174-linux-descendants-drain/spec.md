# Feature 174 — Linux adopted-child drain

## Problem and contract

The native bootstrap currently retires its guardian immediately after waiting for the direct
target. A target can exit while descendants continue, leaving a controller-crash window before
Python cleanup. This P0 slice keeps the trusted Linux bootstrap alive until its adopted child
tree is drained. It extends Features 156/157/172/173, without changing their ownership authority.

- Before forking a target, configure and verify Linux child-subreaper status and a default
  waitable SIGCHLD disposition. Setup failure prevents target admission.
- Save the direct target's exact status, then reap children with `waitpid(-1, __WALL | WNOHANG)`
  until the kernel returns ECHILD. Normal exits, double forks and non-SIGCHLD clone children
  must not retire the guardian early. Unexpected wait or clock errors fail closed.
- Keep the original private group leader and guardian throughout this wait. Controller EOF,
  unexpected lifeline data or the original absolute deadline stop the original group. No new
  grace period, post-target budget, PID enumeration authority or recovery signal is introduced.
- Recheck the lifeline/deadline before retiring the guardian and emitting sequence-3 terminal.
  Missing terminal remains unknown. The terminal write must succeed; it is never synthesized.
- New Linux builds use implementation version `native-bootstrap-linux-subreaper-v1`. Formal
  Linux attempts require that exact selected descriptor and pass explicit
  `--child-supervision linux-subreaper-v1` with lifeline and deadline. Historical binaries reject
  the new arguments; old descriptors cannot be launched by the new formal Linux path.
- All runnable entries in the new Linux binary drain children, including the old direct fixture
  argv. Entries without a lifeline/deadline prove only cooperative natural drain, not bounded
  guardian behavior. Custom descriptor labels cannot turn off the implementation.
- Darwin keeps its existing direct-child lifecycle and rejects the Linux supervision flag. It
  does not gain child-subreaper authority or receive a relabelled descriptor. Common guardian
  final checks and failed terminal-write handling are also strengthened on Darwin.

## Evidence and limits

Keep the bounded control record, frame protocol and existing exact `process_only` terminal
receipt schema. The formal runner still requires an actual sequence-3 frame, verified process
exit, deadline anchor and cleanup. A descriptor describes installed runtime capability; generic
handshake passed/EOF alone does not establish child-tree drain. No new evidence field or
publication/admission authority is inferred from a descriptor. Historical read-only recovery
continues under its existing scope, without upgrading old evidence.

The guarantee covers Linux descendants while their bootstrap remains alive under the selected
trusted target policy. Feature 172 restrictions remain inherited. `fixture-none` is cooperative
fixture scope only. Terminating or pausing bootstrap also destroys or stops its guardian,
including SIGTERM during controller cleanup, SIGKILL and process-wide SIGSTOP. This slice does
not solve those cases, full filesystem/egress containment, process-count budgets, reboot recovery,
Python runtime sealing, trustworthy failure settlement or multi-host scheduling.

Validation uses inert local C/bootstrap fixtures only. No model, WebAgent, remote/company
evaluator, real solver campaign or `.env` access is authorized for this slice.
