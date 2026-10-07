# Plan

Add a standalone bounded no-follow `native_deadline_binding` publisher/observer and strict pure
descriptor parser. Keep it independent of bootstrap/attempt modules to avoid import cycles.
Extend the existing native consumption parser and registration publisher with an exact v2 branch;
preserve exact v1 parsing. Return the validated binding in the read-only attempt projection.

The formal attempt freezes the publisher's pin and the exact consumption claim, rechecking both
claims and deadline at gate and publication boundaries. Recovery freezes the validated registration,
consumption/handoff and descriptor, revalidates before each cleanup signal and after cleanup, and
publishes an exact v2 unknown receipt. The pure worker verifier compares canonical record bytes to
the claim's pin but makes no filesystem/inode observation.

Parallel ownership: helper and inert tests; consumption/registration and protocol tests; root
attempt/worker integration and SDD; independent native recovery tests. Integrate then focused
regressions, Ruff, compileall, diff check, final-head Ubuntu3.11/3.12/3.13 complete CI and merge.
