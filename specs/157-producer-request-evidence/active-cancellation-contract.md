# Active broker cancellation contract

This local Feature 157 slice connects caller cancellation to an already admitted HTTP
request. It closes the observed gap where native target cleanup succeeded but its host
HTTP worker continued until the request deadline or provider response. It does not close
the wider controller-crash, complete-egress, or external-project trust requirements.

The native attempt owns a thread-safe stop event. Its main thread evaluates the caller's
cancellation callback and sets the event on an unsuccessful execution path before waiting
for broker cleanup. The broker thread observes only this event; it never evaluates the
user callback or signals the producer's process group. The broker retains exclusive
ownership of its pipe descriptors. Normal successful execution does not set the event.

The request broker accepts an optional cancellation observer. Before admission, an
observed stop rejects the request without spending a slot or starting transport I/O.
After admission, cancellation polling uses bounded wait slices under the original
admission deadline. It neither starts a second request nor creates a fresh timeout.
Cancellation between admission and transport start records a cancelled admission without
starting the transport. The legacy path without an observer retains its existing wait
and timeout behavior.

For active I/O, cancellation is confirmed only when `cancel()` returns exactly `True`
and the same handle returns the `cancelled` terminal state. Only then may the host append
a cancelled terminal event. An early caller stop is not enforced-timeout evidence, and
no response is returned. Rejected cancellation, unexpected terminal states, and callback
errors remain unknown. Callback errors trigger best-effort transport cleanup but retain
the admitted request as active, so read-only journal recovery cannot upgrade it to a
complete result. Existing ledger timestamps may conservatively classify a terminal that
crossed its original deadline as timed out.

The pipe bridge checks the stop event during idle reads and response writes, before
request admission, and after request execution. A confirmed stop ends the bridge with
`reason=cancelled` and `complete=false`; it does not attempt a response write to the
terminated producer. Unknown transport shutdown remains `request_boundary_unknown`.
All stops keep the journal, admission counts, original identity and original deadlines.
Read-only recovery performs no provider I/O, retry, producer launch, or publication.

Acceptance uses only local fixtures: cancellation before admission performs no I/O;
cancellation of a blocked admitted request kills and reaps the exact HTTP worker;
unconfirmed cancellation and observer failures retain uncertain admissions; ordinary
completion and request timeout retain their prior semantics. The native fixture must
observe an authenticated target start and a received loopback POST before cancellation,
then verify native cleanup, worker reaping, no formal success receipt or publication,
and read-only recovery without new I/O.

Validation: final local combined source/tests run passed 1,875 cases with four Darwin skips and
zero failures/errors in 211.727 seconds (`/tmp/lunar-worker-recovery-final-20261001.xml`). The new
blocked-request native cases both passed and the broker cancellation/IPC/HTTP focus passed 69
cases on each of Python 3.11/3.12/3.13. Ruff, compileall and whole-branch diff checks passed. The
Ubuntu complete runner and controller-death recovery remain separate acceptance requirements.
