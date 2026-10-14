# Explicit controller child native claim

## Scope and authority

`claim_python_producer_controller_child` is an experimental Python API over the
existing `PythonProducerControllerChildPreview` and `NativeEpisodeClaim`. It is
not called by controller default dispatch, resume or the CLI. It creates only
one row in the existing native claim table. It does not create a running episode,
invoke a receipt provider, launch a producer, consume an attestation, append a
checkpoint, reserve budget, evaluate a candidate or publish a result.

The caller must already hold the original controller ledger's run lock. A preview
is an observation and comparison pin, never an execution grant. The API validates
its exact DTO and bounded plan shape, reuses the existing pure plan parser and
context fingerprint, and resolves the ready child again under the lock. The
current root controller/gateway/ledger, request, memory, checkpoint, child proof,
original file pins, runtime inventory, complete plan, deadline and cancellation
gate must agree. Child context execution hooks supplied in the preview are not
adopted; only freshly resolved controller-owned dependencies are observed.

## Atomic checkpoint and claim

`RSILedger.claim_native_episode` adds two optional comparison pins:
`controller_run_id` and `expected_controller_checkpoint_sha256`. They must be
provided together, and the original controller lock must be held by the calling
thread on that exact ledger instance.

After `BEGIN IMMEDIATE`, the existing journal history is revalidated and its
head must equal the supplied original checkpoint. Claim creation then occurs in
the same transaction. A checkpoint change between preview validation and claim
creation therefore refuses without inserting a claim. The guarded path also
refuses any existing episode or native claim, including terminal results and
claims inserted by another caller after the initial preview check. It never
adopts a competing claim as a fresh attempt. The unguarded native API retains
its original recovery and terminal replay behavior.

There is no new table, claim DTO, receipt, sidecar or second authority. Claim
request/plan/identity hashing is unchanged. The existing journal retains the
original proof and budget/deadline evidence.

## Interruption and recovery boundary

After claim creation, the bridge rechecks the owner lock, ledger/gateway,
checkpoint, original producer proof, child files, request/memory and deadline,
and rereads the exact native claim. Post-claim drift or interruption preserves
the started claim. It does not delete the claim, roll back a completed insert,
adopt current disk pins, replace a proof, refresh the checkpoint or remint an
attestation. The caller receives no successful claim return after drift.

Repeated calls reject. Controller resume retains the existing read-only
`dispatch_not_accepted` or evidence refusal, without restaging, reclaiming or
reserving another invocation. A claim does not establish worker completion or
authorize replay; started/unknown requires a later independently validated
recovery/execution slice. This API intentionally does not implement that slice.

## Local validation and remaining work

Provider-free focused tests cover exact once-only claims, no execution effects,
unchanged original proof/checkpoint/budget, owner lock and ledger-instance checks,
request/memory/plan/proof/context drift, checkpoint and competing claim races,
paired CAS pins and retained started claims after interruption. Ruff, compileall
and diff checks remain required. Final-source CI and independent source audit
remain separate integration obligations.

Only inert local fixture bytes are used. No real runtime, CPython/toolchain,
model, evaluator, OpenEvolve/Shinka campaign, WebAgent or company platform is
accepted. `production_admission=false` stays unchanged. Actual child execution,
receipt/publication/recovery composition, full multi-episode DRS/BRS dispatch,
production CLI and P1 runtime acceptance remain open.
