# Feature 196 validation plan

## Reserved-wave serial working-tree status — 2026-10-19

The working tree contains the bounded reserved projection/prefix and ledger
observers, original reservation reader, preparation exchange, native
provider/completion, reserved owner/policy/rejection readers, private serial
driver and governed finalization readers. Previously reported focused evidence
includes 16 serial-finalization cases, 5 governed-finalization cases and 79
reserved-policy/provenance cases. These are component checks and do not replace
the integrated behavior gate below.

The latest natural two-child `rejected -> rejected` integration fixture run did
not complete owner admission and mailbox handoff; the underlying cause remains
under investigation before changing any fingerprint, claim, owner or lifecycle
gate. The earlier
`rsi_brs_reserved_prefix_material_path_invalid` failure at
`read_reserved_brs_prefix -> validate_brs_reserved_prefix` is repaired by strict
rejection-evidence path/pin mapping. The latest integrated run advances to
`rsi_brs_reserved_serial_settled_transport_missing`; no V01-V10 or F01-F05 item
is complete, and no public native BRS, production admission, remote evaluator or
real solver has been enabled.

## Staged-ACK prerequisites — 2026-10-18

This successor validates bounded primitives and their pre-arm wiring. It does not
validate a staged service, ACK visibility, permanent partial assignment, actual worker
receipt, the full physical final-reader graph or public native BRS.

| Source / scope | Recorded result | Boundary |
| --- | --- | --- |
| PR133 original-owner pre-arm capture | Matching macOS/Linux inventories: 544 cases each passed; independent product/raw/source/import review passed | No arm, dequeue or ACK. Full CI/main integration pending. |
| PR134 SQLite scratch-path fixture race fix | 10 focused cases passed | Fixture-only scope; full CI/main integration pending. |
| Current staged-ACK prerequisites | New lock/ACK/state/URI component cases and connected pre-arm lock-replacement cases are implemented; final frozen evidence is pending | Do not combine earlier-source counts into this acceptance or claim a complete ACK service. |

Development component scope:

```bash
PYTHONPATH=src:tests python -m pytest -q \
  tests/test_rsi_brs_rejection_ready_locks.py \
  tests/test_rsi_brs_rejection_ready_ack.py \
  tests/test_rsi_brs_rejection_ready_state.py \
  tests/test_rsi_brs_rejection_ready_ledger.py \
  tests/test_rsi_brs_rejection_ready_policy.py
ruff check src tests tools
python -m compileall -q src tests tools
git diff --check
```

Freeze the complete source before genuine owner tests, then include
`test_rsi_brs_rejection_ready_owner.py`, existing reference/sync/channel readers,
original admission/handoff and original provenance-policy regression inventory.
Collect the exact ordered node IDs from that frozen checkout; independent groups
must form the same complete disjoint union on both platforms. Each installed editable
environment must import its own frozen checkout, preserve source before/after and
record collection/pytest/static exits and zero-failure/error/skip JUnit. Component
tests must not be presented as genuine original-owner or actual worker ACK evidence.

Required current assertions:

- Original controller observation/ledger guard/optional control RLocks and namespaces
  are retained before callbacks. Replacing any one during genuine pre-arm validation
  refuses, poisons and retains the old capsule. Pure capture/assert do not acquire a
  lock or wait for another thread holding it, and confer no controller lease.
- ACKs are detached exact DTOs over four plain strings. Alias/code/default/closure/
  metadata/dataclass/slot/regex/runtime mutations refuse before foreign callbacks;
  changed Python error initializers are bypassed by the refusal allocation path.
- Passive state readers retain the natural original queued pending/ready/container
  identities after fixture-only transitions. They reject reconstructed pending/ACK/
  field tuples and never clear retained evidence. These fixture assignments do not
  test production transition order, permanent ACK retention or actual receipt.
- Stateless URI encoding preserves strict UTF-8, the existing 4096-codepoint bound,
  slash and unreserved ASCII, encodes reserved/Unicode bytes, and rejects foreign
  path subclasses before operations. Real special-character SQLite files remain
  read-only before `query_only`; poisoning the old quoter cache has no effect.
- The outer policy holds all new exported closures and declared state local readers;
  pre-arm checks observe the ACK graph and original lock capsule without publishing
  anything. Existing six-table/schema/capacity, P/inode, budget/claim/result/publication
  and old empty-channel refusals remain intact.

