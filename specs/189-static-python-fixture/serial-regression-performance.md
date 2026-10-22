# Original-budget serial regression performance

This continuation addresses the existing three-child mixed serial regression
gate. It changes no solve budget, policy/admission wire, evaluator behavior,
checkpoint digest algorithm or source-fingerprint output.

## Retained failure and diagnosis

Exact source `cfd76f8ed2fbe3e0a91c5f9240e852cc50a67c82` passed the local
Python 3.13.12 case in 468.41 seconds with `SolveExecutionControl(600)`.
The independent Linux Python 3.13.13 replay failed after 602.75 seconds with
`rsi_python_brs_native_dispatch_rejection_control_expired`. The original raw
stdout, XML, metadata and exit result are retained under ignored
`.lunar-evolution/validation/feature189-20261023/linux-mixed-cfd76f8-k2sex269/`.
This is a real open performance gate; a passing macOS case does not close it.

A separate single Linux diagnostic samples Python stacks every 0.1 seconds
without reading frame locals or altering source, budget or process fixtures.
At 120 seconds, repeated checkpoint-history traversal and full persisted-text
SHA-256 computation dominate active samples. The existing digest cache hashes
the entire SQLite text even on a hit. A separate pure policy observation
records 738 component fingerprints and 613 different source-cache keys;
the 256-entry LRU repeatedly misses, despite retaining only 391,348 source
bytes. Sampling results are diagnosis, not acceptance or timing guarantees.

## Two bounded pure-cache changes

1. The checkpoint digest cache may key by the exact immutable persisted
   Python `str`, plus run/revision/parent. Dictionary hash collisions still
   require exact string equality; no revision-only or stat-based shortcut is
   permitted. Avoid the additional UTF-8 copy and cryptographic hash used
   solely for the old cache key. Retain explicit entry and text-memory bounds,
   with LRU eviction. On a miss compute the original canonical checkpoint
   digest. Every call still reads and parses fresh SQLite rows and performs
   all revision/parent/digest/reference/history checks. Do not cache whole
   validation results, skip a row scan, or share mutable decoded histories.
2. The source-extraction cache may retain enough small entries for the actual
   graph, subject to a separate total source-text budget no larger than its
   old theoretical 256 x 96 KiB ceiling. Keep the exact source-content digest
   and full locator in every key, both fresh source-byte reads and all
   before/after ownership/code/backend checks. Defaults, closures, explicit
   code hooks and configuration hooks remain live on every fingerprint.
   Do not cache component identities or final fingerprints.

These two offline changes are now implemented in `rsi_store.py` and
`rsi_identity.py` with separate test suites. The digest cache retains up to 128
entries under a 16 MiB conservative unit budget and keys on exact persisted
SQLite text. The source cache retains up to 1,024 extracted-source entries
under a 24 MiB UTF-8 source-text budget (the former theoretical maximum). The
new digest suite covers same-length row replacement, fresh-history mutation,
exact-text hits, parent/revision/run changes, LRU/budget eviction, concurrency
and detached returned state. The source suite exercises 613 distinct small
components without extraction thrash and checks live drift and budget behavior.
The focused cache/store/identity gates have passed; the unchanged Linux mixed
case on exact source `3222c9d78f96ce484ca31d88969ee759c675a798` still failed:
602.633 seconds total, 600.945 seconds for the case, at the original control's
`rsi_brs_before_evidence` check. Its raw stdout, XML, source archive, metadata and
result are retained under ignored
`.lunar-evolution/validation/feature189-20261023/linux-mixed-3222c9d-nzbqln_7/`.
The original-budget Linux gate remains open.

Both caches remain optional performance aids. Misses, eviction and disabled
retention must produce the same digest/source as an uncached observation.
Source edits, same-length text replacement and identity/parent/revision drift
must remain detectable. Source-cache bounds must also hold for its existing
direct `clear()` test seam and replacement; clearing must reset bookkeeping.

## Mailbox and admission-row follow-up

The failure's `transport_observed` stage calls `retain_mailbox_observation`,
which performs three full `_mailbox_observe` passes and three independent
`_mailbox_readback` passes around process observations, append and readback.
Each full observation verifies owner/source state and fresh running/history
state, then checks live control callbacks and verifies running/history state
again. These checks bracket callbacks and mutable authority; the control
exception identifies exhausted budget, rather than proving the timer itself
is a hotspot. No such observations, locks or freshness checks are removed.

A separately authorized 0.1-second stack-only diagnostic uses the unchanged
`3222c9d` archive and original 600-second control. Its intermediate 300-second
snapshot no longer lists checkpoint-digest calculation among the top 40 leaf
frames. The largest non-wait leaf is the admission-row SELECT in
`_checkpoint_reference_rows_tx`; history SELECT/fetch, fresh JSON parsing and
source observation also remain visible. Sampling a C call site does not
distinguish database I/O, C execution and GIL scheduling cost.

That single diagnostic finished with one failure in 603.198 seconds (case
602.533 seconds), reporting `rsi_brs_rejection_ready_state_invalid` at the
active-ready recheck, plus an unknown worker attempt. It must not be relabeled
as a direct budget exception or acceptance. All 22 retained remote files and
the before/after 2,310-file source checks were independently verified. The
final sample has 5,425 ticks; checkpoint digest appears only seven inclusive
times, while history/reference work remains visible. GIL sampling bias and
diagnostic overhead prevent interpreting these counts as CPU percentages.

An independent read-only SQLite backup taken during that diagnostic contains
29 journal rows across four namespaces. Their combined conservative digest
cache cost is 4,575,200 units, below 16 MiB and 128 entries; no entry is
oversized. This snapshot supports no cache-capacity increase. It is a
mid-run observation, not the final history or a cache-hit measurement.

