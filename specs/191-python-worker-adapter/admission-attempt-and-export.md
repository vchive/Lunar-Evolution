# Admission-attempt content anchor and detached adapter export

This provider-free slice adds retained content consistency to the standalone
publication transaction and a common evidence export for OpenEvolve/Shinka.
It does not complete the live controller admission flow or sealed CPython
runtime acceptance.

## Admission-attempt anchor

`python-producer-admission-anchor.json` contains a canonical
`lunar-python-producer-admission-attempt-anchor-v1` record. Its self-digest binds
attempt/run/journal IDs, binding/handoff/terminal/runtime/native-receipt/plan
digests, authority fingerprints, request budget, original timeout and deadline.
Fractional timeout/deadline values are preserved exactly. Parsing requires a
retained nonzero digest, exact primitive types, bounded canonical UTF-8 JSON
and no duplicate keys or nonfinite numbers. Reused DTOs are revalidated.

The transaction derives this projection from the independently pinned original
handoff. It creates the anchor before the immutable prepared intent, then
revalidates it after caller checkpoints/timeout callbacks and before publication.
An interruption before or after the prepared-intent write reuses the same
retained anchor without rewriting it. An existing prepared intent with a missing
anchor refuses; retry must not manufacture replacement evidence. Partial or
unknown writes remain available for inspection.

Storage is bounded to 256 KiB and requires a regular `0600`, single-link file.
Held ancestor handles, nonblocking no-follow opens, pre/open/post/named stat
checks, fsync and held-descriptor readback detect replacement within an
operation. FIFO, symlink, hardlink, mode drift and incoherent reads refuse.
Exact existing bytes can be replayed read-only.

The anchor pins **content**, not the original anchor inode across operations.
A same-byte replacement is allowed by this content contract. Original handoff
inode identity remains owned by `PythonProducerAdmissionHandoffFilePin`.
Coherent rewriting of every trusted retained anchor is outside this local
contract. Controller/ledger admission-attempt binding and standalone recovery
integration are still pending; this change does not retrofit the earlier RSI
producer binding/run proof.

## Detached producer adapter

`PythonProducerAdapterEnvelope` uses the
`lunar-python-producer-adapter-v1` canonical domain, bounded to 4 MiB. The public
surface is `build_python_producer_adapter_envelope`,
`parse_python_producer_adapter_envelope` and
`verify_python_producer_adapter_envelope`. Supported producer IDs are
`openevolve` and `shinka`. There is no evaluator/admission entry point.

Build/verify reparses the original binding, terminal, runtime-observation and
result wires. It compares producer identity/fingerprint, contract, run/journal/
launch identity, original deadline, request count/budget, interpreter byte/size/
device/inode, version/cache tag, existing ABI-prefix policy, argv/orig_argv,
startup flags and pycache claim. Frozen DTO mutation, unsupported collection
types, missing digests, malformed nested records and admission upgrades refuse.
Parse validates retained internal consistency; verify additionally compares the
envelope to the caller's original binding. Neither authenticates child claims.

`production_admission` is always false. The adapter performs no I/O, process
launch/observation, budget consumption, evaluator call or publication. Actual
OpenEvolve wrapper/Shinka SQLite export lifecycle composition, exact ABI-profile
acceptance, independently observed sealed runtime and local exact-evaluation
authority remain separate gates.

## Verification

The dedicated `python-admission-export.xml` inventory combines anchor DTO,
anchor I/O, transaction interruption/callback and detached adapter tests. It
requires zero failures, errors and skips on Linux Python 3.11/3.12/3.13. Existing
recovery, admission, handoff-pin, preparation and observation reports retain
their separate inventories. Provider-free evidence does not count as successful
CPython execution, real solver campaigns or production admission.
