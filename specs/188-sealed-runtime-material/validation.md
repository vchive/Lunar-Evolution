# Validation state

Status: local implementation and portable validation complete; Linux sealing
acceptance is pending. Feature187 prerequisite PR21/run37738544048 passed an
independent final-source raw audit and merged as518f1f4 before coding began.

Root integration `/tmp/lunar188-composition-final.xml` contains 635 cases:
556 passed / 79 Darwin platform skips / zero failure/error. It includes the
274-case new focused inventory and 361 existing171/177 cases. Do not add these
overlapping suites to make another acceptance total. The new portable parser
131/131 and source IO55/55 pass; material owner suite is9/88 passed on Darwin,
with79 actual-Linux cases skipped. No Linux mechanism pass is claimed.

Ruff (`src tests tools`), compileall and git diff --check pass. The 708 package
exports are present and unique. Dedicated `runtime-material.xml` is wired into
CI with an exact274-case, zero failure/error/skip gate before the existing21
phases. Final exact-head Linux inventories and independent raw audit remain
required before integration.

First failures remain separate: the root initial missing-PYTHONPATH collection
is `/tmp/lunar188-existing-focused-first.xml`; source IO first39-case run had
38 passed/1 failed at `/tmp/lunar188-sourceio-first.xml` because the test injected
cleanup failure before its intended read failure. Narrowing that test's fault
injection produced the final passing55-case inventory, without weakening the
helper contract. Initial Ruff test sentinel/lambda style failures were fixed.

No interpreter is launched by materialization. The inert C reader has not run
on Darwin and still needs Linux size/hash/seal/FD-census acceptance. No provider,
model, WebAgent, remote/company evaluator, .env, credentials or real campaign
is used. Existing171/177/184 scopes are unchanged.

The following plan defines the required Linux evidence, not a passing result.

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