A separate 25-read, read-only `cProfile` of the 19-row namespace on an
independent, hash-verified copy shows the remaining pure Python costs: JSON
encoding 0.131 s, JSON decoding 0.077 s, and admission shape validation
0.069 s over the diagnostic profile. The whole loop took 0.624 s including
profiler overhead. SQLite `fetchall()` accounted for 0.006 s. This synthetic
read loop confirms that fully revalidating the two references stays materially
more expensive than the duplicate per-row canonical serialization; it does
not justify weakening reference checks. It also does not isolate filesystem
or CPU cost in the original multi-threaded failure.

The next minimal change removes one duplicate `record.to_json()` from
`_python_admission_row`. The full parser already compares freshly read exact
SQLite text to canonical bytes in `RSIPythonAdmissionRecord.from_json`.
An explicit exact-`str` gate retains rejection of canonical BLOBs stored in
SQLite's non-STRICT TEXT column; the public `record_corrupt` refusal is
unchanged. Every row SELECT, full strict parser, detached record, independent
column/created-at comparison, admission-reference binding and surrounding
history/state check remains live. No whole validation result is cached.

A pure microbenchmark over the copied read-only diagnostic snapshot compares
the exact `3222c9d` method with the changed method on two retained rows. One
pass invokes `to_json` six times before and four after. On local Python 3.13.12,
three alternating trials of 100 passes have median times 0.137619 and 0.103374
seconds, respectively. This measures only row parsing and establishes no
end-to-end speedup or acceptance. The script, snapshot provenance and raw
measurements are retained in ignored
`.lunar-evolution/validation/feature189-20261023/linux-mixed-profile-3222c9d-working/`.

## Verification

The 17 new row cases pass, as does independent review. The row/admission/BRS
publication-recovery/prepared-pin/evidence-composition selection passes 260
cases. Whole-repository Ruff, src/tools/tests compileall and diff check pass.
The local pytest run reports the existing 27,483 read-only temporary-tree
cleanup warnings and exits zero. Final-source Linux performance and CI are
still separate gates; these local selections overlap and are not additive.

Run focused cache/identity/store tests with independent canonical expectations,
fresh-history drift and capacity/eviction cases; Ruff, compileall and diff
checks; then rerun the unmodified Linux three-child mixed case on the exact
changed source under the original 600-second control. Retain all failures
separately. Final-source three-version CI remains mandatory before main merge.
This work does not close the static-image build or runtime gates in G1-G3.

## Exact types and distinct builtin namespaces

The single unprofiled Linux replay of exact `31b8c2cd` still failed at the
original 600-second control: case 600.958 s, suite 602.662 s, observed budget
600.320502001 s. The refusal occurs in the second mailbox observation at
`transport_observed`, with an unknown worker attempt. Its wrapper separately
missed the `tests.` prefix in the live test-module receipt; that receipt is
incomplete. Post-run import/hash checks are retained separately and do not
repair live provenance. All 2,315 source-file bytes/executable bits and nine
transferred artifacts passed independent checks. Raw evidence remains under
ignored `linux-mixed-final-31b8c2cd-65xd3bvk/`.

Admission shape and wire-entry type allowlists now use identity comparisons.
Set/tuple membership previously permitted unsupported metaclass hash/equality
callbacks, including spoofed builtin equality. Exact string keys are checked
before field-set comparisons. Full canonical serialization, strict parsing,
digest verification and detachment remain unchanged. Thirty-three pure tests
cover callback rejection and supported values.

A pure five-call `_policy()` CPU diagnostic separately identified repeated
builtin-domain scans: the builder appended the same globals namespace once
per function. The builder now keeps one observation per captured globals
identity on every projection. All function code/default/closure/global pins
remain; each distinct namespace still checks its live builtin alias, domain,
exact string keys, captured bindings and complete shadow vector. Different
namespaces sharing one domain are never merged. This is not a cross-call
validation cache or an atomic concurrent snapshot.

Twelve focused tests cover full namespace coverage, shared domains, live alias
replacement and binding/key drift, including four external namespaces whose
new builtin shadows are absent from function `co_names`. Independent review
passed the combined 45 new cases. An AST-isolated baseline from `31b8c2cd`
retained the same 830 function pins, projections and module identities; only
namespace observations changed from 830 to 62. Nine alternating rounds of
50 unprofiled pure `project()` calls had median elapsed times 0.722442 s and
0.507494 s (29.75% less). This measures that function only, not `_policy()` or
the complete mixed case. Script and raw measurements are retained as
`builtin-domains-independent-microbenchmark.{py,json}` in the ignored validation
directory.

The related admission/type selection passed 178 cases and policy selection
passed 64 cases (242 total). A runner selection passed all 204 cases with a
unique `/tmp` basetemp. Its first combined run retained 444 passes and two
runner failures: placing basetemp below the repository made nested pytest find
the parent configuration and emit prefixed node IDs. No product runner change
was made for that test-environment mistake. The original failure remains in
`final-type-policy.{log,xml}`, separately from the successful
`final-runner-external-temp.{log,xml}`.

A separately retained main-thread `cProfile` diagnostic of `31b8c2cd` used
`time.thread_time` but produced impossible SQLite time and negative self-times.
The timing data is INVALID and supplies no hotspot ranking or performance
claim. Its raw data and failing original-budget outcome remain preserved;
corrected live module receipts and source checks do not validate its timer.
The new source still requires its own unprofiled original-budget Linux replay
and all final-head CI jobs before merge.
