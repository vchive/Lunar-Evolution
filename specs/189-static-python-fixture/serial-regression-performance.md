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

## Follow-up after `88005a30`

The single unprofiled Linux case on `88005a30` still failed: case 600.573 s,
suite 602.050 s. The primary refusal is native dispatch
`rejection_control_expired`; executor teardown reports `worker_unknown`.
It is not a direct `SolveExecutionBudgetExceeded` result. Live module receipts
and all 2,317 source-file byte/executable checks passed. Eleven remote evidence
files passed transfer verification. Fixture teardown removed its private
`/var/tmp/lrsi-*` directory before post-run collection, so the final ledger
could not be retained; no final-history progress claim follows from this run.
Evidence remains under ignored `linux-mixed-final-88005a30-yt5v_law/`.

The next bounded change removes temporary tuples/generators from exact type
dispatch inside reserved-policy `freeze()` and admission shape checks. Preserve
all scalar labels, container identities, recursion/node budgets, traversal,
finite-float refusal, DTO identity allowlists and callback refusal. It adds no
memoization and changes no source/SQLite/history/reference observation. Require
independent old/new projection/pin comparison and focused drift tests before
using it in another exact-source acceptance. A standalone seven-round parser
experiment observed only 3.81% lower record parsing cost and 2.33% lower copied
history-loop cost; those are local measurements, not acceptance or an E2E
speedup promise. Do not add a normalization cache without a separate backend
mutation analysis; replacing `textwrap.dedent` must remain observable.

The same projection may also observe each captured exact builtin dictionary
once, separately from the existing per-globals alias and shadow vectors. Keep
all namespace pins and every distinct domain, including equal-content private
copies; deduplicate only by captured identity and retain the domain vector as
an immutable tuple. Check all domain lengths, exact string keys and selected
bindings on every projection before the namespace alias/shadow pass. No
foreign alias is dereferenced and no cached validation result is introduced.
This reorders sequential observations and removes duplicate opportunities to
notice a concurrent mutation; it supplies no atomic snapshot. It does not
repair the preexisting global-builtins key race or claim a stronger concurrent
guarantee. Require copied-domain/key/binding drift and separate-shadow tests.

Independent builder comparison of `88005a30` with the freeze-only change
preserves the complete projection and all 830 function pins, 58 declarations,
19 module namespaces, 32 external members, 22 runtime edges, two limit pins,
35 registered modules, 39 builtin bindings and 62 globals domains. Nine
alternating rounds of 50 pure projections have medians 0.511397 s and
0.367023 s (28.23% less). Both builders use the same currently imported graph;
this is not a comparison of complete historical and current runtime trees.
Raw script and measurements are retained in
`freeze-dispatch-independent-microbenchmark.{py,json}`.

A second independent 9 x 50 three-way comparison includes the domain split:
baseline 0.539380 s, freeze-only 0.380856 s, current 0.371127 s. The current
graph shares one captured domain across the same 62 separately checked globals;
all original pins and projection agree. The domain split alone saves 2.55% in
this local function, both changes 31.19%. Source SHA and registered source
vector remain unchanged during measurement. The separate raw report is
`domain-split-independent-microbenchmark.json`; it is not E2E evidence.

The final local selection passes all 288 admission/row/type/domain/freeze/
policy/compaction cases. The new 39-case freeze suite covers scalar type labels,
foreign values/metaclasses without callbacks, finite floats and depth/node/
width limits; the domain suite has 19 cases, including both equal-content
private dictionaries independently mutated by bindings, foreign keys or size.
CI's combined exact-type/domain/freeze gate requires 91 cases without skips.
Whole-repository Ruff, src/tools/tests compileall and diff check pass. Exact
final-source unprofiled Linux acceptance and all 33 CI jobs remain separate.
The external-`/tmp` runner selection also passes all 204 cases after the new
test-file inventory is present.

The normalization memo prototype is not adopted: an independent counterexample
changes `re._cache2` while dedent/code/regex/re.sub/re._compile identities remain
unchanged. The original operation observes a different value and callback,
whereas a warm memo hides both. Pure local timing gains do not override that
backend semantic difference. This experiment creates no production cache.

## Call-local admission canonical verification

Exact head `72232018` still exhausts the unchanged 600-second execution control
in the Linux three-child mixed case. Its independent 5090gpu replay and all
three `current-3` CI shards fail; the earlier passing replay on source-equivalent
`5c37f4c5` does not establish reliable completion. Preserve those first failures.