Successor P0 acceptance must additionally cover the exact-owner one-shot service,
staged transport and last-gate ACK visibility, worker callback-to-constructor re-entry
guard, finite physical/deadline tail and pre/postassignment failure retention. Public
native BRS, `production_admission` and `online_publication` remain closed. Only local
inert/provider-free fixtures are permitted; no real solver, WebAgent or remote evaluator.

## PB-03a checkpoint delta/readback extraction

Final product/test source `3c0d74e7f97c7e98a8f4e68bcc439275e272dd8f`, tree
`3830617dc27fc1bbbfe3149f09fd21a35a3568a9`, passes 17 distinct inert cases in
two disjoint groups (15 and 2), with zero failures, errors or skips. The 15 new
cases cover bounded one-field deltas, exact canonical readback, original DRS CAS,
competing writes, post-write missing/wrong evidence, post-readback context/root
failure, stale/poisoned state, and live helper rebinding before any helper/CAS effect.
The two original compatibility cases execute successful publication plus read-only
inspection, and the original rejected C1/provenance-P/C2 sequence, respectively.

Seven collection/install/test/static exits are zero. The editable environment points
to its own checkout; 2,030 tracked files are unchanged before/after and match immutable
Git blobs. Full-scope Ruff, compileall and diff-check pass. Raw inventory, XML, source
maps, exits and result are retained under ignored reports
`pb03-kernel-and-final872-independent-20261015/final-17/`; the stdlib raw review passes
6,159 assertions. Separate root/code review checks original operation order and the
explicit live-helper fingerprint dependencies. These local results do not replace
final-source CI or complete the online BRS publication bridge.

The first 13-case development run retained 6 passes and 7 setup failures caused by
deep temporary paths exceeding the existing 32 KiB binding limit. A subsequent short
workspace 13-case run passed; both remain evidence of their original source. The later
live-helper fingerprint fix has its own final 17-case validation above. Neither earlier
run is added to the final count. Source/policy hashes intentionally change with this
extraction, and persisted runs retain their existing drift refusal without migration.
No BRS mutation gate, wire schema, capacity or production admission is widened.

## Earlier handoff validation

BRS-2a now has a pure detached handoff value and gate. It has no controller, ledger,
workspace, channel, CAS, worker dispatch or native BRS integration. The local focused
checks cover H01 identity serialization, H02 fixed worker count, H04 channel-level
selected ready/ack, H06 owner/head/source/policy drift, H07 nonce/replay/selection gates,
and H08 selected-channel close/error wakeups. The remaining matrix is for controller
integration. Tests must use local fixtures; no network, process campaign, WebAgent,
remote evaluator or company platform is allowed.

| ID | Scenario | Required assertion |
| --- | --- | --- |
| H01 | Fresh handoff shape | **Pure helper covered:** exact run/wave/episode/ordinal, M0, request, owner, head, source and policy pins serialize canonically; mutable subclasses are refused. |
| H02 | Policy and worker count | **Pure helper covered:** `max_workers=1`; existing child preflight requires BRS mode. Controller mode upgrade and pre-I/O integration gate remain open. |
| H03 | Owner lock boundary | Worker and nested callback never acquire the controller, lineage or checkpoint owner; owner-only CAS remains the sole mutation path. |
| H04 | Ready/ack meaning | **Channel helper covered:** ready/ack is bound to the single selected episode and exact ready digest. Durable pin-only semantics and non-escalation remain controller integration tests. |
| H05 | Queue while ordinal waits | Owner services a queued ready request while an earlier future runs without holding a wait lock; no deadlock at `max_workers=1`. |
| H06 | Head/state drift | **Pure helper covered:** changed head, state, controller, ledger, workspace, sidecar, owner thread, source, policy or execution-control fingerprint refuses. Durable evidence preservation remains an integration test. |
| H07 | Duplicate/foreign request | **Pure helper covered:** consumed nonce, wrong wave/ordinal and owner-thread drift refuse. Channel replay, sibling/nested/recovered requests and admission-reference uniqueness remain integration tests. |
| H08 | Ack failure / owner exit | **Channel helper covered:** selected-channel close and handler error wake waiters. Durable pin retention, owner exit ordering and no repair remain controller integration tests. |
| H09 | Deadline/cancel/unknown | Deadline, cancellation and unknown close the selected handoff, preserve budgets/evidence and do not auto-retry or dispatch a sibling. |
| H10 | Serial head continuity | After a completed or rejected child, the next ordinal gets a fresh handoff against the new head while all requests remain bound to M0 and the original reservation. |
| H11 | Partial-wave resume | Completed child references remain in the wave scope; only the missing selected ordinal may receive a fresh handoff; terminal resume is read-only. |
| H12 | Mixed publication | Success/rejection follows existing v2 owner CAS and C1/P/C2 rules; worker cannot publish or promote memory and rejected result never advances memory. |

