# Original scheduler live-modules sink input

## Scope

The existing original-attempt private pipe can receive an explicit
`FixedPythonLiveSinkRequest` through `NativeRSISchedulerContext`. The ordinary
success/outcome scheduler and reserved BRS preparation-only scheduler forward
that exact request to their existing single native attempt. No additional
launcher, worker, callback, factory or CLI path is introduced.

`None` preserves the previous call shape and fingerprint projection. Selection
adds only a read-only content/code projection. The request retains its original
installation, image and main-source comparison inputs; no expected values are
converted into observed startup facts.

## Retention and drift

The context validates the request against the original intent executable SHA-256
once before retaining it. It retains the request object and the identities of
all exact immutable request/installation fields. Repeated `__post_init__` calls
check this retained pin instead of refreshing it. Context normalization and
child `dataclasses.replace` copies retain the same request object and revalidate
its material. A fresh equivalent request, changed nested installation field,
removed selected request, or newly inserted default request is drift.

Hot reserved BRS checks compare these retained immutable identities; they do not
rehash the entire image on every poll. Full native attempt validation remains
inside the original runner before nonce consumption and spawn. Original budget,
claim, receipt, publication and execution order remain unchanged.

## Verification boundary

`tests/test_rsi_live_sink_scheduler.py` uses the real synthetic sink validator,
original scheduler composition and original BRS exchange with explicitly inert
process/publication doubles. It covers opt-in/default projections, immutable
drift, normalization/copy retention, all wrappers, original attempt/receipt/output
order, ordinary dispatch, reserved preparation dispatch and its hot gate. It does
not demonstrate an actual solver process, authenticated live runtime, immutable
custody, cleanup acknowledgement or production admission. Those claims remain
false and their existing independent validation work remains required.
