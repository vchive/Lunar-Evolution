# Validation state

Status: SDD preparation only. No Feature188 source, tests, runtime API, CLI,
materialization or Linux platform evidence exists from this preparation.
Only document-content and whitespace checks were performed. No tests, target
interpreter, provider, model or evaluator were run for these files.
Existing Feature171/177/184 results establish their original limited scopes only.

Implementation begins only after Feature187 final-head Linux acceptance.
The following is the required future validation plan, not a passing result.

## Parser and bounded work

Use inert explicitly selected roots/files. Test canonical roundtrip, original
declared/tree/target/version pins, every file role and empty directory membership.
Reject missing/extra/unknown/duplicate fields, malformed UTF-8, duplicate JSON
keys, unsafe names, aliases, noncanonical tables, offset overflow/gaps/overlap,
trailing bytes and independent file/entry/depth/byte/table/frame limits.

Force frozen DTO collection/scalar mutation and verify refusal before custom
len/index/iteration/hash callbacks, serialization or unbounded work. Parsing
must perform no filesystem read, launch, target import, write or chmod, and must
never produce a live ownership handle.

## Materialization and actual kernel seals

Actual Linux tests must verify all four seals on the original object and exact
frame/table/payload bytes. Exercise copy/read/seal/reverify faults, missing support,
each missing seal, ordinary unlinked files, shared writable mappings that make
F_SEAL_WRITE fail, and F_SEAL_FUTURE_WRITE as an invalid substitute.

After sealing, write/pwrite/ftruncate and new shared writable mappings must fail.
MAP_PRIVATE memory mutation must leave the underlying file digest unchanged;
this is not process-memory protection. Source byte/stat/parent/tree drift before
or during copy refuses. Source replacement after sealing must leave the returned
material unchanged while the original source verifier refuses its drift.

No test may silently downgrade to chmod, a private copy, a read-only mount or
a host-installed dynamic interpreter when the selected mechanism is unavailable.

## Ownership, deadline and cleanup

Test original FD identity, foreign reuse of its numeric FD, same-byte different
object, reader duplicates and exact original cleanup authority. A foreign object
must not be closed because its number appeared in a descriptor or observation.

One original absolute deadline applies throughout; test boundary expiry and no
budget renewal. Inject OSError, KeyboardInterrupt and SystemExit at each resource
acquisition/copy/seal/verification boundary. Every still-owned FD must close,
primary errors must survive cleanup faults, uncertain cleanup must remain explicit,
and source files/permissions must remain unchanged.

An inert static local reader can prove deliberate parent-owned delivery of the
single framed sealed FD. It must retain actual size/hash/seal/census observations
and reap/close its original process/FDs. It does not establish CPython loading,
production native control v2 admission or additional grants.

## Evidence and limits

Record actual focused counts, platform skips, first compiler/startup/test failures,
raw XML paths and hashes, Ruff/compileall/diff results and final exact-head Linux
inventory when implementation exists. Darwin unsupported-unit checks and skipped
kernel tests cannot substitute for Linux sealing execution. Do not sum overlapping
focused/native/current suites or borrow another head's CI result.

All evidence must retain `runtime_load_protection=false` and
`production_admission=false`. Feature189 must separately prove a real pinned
static CPython image, frozen encodings/importlib/stdlib/dependency closure and
actual native launch/FD/deadline/pipe/cleanup behavior before any later claim.
No arbitrary Python project, real campaign, model, WebAgent, remote/company
evaluator, .env, credentials, service or multi-host scheduler belongs to this plan.
