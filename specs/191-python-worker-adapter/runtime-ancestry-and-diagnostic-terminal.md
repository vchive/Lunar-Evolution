# Runtime ancestry scans and truthful diagnostic termination

Status: implementation, focused regression and static checks complete; see
`../../docs/parallel-batch-validation-20261027.md` for original failures and
latest-node coverage. Actual final-source Linux/CI acceptance remains pending.
This does not close P0.

## What the retained failure establishes

PR189 head `2486a6dc08457b360fdd7bc5f0e6fdb14966e52f` failed its original
600-second Linux mixed case in CI40457518133. The matrix had 29 successful
execution jobs and one failed Python3.11 current-3 `three-child-mixed` job:
`solve_wall_timeout`, 600.142613669 seconds. Its attached
`rsi_native_gateway_attempt_unknown` receipt records uncertain attempt outcome;
it does not establish another independent failure or a timeout mechanism.
The three focused gates refused the failed matrix correctly. The separate
same-head 5090gpu attempt also timed out at its original limit, retained raw
return code -15 and no JUnit. Neither attempt is retried here.

The retained own-process stack window is only 167 contiguous samples, indexes
0–166, through 85.771766643 seconds. Its stop record at 86.279290736 seconds
says `sample_limit`, although its declared bounds were 361 samples/180 seconds.
The outer diagnostic subsequently timed out at 180.031620365 seconds. The old
sampler initialized `sample_limit` before entering its loop and did not catch
all exceptions. Consequently its early stop reason is unsupported. No retained
exception identifies the specific stopping trigger. The missing later window
must not be described as idle, blocked, deadlocked or sampled through 180s.

Within that valid early window, the main thread moves through JSON encoding,
owner/control validation, checkpoint history, SQL evidence and runtime/source
pins; the worker often waits for the publication mailbox. First-frame counts
are observations, not time or CPU attribution. Their call chain is:

1. Publication mailbox `service` dispatches to the original BRS native owner bridge.
2. Native publication observes original owner checks and fresh recovery, then
   prepares the admitted transaction.
3. Persisted lineage policy checks read controller/checkpoint history and recheck
   bindings/runtime evidence at the required transaction boundaries.

These boundaries deliberately require fresh state. This slice removes no owner
check, source read, SQL SELECT/decode, filesystem observation, receipt or callback.
Historical thread-group CPU windows support investigating compute cost; they do
not attribute all descendant work or explain the full current-head 600 seconds.

## Supported ancestry candidate

The historical macOS whole-case profile at head `1e6` recorded 9,789 graph
validation calls, 411,138 direct `Path.is_relative_to` calls and 117,468 direct
`Path.relative_to` calls from that validator. Their raw cumulative edge values
were 6.588890264 and 1.108878284 seconds respectively. Threaded caller timers
overlap; these are a repeated-work lead, not predicted wall savings or current
Linux root cause. The old absolute ancestry loop's AST is identical in that
archive, PR189 head2486 and pre-change head869198bc:

`9f3d71e360b06d6ad9353ad7dc88fa1dcec0024f8c1407f7fb3c750edd9a0cb4`

The graph still checks root binding first, constructs the original local
`Path(root.path)` once per root and constructs `Path(original_directory.path)`
once per pin. Only after that pin's original PathLike callback does it read fresh
text from both local Path objects. For ordinary canonical absolute POSIX Paths,
equality projects to `.`, while a slash-boundary prefix projects a descendant's
relative path. `/a` does not contain `/ab`; `/` contains every other absolute
single-anchor path. Relative paths, double anchors and `..` components retain
the original `is_relative_to`/`relative_to` fallback. Path normalization still
occurs through the original constructors before this computation.

