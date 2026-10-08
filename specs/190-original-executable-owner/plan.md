# Plan — internal owner plus existing callers

Internal API names below are frozen for this implementation. Final Linux
acceptance remains required. Preserve public DTO shape/export names and legacy helper call sites.

## Proposed implementation and APIs

1. Keep `src/lunar_evolution/linux_executable_binding.py` as the public facade.
   Prefer an unexported `_LinuxExecutableOwner` and owner registry in this module
   for the smallest review; a private `_linux_executable_owner.py` may be split
   out only if it makes that implementation clearer. Do not use the Feature188
   data material API as an executable owner. Its anchor/borrowed/identity pattern
   is a reference, not inherited acceptance or interchangeable semantics.
2. Proposed internal `_validate_original_linux_executable(binding) -> None`:
   exact handle/registry identity; original public scalar projection; original
   source-derived image pins; original anchor and borrowed object identities;
   mode/size/CLOEXEC/full seals; independent bounded `pread` image digest; stored
   deadline/clock. No external numeric FD, parsed descriptor or custom callback
   may supply ownership. No new caller deadline parameter.
3. Proposed internal pair registry binds the exact `TrustedExecutablePair` to
   its two original factory handles and immutable original projection. Proposed
   `_validate_original_linux_executable_pair(pair) -> None` verifies both handles
   and the public pair projection. Constructing a lookalike pair is not enough.
   Keep the registry alive only during the producing `ExitStack` context.
4. Call that check before Linux control encoding and after final launch/grant/
   deadline checks immediately before `native_trusted_attempt`'s `Popen`; repeat
   before `start_native_guardian` passes the bootstrap executable to its watcher.
   Validate the direct helper result immediately before `producer_process`'s
   `popen_factory`. Snapshot path/pass-FD operands from the validated original
   projection; do not recompute ownership from mutated public fields.
5. Pair entry and exit must map fixed `LinuxExecutableBindingError` to existing
   `TrustedBootstrapBindingError` boundary behavior; the current try block only
   maps enter-time errors. Context-exit cleanup errors must not bypass the native
   runner's binding error handling or mask a body exception. Legacy producer
   error mapping may retain its existing binding-unknown category; receipt
   fields and schemas remain unchanged.

## Acquisition and cleanup discipline

Use one original anonymous memfd anchor plus a CLOEXEC borrowed duplication for
the existing executable role. Pin identity before any public exposure. Track
source/anchor/borrowed independently from the public DTO, including interrupted
creation, first-fstat, chmod/copy/fsync/seal/duplication and post-operation
deadline failures. Independent memfd readback must occur after actual complete
seals and before yield; input-stream hashing alone is insufficient.
Use `fcntl(F_DUPFD_CLOEXEC, 3)` for the borrowed descriptor so closed stdio cannot
be appropriated. The extra anchor is not added to either native pass-FD list.

For acquired private numbers not yet identity-pinned, the frozen rule is: only
the existing trusted controller's no-private-rebind assumption can justify the
first release of that unpublished acquisition. A later `fstat` is not promoted
to original identity. If that relation is uncertain, preserve fixed
cleanup-unknown evidence and a possible leak, never close a known foreign
object, and do not claim unconditional zero-leak cleanup. No unpinned handle
is exposed. A close with an unknown result is never retried by number.

Attempt release of every owned role even when an earlier release fails or raises
`KeyboardInterrupt`/`SystemExit`. Snapshot a primary exception before cleanup.
Preserve its identity/traceback; append only a fixed non-sensitive note. Without
a primary, any uncertainty raises the fixed owner cleanup error. Do not call the
expired checkpoint as a condition for closing owned FDs and do not blindly
retry a close whose result is unknown.

## Exact files planned

Required code: `linux_executable_binding.py`, `trusted_bootstrap_binding.py`,
`native_trusted_attempt.py`, and the one legacy pre-spawn check in
`producer_process.py`. No `native_bootstrap.c`, native v2 encoder, registration
or receipt schema changes are needed for this controller-side owner slice.
`__init__.py` exports stay unchanged; an internal validation helper is unexported.

Required tests: extend `test_linux_executable_binding.py` and
`test_trusted_bootstrap_binding.py`, add a focused
`test_linux_executable_owner.py` if needed for fault inventory, and focused
integration cases in `test_native_trusted_attempt.py` / `test_producer_process.py`.
Use the existing inert static native fixture; no CPython189 image is built here.
Add a dedicated Linux owner XML/gate to `.github/workflows/test.yml` only after
the actual case identities/counts are frozen. Record validation/tasks and a
limited owner doc/HANDOFF update after evidence exists.

## Existing test seams to preserve

- `test_producer_process.py:640` patches the imported
  `producer_process.sealed_linux_executable` unsupported context; preserve that
  path and fixed unsupported error mapping.
- `test_producer_process.py:597` changes source bytes inside `popen_factory`
  after sealing. It must still run the original admitted image; a pre-spawn
  owner check must not add a fresh source-path revalidation that defeats this.
- `test_linux_executable_binding.py:50,76,89` use `deadline=inf`; preserve helper
  compatibility and add finite-boundary tests separately.
- `test_producer_process.py:892` uses a finite clock iterator to prove preparation
  budget expiry. Keep its semantic earliest-expiry path; additional checks must
  not make a brittle call-count failure the intended assertion.
- Native tests patch `runner.subprocess.Popen` with real subclasses, notably
  `test_native_grant_control.py:192`, `test_native_deadline_anchor.py:159,380`
  and `test_native_trusted_broker_cancellation_e2e.py:70`. Preserve that concrete
  process class seam and its separate native watcher calls; validate that
  guardian handoff too. Do not wrap `Popen`
  with an unrelated proxy or replace it with a fake acceptance path.
- `test_trusted_bootstrap_registration.py:31` intentionally constructs detached
  pair DTOs for record-validation tests. Keep those tests distinct from live
  native owner acceptance; no owner requirement is added to that public record
  API in this slice and no detached test is counted as live ownership evidence.

## Sequence

After188 G0, freeze this scope/API/fault contract, implement owner and helper
tests, implement pair/pre-spawn checks, then run focused/static checks and exact
Linux owner/native compositions. Independent raw audit and merge precede
Feature189's use of this owner.189 installation research can remain a draft;
neither a draft nor190 owner acceptance completes CPython/runtime admission.