Focused commands for this slice:

```bash
PYTHONPATH=src pytest -q \
  tests/test_rsi_python_brs_child_policy.py \
  tests/test_rsi_python_brs_handoff.py
ruff check src/lunar_evolution tests/test_rsi_python_brs_*.py
python -m compileall -q src tests
git diff --check
```

The channel atomically consumes the nonce under its in-memory condition lock and gates
ready messages to the selected episode. It does not verify that its caller holds the
controller mutation lock; future controller integration must call it inside the exact
owner scope. Channel completion checks acknowledged, non-cancelled, error-free request
state; it cannot observe the executor future. The caller must observe that future's
successful terminal outcome before invoking completion. The helper alone does not
provide native BRS dispatch or production admission.

The final acceptance must additionally compare complete source inventories before and
after, canonical tree and parent commits, all raw JUnit files and every durable
workspace/ledger/inode pin. A focused fixture pass cannot claim native runtime,
external worker authenticity, distributed ownership or production admission.

## Private selected owner-service slice

The controller now has a private, provider-free selected-service seam. It binds one
selected child from a complete BRS wave, checks original planned budget/deadline and
request budget before executor creation, runs source/configuration fingerprint hooks
outside the short observation lock, then rechecks strict handoff identity and owner
CAS pins inside that lock. The worker returns only a validated `EpisodeExecution`;
episode/request/result/verifier DTO types and verifier-to-episode consistency are
checked before durable result comparison. Channel ACKs are detached from caller
objects and completion verifies the retained owner fields.

The focused tests are split so their exact counters remain auditable:

| Scope | Cases | Result |
| --- | ---: | --- |
| Existing BRS admission/owner/publication | 104 | provider-free pass |
| Detached ACK channel | 13 | provider-free pass |
| Detached handoff contract | 30 | provider-free pass |
| Selected owner service and drift/lock/result gates | 28 | provider-free pass |

The public `_drive_brs` entrance remains refusal-only and no native producer,
sealed runtime, external worker, remote evaluator or production admission is enabled.
The 175 local cases are focused seam evidence, not native BRS acceptance.

## Private selected execution checkpoint settlement: validation scope

BRS-2c adds a separate owner checkpoint boundary after the existing worker/result
and channel completion boundary. Its new focused matrix must use the real selected
service, original ready/ACK, durable episode/result, `_save_flow` CAS and readback
on its successful path. Fault injection is reserved for refusal and interrupted
write/readback paths; it cannot manufacture a successful owner grant.

Required checks include original selected result persistence, owner thread and lock,
foreign/changed return values, duplicate settlement, retained ACK/result/source/M0/
budget drift, stale head, CAS and full readback failure. No sibling may launch or
acquire a refreshed request/reservation. A durable write followed by uncertain
readback remains retained with a stale owner head and no automatic retry. Existing
service, ACK, handoff, admission and public native-refusal tests remain regression
obligations. Final counters and source identity will be recorded after execution;
this plan alone does not complete a test or runtime acceptance.


### Settlement source-specific execution record

All runs below use only installed local provider-free/inert fixtures. Original
failures and interrupted attempts remain retained in separate ignored reports.
Counters across different source hashes are not added into one acceptance claim.

