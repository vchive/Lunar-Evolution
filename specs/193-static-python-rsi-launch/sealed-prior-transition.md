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