The original pin order, observed-membership lookup, fresh device/inode/mode reads,
exact refusal codes and final digest check remain. No decision or DTO field is
cached across pins or subsequent callbacks. As with the previous lexical-path
slices, this contract uses the ordinary Path backend and does not promise extra
callbacks on a caller-replaced implementation or consistent behavior for
privately corrupted Path internals. Public DTO gates and their callback behavior
are unchanged.

This candidate addresses a supported repeated operation. It has not established
that the combined source completes the original Linux timeout case. The broader
fresh JSON/history/runtime-pin costs remain unresolved, and no unsafe shared
JSON decode or one-shot encoding optimization is introduced.

## Diagnostic successor contract

`tools/python_own_stack_diagnostic.py` is an API-only development collector. It
does not import product modules, run pytest, launch a case, request a model,
invoke an evaluator or inspect another PID. It preserves the ignored historical
diagnostic and its bytes. Its protocol is
`lunar-own-python-stack-diagnostic-v2`.

The explicit caller provides canonical source/stdlib roots, an allowlist of at
most 4,096 relative Python filenames and a create-only output path. No roots,
argv/env, locals/globals, source-line text, raw thread IDs, thread names,
unapproved filenames or raw exception content are emitted. Output contains only
allowlisted relative filenames, approved bounded function names, line numbers,
numeric counters and fixed classifications/reasons. The leaf uses
`O_EXCL|O_NOFOLLOW`, mode0600 and no overwrite/removal of partial evidence.

Bounds are 180 seconds, 0.25/0.5-second intervals, at most721 samples,32 selected
threads/sample,64 stack frames/thread,128 emitted frames/sample and64 lifetime
thread slots. Records are at most128KiB and total output at most8MiB, with1KiB
reserved for a terminal record. These are cooperative bounds; an unreturned
operation still requires the caller's outer deadline. Delayed execution never
causes a catch-up sampling burst.

`sample_limit` is assigned only by the loop's actual exhaustion branch. Main
completion, duration, record/total-byte caps, observation/write/wait errors and
interruption have distinct fixed reasons. TypeError/AttributeError and other
previously uncaught regular exceptions are caught without retained messages.
Stop records distinguish successfully observed samples from completely written
and fsynced samples. Partial writes increment the actual byte counter, retain
their bytes and leave terminal status unknown; no JSON stop record is falsely
appended to an incomplete line. A failed terminal write is also unknown.

`finish()` requests cooperative stop and joins for0.5 seconds. If the writer is
still alive, it returns `writer_running=true`, `terminal_status=unknown` and
does not close that writer's fd. Constructor/start failures close their owned fd
and preserve any created partial output. This truthful successor cannot repair
or identify the old early-stop trigger retroactively.

## Validation and remaining work

- [x] Implement only the absolute ancestry/projection computation.
- [x] Add frozen original-AST differential, canonical/fallback, callback-order,
      fresh-identity and real-tree digest/binding tests in a separate module.
- [x] Add API-only collector and synthetic fake-frame/clock/thread tests for
      terminal distinctions, privacy, bounds, descriptor cleanup and create-only
      evidence. No live stack sampling occurs in these tests.
- [x] Perform AST-only syntax/structure self-checks without product imports,
      cases, benchmarks, tests or model requests.
- [x] Integrating agent runs focused tests, Ruff, compileall and diff checks
      against the frozen combined source.
- [ ] Independent source review and one centrally planned final-source regression
      establish whether P0 is resolved. Original600-second budgets remain intact.

The retained original diagnostic wrapper SHA256 is
`09692b2bbefa0e7d295d1a70d3f739d7368e857a9e619361f341b7be9d75c18a`;
the167-sample JSONL SHA256 is
`64c5cf7f32b24236fadc7d2273ac4c22c5eb3c08db08a00adbce29738328ec70`.
The historical whole-case pstats SHA256 is
`17da44993da76e54664b94f7706da271801db58f880cdf49d4d2d4adb0814c80`.
They are provenance, not new acceptance. CI/P0/merge/runtime/publication flags
remain false until their respective actual gates pass.
