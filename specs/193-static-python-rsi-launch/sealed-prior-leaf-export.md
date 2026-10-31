# Command-owned sealed prior leaves

This bounded continuation of the sealed staging carrier prepares the original
bank for a later worker's exact file binds. It preserves the existing runner,
backend defaults, reports, CLI and authority claims. The packed command frame
cannot itself be bound as several independent files: each record occupies only
a range within that frame.

## Owner contract

`bank.export_worker_prior(records)` accepts exactly the committed bank inventory,
with no pending group, active export or replacement descriptor supplied by the
caller. It copies each record directly from its original sealed entry into a
separate private Linux memfd, verifies the exact bytes and size, sets mode 0500
for executable records or 0400 otherwise, and applies WRITE/GROW/SHRINK/SEAL.
Recheck the original held leaf and all seals before publishing the whole lease.
Empty inventories are valid owned leases. Acquisition failure publishes none.

Use the original checkpoint throughout. Before any allocation, require at most
4,096 exported files, at most 4,096 bank-frame plus exported-file descriptors,
and combined bank plus export bytes within the original bank byte budget.
No capability fallback, new allowance or retry is permitted. An executable-mode
or memfd policy refusal remains a refusal.

The private lease constructs exact `(record path, /proc/original-pid/fd/owned-fd)`
mount pairs only from its original live handles. It verifies a borrowed leaf FD
against the corresponding owned object: device/inode/type, zero links, size,
mode, seals and bytes, preserving the borrowed offset. Matching detached bytes
or an unrelated sealed inode do not convey ownership. Reject use after close,
PID drift, foreign descriptor reuse and any record drift. The bank cannot begin
another output group while an export is acquiring or active.

Close once on normal completion, cancellation and failure. Closing the bank
also releases its export; every other bank frame must still be released when
one close is uncertain. Remove authority before attempting close, preserve the
primary exception, retain cleanup-unknown notes and never close a reused foreign
descriptor by its former numeric value.

## Validation

Finish owner implementation and meaningful boundary tests before one combined
Linux regression over the complete affected files. Exercise real Linux seals,
distinct file ranges, executable and empty leaves, exact inode binding, wrong
but byte-identical objects, allocation budgets, cancellation, all-or-none export,
close-once ownership, descriptor reuse and primary-error-preserving cleanup.
Run Ruff, compileall and diff checks after integration.

Independently review a separate finite rootless Podman mechanism observation
before dispatch. Reuse only the already checked inert executable and object
fixture; use fresh paths, the original local service, bounded time and zero
automatic retries. Directly bind an executable sealed leaf and a data leaf,
verify the initialized guest sees their original sealed inodes, and execute the
inert helper against the data leaf. Preserve any actual failure; ordinary-file
copying cannot substitute for a refused sealed bind.

## Remaining integration and limits

The production runner does not consume this lease yet. Wiring it requires exact
leaf mount vocabulary in the original OCI, worker inventory and retained-history
validators, plus the original lifetime ownership and cleanup. Do not globally
permit zero-link files or unplanned nested mounts. Protecting leaf bytes alone
does not establish immutable directory names, source/toolchain or complete
configured driver inputs, exclude every external writer, or accept a runtime.
Fixed-U/account/root/ACL/cgroup obligations remain separate. All custody,
installation, runtime, admission and publication claims stay false. No model,
real solver, remote evaluator or original benchmark mutation is part of this
batch.

## Frozen validation and actual compatibility refusal

Frozen `21d1662c4d056a94f6e771f56bc43feecc89f8de`, tree
`49849fa150e677577cab0d307e357c629d442225`, passed one complete affected Linux
3.12.3 batch: 59 original sealed-bank cases, 28 integration cases, 82 aggregation
cases and 41 new leaf-owner cases, 210 total, in 4.072062559s/600s. No failure,
error, skip, retry or timeout occurred; original child and SSH were reaped at
rc0. All 2,801 source files and 308 directories matched before/after, with eight
module origins fixed to the frozen checkout. Ruff/compileall/diff passed.

Root independent original review `4db5bcd247247037b7068465c4793060c7cbdaf29da14962be4d1abb3ad842b5`
verified Git/archive blobs and execution modes, all eight original payloads,
the 169 unchanged legacy keys and all 41 new keys by static AST expansion.
The original batch was not rerun. Evidence is under primary ignored
`validation/sealed-prior-leaf-export-20261031/`.

The separate reviewed v2 syscall probe used the same baseline memfd flags and
0500/0400 modes. Both sealed host objects and the inert image import succeeded,
but original Podman create returned125 with:

```text
Error: statfs /proc/1738954/fd/3: permission denied
```

No worker init, guest same-inode observation, backing mutation-denial probe or
helper execution followed. Probe elapsed0.192390364s and original parent
elapsed0.264517163s under120s, with one dispatch, zero retries/timeouts and
the original child reaped. Unknown container creation remains recorded; only
the known original image tag was removed, at rc0. V1 was preparation only.

Independent original audit29b3f70a… and root review35f4541c… verified all35
archive members, including34 declared records and their exact manifest. They
verify a retained failure, not guest compatibility. Evidence is under primary
ignored `validation/sealed-leaf-probe-20261031/`. This establishes only the
refusal of the requested proc-FD create path. The permission mechanism and
other possible paths remain unproved; there was no fallback or second probe.
Resolve original service/source visibility before runner integration. The
27,829-key inventory is expected-only; final-source CI/main integration remains
required separately.
