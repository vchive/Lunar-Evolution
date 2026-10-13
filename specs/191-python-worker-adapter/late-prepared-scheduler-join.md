# Opt-in local late prepared scheduler join

The ordinary native scheduler path keeps its existing arguments, fingerprint and
publication behavior. Merely binding a Python controller never enables this join.
An explicit immutable `NativeRSISchedulerContext.python_handoff_after_execution`
callback enables the local join and enters the provider fingerprint before the
controller freezes its original run request. The disabled projection stays unchanged.

The lower scheduler calls this supplier once only after native execution, durable
receipt persistence, strict output preparation and receipt/output comparison. It
passes the original receipt and output, and requires the existing
`PythonProducerAdmissionHandoffSidecar` carrying the independently retained original
file pin. The supplier owns the runtime observation/build step; the scheduler never
discovers a host interpreter, constructs observations, or adopts a freshly read pin.
An incomplete join configuration refuses before consuming an attestation.

After the supplier returns, recheck cancellation/deadline, original input/plan,
handoff pin/content, exact receipt, admission-plan and authority links. Only then
forward the handoff digest and original pin to the existing transaction. No prepared
journal or admission-attempt anchor is read during producer dispatch or supplier
registration. The transaction retains its original handoff/anchor/prepared ordering.

The transaction's durable `prepared_observer` invokes the provider's existing
`pin_python_admission_at_prepared_boundary` with the original supplied handoff pin
and its projected expected anchor. This dispatches to the existing DRS owner or BRS
ready/ack channel. Retain the returned record digest and capture the existing complete
reference binding; require it at every subsequent transaction evidence boundary and
successful scheduler return. BRS observations use the existing observation lock,
never the owner's mutation lock while a worker waits. Duplicate notification,
missing pin, changed input/handoff/record/reference or interrupted pin refuses; it
does not repair, retry or adopt a newer checkpoint. Already durable obligations and
unknown/committed publication effects remain retained.

This is local opt-in wiring tested with inert fixtures. It does not enable a real
sealed CPython runtime or production admission. Real installation, runtime/process,
owner/FD, broker journal and local solver acceptance remain independently required.
`production_admission=false`; remote evaluator and distributed services stay deferred.

## Verification

Focused tests must prove stage ordering; malformed/incomplete join rejection before
attempt; supplier cancellation, exception and original-pin/receipt/plan drift before
publication; unchanged ordinary path/fingerprint; prepared notification before the
first evaluation; original record/reference required after pin; DRS/BRS owner routing
and refusal without an active owner. Existing prepared-boundary, native scheduler,
admission-flow/publication compatibility tests remain required.

Local Python 3.13 validation passes 47 distinct cases across the two new suites
and existing prepared-boundary suite, plus 73 disjoint original scheduler/outcome/
provider compatibility cases: 120 distinct passes, no failures/errors/skips. The
final supplier/observer one-shot refinement reruns the same 12 provider cases;
that replay adds no distinct case count. Ruff, compileall and diff-check pass.
JUnit is retained at `/private/tmp/lunar-scheduler-join-focused-20261013.xml`,
`/private/tmp/lunar-scheduler-join-compat-20261013.xml` and
`/private/tmp/lunar-scheduler-join-final-20261013.xml`. An initial test fixture
failed because its BundleGroup omitted the required material-path argument; the
fixture was corrected without relaxing product checks. Final integrated source
still requires its own CI and the independent owner/channel composition review.
