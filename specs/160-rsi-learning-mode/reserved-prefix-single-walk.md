# Reserved BRS prefix normalization in one ordered walk

Status: implementation integrated; concentrated regression pending. Production admission and
online publication remain false. This is a pure-computation change inside the
existing Feature 160 / 189 boundary; it adds no service, schema or authority.

## Problem and existing evidence

`reserved_history` receives one freshly reconstructed tuple of settled `batches`,
then calls `validate_brs_reserved_prefix` separately for slices of length 0..R.
The same old execution DTOs, complete root payloads, descriptors and material pins
are therefore normalized repeatedly. Batch i is normalized R-i times. R is bounded
by eight; this is bounded repeated work, not evidence of unbounded complexity.
`_root` also checks all preceding executions inside each full root, amplifying
that repeated work. Existing 600-second mixed stack samples repeatedly include
reserved_history / history / rejection material paths, but samples are observation
locations, not CPU percentages or call counts. No predicted suite speedup is made.
The earlier fresh matcher micro changed a local median by about 2%, and does not
close the mixed timeout. No new profiling, micro, mixed or model run is authorized
by this document.

## Contract

- Keep public `validate_brs_reserved_prefix` and `validate_brs_reserved_append`
  signatures, output bytes, ordinary validation order and refusal behavior.
- For the private original owner, normalize the same freshly read batch tuple once
  and return exactly the prefix facts formerly produced for lengths 0..R.
- Encode the empty prefix before touching batch zero. After normalizing each batch,
  encode that complete prefix before touching the next batch. The domain, every
  normalized member and complete projection still pass original `_canonical` /
  `_plain` byte, graph, depth, identity, candidate and aggregate limits at emission.
- No shared decoded prefix, authorization result, validation cache or cross-call
  context is introduced. Every emitted result contains immutable bytes only.
- Keep `_original` and all its original per-row canonical/128-KiB gates unchanged.
- Keep every SQL/FS/ledger/owner/budget/deadline observation and all history walks;
  do not replace the full history with a tail query or use old live owner heads.
- Keep the original per-history-entry transition / association / head checks and
  historical rejected/published material reobservations unchanged.

## Design

`_validate_brs_reserved_prefix_walk` contains the original domain and normalization
body. The public single-prefix wrapper selects non-collecting mode, so it encodes
only the final prefix in the same order as before. Private
`_validate_brs_reserved_prefixes` uses collecting mode; it emits 0..R in order.
`_project_brs_reserved_prefix` contains the unchanged original projection and final
three canonical encodings. `reserved_history` replaces only its repeated pure
slice-comprehension with the private collecting call.

All helpers are module-level functions with no closures or retained state. The
existing reserved policy already scans every function and namespace in
`rsi_brs_lineage_prefix` and `rsi_brs_reserved_owner`, records their source hashes,
and pins code/globals/defaults/kwdefaults/closure captures/attributes/annotations
and aliases. The new helpers and owner import alias consequently enter the original
module/code/capture/source policy without a second manually maintained allowlist.
New drift cases explicitly cover these facts. No policy exemption is added.

## Validation to perform after integration

1. Existing lineage prefix, reserved rejection/owner and reserved policy suites.
2. New differential cases: 1..8 published/rejected/mixed waves, including empty
   prefix; all canonical/domain/batch bytes equal separate public validations.
3. First-refusal comparison for association, claim, execution, root depth,
   descriptor capacity, missing material, inode alias, and earlier-prefix capacity
   followed by a later malformed batch.
4. Verify each execution/root normalizes once, while complete encodings occur in
   order 0..R; inputs preserve identity and outputs remain detached immutable bytes.
5. Pure no-I/O / foreign collection hooks; helper code/defaults/annotations/global
   aliases and owner alias drift must refuse at original policy.
6. Focused regression, ruff, compileall, diff checks under the coordinated frozen
   source runner. Only after those pass may a new clean-source mixed be considered
   under its original deadline and fresh-evidence rules.

## Limits and remaining risk

Root validation inside one pass still checks each root's full historical execution
prefix. Every emitted prefix still encodes its complete value. Required fresh
history and material reobservations are unchanged, so major costs may remain.
This change does not claim to solve the original 600-second P0 timeout. Mutable
input mutation / executable rebinding is governed by the original enclosing live
policy, not a new promise of atomicity. Production remains unaccepted.