| Source / scope | Observed result | Boundary |
| --- | --- | --- |
| First 34-case attempt, 300s runner limit | partial; no complete final XML | Not acceptance or a proven product failure. |
| `132e530` controller / `7983f4d` tests, six groups | 272 distinct: 269 pass, 3 failures, zero errors/skips | Two invalid `None -= 1` budget faults and one expected-code mismatch with the existing checkpoint conflict gate; original XML/source/exit evidence is retained. |
| `eb01d461` controller / `ea478ae` tests, six groups | 274 distinct: 274 pass, zero failures/errors/skips | Real CAS/readback, post-save original owner/state identity, valid budget drift and exact conflict contract. Independent source/install/exit and inventory/JUnit disjoint-union audit passed. |
| Final callback hardening quick scope | 32 pass, zero failures/errors/skips | Exact DTO attribute dictionaries/keys, colliding keys, metaclass type callbacks, flow payload and wave-state rejection; callbacks remain zero. This is a parser/refusal gate, not worker execution acceptance. |
| Final integrated hardening scope | **360 pass; zero failures/errors/skips** | 85 settlement (53 service/CAS + 32 quick refusal), 221 existing BRS, 54 existing admission-flow. Eight exact node-hash groups; installed origins, source freeze, all exits and raw XML/inventory disjoint union independently audited. |

The final code SHA256 is
`5f2d932b21738b7d612da23292c6de2c8df0c52d655d21174b4364af1235da10`;
the final settlement test SHA256 is
`00229c85c1a277c4647454a3f7fe18c9f10f507076cea06c5a25543882c7171d`.
The earlier 274 inventory SHA256 is
`bdf14d90dbbe3ad7e166f068067b851b77bddf4b6cce0c81e18707cb88a5fc98`.
Its raw XML/source/exit receipts are under `final-six-jxxylqq_`; they do not certify
the later callback hardening. The original failed 272 run is `final-six-3mhbexg1`.

The workflow adds a separate 85-case no-skip settlement gate on Python 3.11/3.12/3.13;
the complete current suite still discovers the same module independently. A local
focused pass will close only this private checkpoint sub-slice, not public native
BRS, ordinal/publication recovery, real runtime/producer/CLI or production admission.
Final-source CI and independent raw/source/tree review remain separate obligations.


Final integrated run: `final-eight-1rb__9zs`, group counts
`45/42/42/50/42/44/49/46`, longest group 244.25 seconds. Dynamic inventory SHA256
`c84aa8e73886640ad9784e35b534d35bc85e427ad83d15f5aa92bf45fc0f1943`;
runner result SHA256 `f78b87803ee6e28bd453ed789cf7ebcb3d71e415e1d55e4c873be4449624eebe`.
Ruff over `src tests tools`, compileall and diff-check passed. Both the test owner's
stdlib audit and a separately written root auditor checked actual raw XML, all eight
exit records, exact disjoint inventory, original/actual source hashes, installed
editable import receipts and static argv/cwd/logs. Root audit SHA256
`81eae45be2ee940124c06d8f405796176a4ef1ca1a333c409c8852850340b6f0`.
The root auditor does not import or execute the product. Raw evidence is retained
on the server and copied into ignored local reports. Only documentation acceptance
status was updated after the final freeze; controller, tests and workflow remained
byte-identical to the accepted focused source. CI/integration remains pending.


## Original-owner staged ACK development and frozen validation — 2026-10-18

The internal dedicated service is now connected to the original owner, channel and
read-only controller root. Development validation includes the first genuine
one-candidate original-worker ACK/receipt on `6422073` (one pass, 54.33 seconds),
98 final-reader component cases and 105 worker/legacy cases. These development
runs have different scopes and are not accumulated into frozen acceptance.

The first snapshot smoke on `fd279a0` failed on an incorrect `before-v2.json`
filename; retain that raw failure separately. The successor reads the original
`before.json` pin, obtains P from confirmed C2 when C1 contains a null provenance
entry, and preserves absence of optional original native sidecars. It also holds
MRO declarations, namespace key domains and exact primitive types before any
possible callback; no capture is refreshed after failure.

The new frozen validation must run one ordered, disjoint inventory on macOS and
Linux, using each runtime's own editable installation and unchanged tracked
source. It includes all preceding 868-case prerequisites plus the service,
worker and final-reader files. The service inventory includes one/two-candidate
actual receipt, permanent timeout, early natural ready refusal, an inflight
callback failure and notification uncertainty that preserves the full ACK.
Fixture-only partial-prefix tests do not imply worker nonreceipt. The original
record, captures, raw rows, budgets, publication and execution state remain held.

Acceptance additionally requires independent product, raw/XML/order, source and
import review. Local scoped success does not replace the complete 33-job CI or
main integration. Public dispatch/admission and online publication stay closed;
rejection dispatch/result/recovery/root/retirement/serial and P1 runtime/solver/
production CLI remain successors.