The next bounded change shares the canonical bytes already verified by the
admission dictionary parser with its enclosing JSON parser. Currently the
outer parser repeats `to_json()` after the dictionary parser has just checked
that complete serialization against the detached input. A private same-call
result can carry both the parsed record and those verified bytes. Each call
must still read and parse fresh input, reject duplicate/noncanonical JSON,
validate all shapes, digests and nested evidence, and detach the returned
record. Public digest/serialization methods must continue revalidating mutable
nested evidence. No stored validation cache or record field is introduced.

Require focused refusal/detachment/fresh-parser regressions and a pure parser
comparison before another exact-source Linux original-budget replay. A parser
microbenchmark is not end-to-end acceptance; configured build/runtime and all
production/publication gates remain open.

The implementation retains that private result only on the current stack.
Six additional row cases cover bytes/string/dictionary entry points, two
independent fresh parses, detached anchor/pin data, post-return mutation and
a changed nested parser on a later call. The row gate is now 24 cases. The
overlapping admission/type/flow/policy/checkpoint selection passes 308 cases;
an independent admission/type/flow selection passes 239 cases. Ruff,
src/tools/tests compileall and the current diff check pass.

An exact baseline-source comparison (`72232018`) against the new parser uses
two retained read-only snapshot rows and 16 differential valid/invalid inputs.
Nine alternating 200-iteration trials have local medians 0.184795 s and
0.117151 s (36.61% less parser time). The script, exact source hashes and raw
measurements remain ignored in `admission-json-reuse-microbenchmark.{py,json}`.
This is a pure local parser measurement, not an E2E speed or acceptance claim.

## Single-history-walk reference context reuse

The single unprofiled Linux replay of exact `92a57408` still fails under the
original 600-second control. The next bounded slice may reuse a detached
reference/plan/journal context only inside one
`_controller_checkpoint_history_tx` invocation, selected by the same episode ID
and equality of the complete canonical reference bytes. No ledger field,
cross-call cache, shared returned payload, or durable validation result is
introduced. The public parser defaults continue performing complete parsing.

Each freshly decoded checkpoint still passes the exact reference-map and key
types, recursive shape/depth and finite-number checks, each reference's
512 KiB canonical limit, and the whole map's 8 MiB canonical limit. First,
added, or changed references still pass the complete plan/journal parser and
canonical round-trip checks before the existing monotonic comparison. Exact
canonical byte equality must retain the distinctions between integers,
floats, booleans, and signed floating zero; Python dictionary equality or only
a digest is insufficient. Every fresh row JSON parse, revision/parent/digest
check, and missing/changed-reference check remains. Final retained admission
SELECTs, exact-text full row parsing, independent columns, and context/record
binding also remain fresh and complete.

The current walk may retain contexts for its preceding validated row rather
than only the final row. These detached contexts must not be inserted into
the returned checkpoint payloads, exposed through public parser results, or
reused by a later invocation. Invalid changed values retain the complete
parser path before history-drift comparison; reuse is not a repair route.

This deliberately reduces repeated nested-parser observations during one
walk. It does not preserve the old observation count for arbitrary concurrent
parser/backend rebinding inside that same invocation and does not claim an
atomic interpreter snapshot. Source/policy observations around the walk are
not removed. Later calls must parse references afresh and observe changed
parsers or input bytes. Require focused reuse, mutation, exact-type/numeric,
size/depth, fresh-row, and hash-valid-history-drift regressions, followed by
Ruff, compileall, and diff checks. No E2E or speedup result follows from this
contract; exact-source Linux acceptance and final-head CI remain separate.

An independent comparison loads the exact `92a57408` admission/store modules
and the changed modules against a retained, independently hash-verified
read-only snapshot copy. All four namespaces' 29 returned journal rows agree;
five separate in-memory database mutations retain the same refusals for
admission payload/independent-column and checkpoint payload/parent/digest
drift. All 13 reference visits remain, while complete fresh DTO contexts fall
from 13 to two. Nine alternating 25-iteration history trials have local median
times of 0.2935065 and 0.1505321 seconds (48.71% less). The exact source hashes,
snapshot identity, script, and raw comparison are retained in ignored
`history-context-reuse-microbenchmark.{py,json}`. This measures the copied
history parser only; it is not an E2E speedup or acceptance result.

The final local selection passes all 649 admission/history/type/cache/identity/
policy/runner cases, with zero failures, errors, or skips. It includes 27 new
history-reuse cases, the existing 24-case row gate, and 204 regression-runner
cases with an external `/tmp` basetemp. The independent 51-case selection
overlaps these results and is not additive. Whole-repository Ruff,
src/tools/tests compileall, and current diff checks pass. CI now requires the
27-case history-reuse gate explicitly; the exact-source Linux replay and final
three-version CI still have to pass before merge.
