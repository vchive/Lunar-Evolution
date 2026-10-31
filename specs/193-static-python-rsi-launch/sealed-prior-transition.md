# Original outputs to sealed successor staging

This continues Feature 193 after PR204 without changing its frozen source. The
existing worker-input-view runner remains the only integration path; no new CLI,
runner, report schema or acceptance authority is introduced.

## Contract

After the original worker's verified terminal event, capture each declared output
through the same original file descriptor used by its complete held output-tree
walk. Verify the declared bytes, size, execution bit and original name identity.
Write the bounded bytes into an attempt-owned Linux memfd, apply WRITE, GROW,
SHRINK and SEAL seals, and reread that original sealed object against the pin.
The complete group remains pending until the original tree, after-readback
phase and lifetime release all succeed. Failure publishes no partial group.

The same custody instance retains the original sealed objects across commands.
Every subsequent prior snapshot must obtain its bytes from that bank, matching
the original records exactly. It must never reacquire its staging source from
the mutable work pathname or accept detached records as replacement ownership.
Work copies remain available to the existing reports and consumers and retain
their original drift checks. Existing source/toolchain validation is unchanged.

Use the original execution checkpoint throughout acquisition, seal verification
and copying; do not create a new deadline or retry. Bound aggregate bytes and
descriptor use before allocation. Close all owned handles on every attempt exit,
including control exceptions. Preserve the primary error and report uncertain
cleanup; never close a descriptor known to have been reused for another object.
No kernel capability fallback is allowed.

## Validation and limits

Run one concentrated affected regression after integration. Linux tests must
exercise actual memfd seals against writes, truncation and writable mapping;
also cover immutable capture despite later work mutation, group failure,
identity/record drift, original cancellation and complete resource release.
Integration tests must demonstrate that a later command's prior snapshot uses
the original bank and cannot receive a failed pending group. Ruff, compileall
and diff checks remain required.

This supplies a kernel-protected output-to-staging carrier. The destination
prior directory is still an ordinary read-only guest bind: interval-wide
protection of the worker's consumed backing remains unfinished. Complete driver
inputs, source/toolchain protection, external-writer exclusion, accepted static
image/material ownership, first scheduler context, production CLI and local
case acceptance remain separate work. All existing authority claims stay false.
Direct memfd guest binds require their own real rootless Podman compatibility
evidence and are outside this bounded change. No model, WebAgent, remote
evaluator, real solver campaign or original benchmark mutation is authorized by
this contract.

## Frozen affected regression

Frozen `634ac185d12f150f388fbddfec98755c50e0976d`, tree `786af733dce681dae110d21a3b9f65d0fd8f1f2e`,
passed all 2,363 cases in 53 complete affected files on Linux 3.12.3 in 51.672603268s.
All 85 additions passed; there were zero failures, errors, skips, retries and
timeouts, and the original child was reaped. The 2,799 source files match their
Git blobs, modes and archive, with identical original before/after observations.
Ruff, compileall and diff checks passed.

Independent original review `cb3fbaa69dd5472ed55416b1fd99c67c145e94697d8160f9a865525bc151968d`
verified all 53 file groups and reconstructed all 85 new raw JUnit keys from static
AST parameters (59 kernel-owner cases and 26 integration cases), without importing
pytest or rerunning tests. Original evidence is under primary ignored
`validation/sealed-prior-transition-20261031/`.

## Separate actual compatibility observation

The same frozen `634ac185` source completed one fresh six-command inert Podman
observation in 14.828434830s within the original 600s allowance. Prepare and
execution were each dispatched once, with zero automatic retries or timeouts,
empty stderr and the original child and SSH transport reaped at rc0. All 2,799
source files and 308 directories remained equal before/after.

Independent audit `482eeb80a33c14d40eb32e6307406a76ae9664f34b1376531ef36c1148cf55c5`
passed all 68 checks: 663 safe unique archive members, 662 manifest records,
505 payload files, 102 VFS and 108 lifetime original records, all original role
inventories, FD identity/bytes/pins, five phases and six command vectors. Prior
input counts were 0/2/4/6/8/9. Fixture inputs and object/archive/link outputs
matched exactly. This is finite inert compatibility evidence, without runtime,
production, closure or publication acceptance.

The first 60s wrapper timeout affected only source transfer, before preparation
or execution. Its partial file is retained. A separately bounded transfer
recovery completed before the first prepare and smoke dispatch; the successful
execution is not a retry of a failed smoke.

## Narrow cleanup-recording supplement

Frozen `de066089957c3dd205d3bf07e9a81c45528a35b9`, tree
`2c6284372fd94757d2d30990cbfd2d8b988d4c2f`, additionally persists the private
cleanup-unknown note when begin/snapshot acquisition fails before returning
control. It preserves the original error and does not alter the successful path.
Two complete Linux files passed separately: 28 integration and 82 aggregation
cases, 110 total including two additions, in 3.671546345s/600s, zero failure,
error, skip, retry or timeout, with the original child reaped. All 2,799 source
files matched before/after and Git blobs/modes; Ruff/compileall/diff passed.

Independent original review `0347ed863d4fa03c6d78170ae269717ff8b173c0c7cbd21896cbdc5f3071bf1c`
verified the base plus eight exact file deltas, all six original payload hashes
and the exact 110 JUnit keys including the two new static AST keys. This is a
separate supplement, not a rerun of the 2,363-case batch or six-command smoke.
The latter remains evidence for 634, not a claimed de066 execution. Final-source
CI/source review and main integration remain pending. The expected inventory
is 27,788 keys per Python (27,654 passes plus the same 134 skips); this is a
prediction, not an observed CI result.
