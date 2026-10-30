# Original native scheduler scope passthrough

Status: narrow implementation slice; tests prepared for one concentrated parent
regression. This note does not establish an accepted build, runtime or root
installation.

## Problem and result

`run_native_trusted_attempt` already accepts an original `NativeWholeScopeOwner`
and `NativePycacheDiagnosticRequest`, but the enclosing native producer scheduler
and `NativeRSISchedulerContext` cannot forward them. A caller selecting the
existing installed scope therefore loses it before the original attempt. The
reserved BRS preparation call has the same gap.

Carry optional `whole_scope` and `pycache_diagnostic` through the existing RSI
context, ordinary success/outcome scheduler wrappers and reserved Python
preparation wrapper to the same single native attempt. Defaults stay None;
existing positional context arguments and unselected kwargs/projection stay
unchanged. The existing BRS call forwards those exact objects without changing
its claims, exchange, control bytes or policy graph.

## Contract

- Accept only the exact existing scope/config types. Reuse installed scope
  checks and original attempt acquisition; never acquire privileges, rebuild an
  owner from a DTO or open a replacement runtime.
- The context retains original scope/config objects and the initially selected
  fixed-U/custody/session children. None-to-new acquisition or child replacement
  after this pin is drift. The parsed finite profile values are frozen separately
  from its raw bytes, so a changed credential/path cannot retain an old hash.
  Repeated validation does
  not repin replacements. A finite configuration projection binds the original
  installation/journal/deadline upper bound and diagnostic observer/layout.
  It is not authority; live checks require the retained original scope.
- The native runner may shorten its original deadline. Extension refuses;
  fingerprinting retains the original upper bound, without hashing mutable
  lifecycle state. Fingerprinting never calls `check_before_launch` and does
  not mutate the scope or allocate a budget.
- A closed, wrong-installation, mismatched journal or replacement scope refuses
  before producer launch. Fresh dispatch checks expiry and one-shot scope state;
  historical/read-only checks do not renew a deadline or require fresh launch.
- Selected direct scheduler checkpoints revalidate before and after existing
  stage/cancellation callbacks, and at prepared/failure/final return, using
  historical mode after execution. An already finished scope cannot be dispatched
  again but remains inspectable while its original installation is held.
- Preserve original objects across failure/unknown handling. This seam neither
  closes the caller's scope nor retries or substitutes another attempt.
- The existing original fixed-U input owner may be passed only to the existing
  native input validator; it is never reconstructed. Fixed-U stager preparation,
  first root loader and interval-wide account/writer acquisition remain separate.
- Pycache config remains an incomplete diagnostic. No boolean is promoted to
  accepted pycache absence, runtime acceptance or publication authority.

These constraints continue Feature190 `spec.md` original-owner rules,
Feature193 `original-pycache-grant-binding.md`,
`remaining-implementation-boundaries-20261030.md` and
`original-native-observation-handoff.md`. A first context is prelaunch and does
not require this attempt's startup: actual startup/completion travel through the
existing late same-attempt handoff. No startup-only selector or fake request.

## Files and verification

Product files: `native_trusted_scheduler.py`, `rsi_native_scheduler.py`,
`rsi_brs_native_provider.py`. Independent focused tests cover opt-in/default
routing, all native wrappers, original object identity, context copy/revalidation
and drift, invalid scope refusal before launch, deadline shortening/extension,
failed/unknown outcomes retaining the caller's scope and reserved BRS routing.
The new test file has 45 expected parametrized nodes, not yet collected or run.
They use explicitly synthetic owners/effects, never imply actual root installation
or static CPython acceptance. The parent runs these with the combined focused
suite, Ruff, compileall and diff check after code freeze.

The Python plan-factory `_read_native` and its projection, episode stager, first
fixed root loader and expanded admission composer remain outside this change.
Passing scope inputs through these three scheduler modules does not make a
fixed-U Python producer or production CLI available. Each installed native scope
still binds its own original journal; it cannot be reused for a different child.
