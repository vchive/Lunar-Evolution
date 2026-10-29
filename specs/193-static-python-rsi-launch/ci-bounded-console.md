# Bounded CI console with complete retained inventories

Status: implemented and affected software regression passed, 2026-10-29.
Baseline: `1ed86fe9`. Complete CI remains open.

## Observed problem

One diagnostic-only local collection of the unchanged source completed with
26,371 unique nodes in 14.404222 seconds including its wrapper. The collected
inventory serializes to 23,643,038 bytes before the rest of the version record;
the longest parameterized node is 9,450,814 bytes. Twenty-one node IDs exceed
64 KiB. Oversized-input tests use actual byte/string parameters as automatic
pytest IDs. Their data and identities are valid; echoing all of them in a single
console line is unnecessary for the original report gate.

Live GitHub UI observations for Python 3.11 current-1 and heavy-5 show both
collections completing, followed by no visible version or pytest-start marker
after about thirty minutes. The original log download endpoint still returns
BlobNotFound. These observations narrow the interval, but do not prove whether
Git identity reads, serialization, console output, or a hosted-runner fault
caused the stall. Preserve the original run and its unsuccessful/unknown status.

## Contract

Under `--diagnostics`, print a shallow console projection without `full_nodes`
and `selected_nodes`. Preserve counts, inventory digests and original remaining
fields. Write the complete unmodified result to the same create-only summary
file. Add checkout-identity phase boundaries. The default runner output and
test arguments remain unchanged. No node IDs, data, selection, file ordering,
JUnit case keys, budgets, retries or admission rules change.

Replace regression-step `tee` with a binary streaming console tool. It writes
every input byte to the original create-only `pytest.log`. For each physical LF
line, console output retains at most 4096 payload bytes; CR does not reset this
limit. An overflow receives a separate finite marker containing the full line's
byte count and SHA256, excluding its terminal LF. A final unterminated line is
hashed without inventing raw-log bytes. The raw log is never decoded or
re-encoded; a console prefix may end inside a UTF-8 character. The truncation
marker appears only on console. Use finite reads and rolling hashes, never a
whole-line buffer. Normal short output is preserved exactly.

For each finite input chunk, complete its raw-log writes and flush the retained
Python buffer before writing any console bytes for that chunk. If the raw flush
fails, refuse display of that chunk. This ordering makes the raw bytes visible
through an independent file descriptor before display; it does not perform
`fsync` or establish crash durability. The ordering correction does not identify
the cause of any historical CI failure.

Keep `set -o pipefail`. Input, raw-file and console failures must return nonzero;
the logger does not turn runner failure into success or manage child processes.
Each role keeps its original four artifact files. The aggregate still reads the
complete inventories from summary, recomputes their partitions and validates
the original XML; the console is never gate evidence. This limits individual
lines, not total output, collection memory or disconnected-runner behavior.

## Validation

Validate opt-in versus default output, complete unchanged sidecar data and
create-only refusal. Exercise byte chunk boundaries, exact limits, CR, EOF,
Unicode bytes, multiple lines and I/O failures. One natural inert pipeline must
prove large output is fully drained and retained while console lines stay
bounded. Use a real buffered raw file and an independent read descriptor to
verify flush-before-display visibility, and require no chunk display when its
raw flush fails. Replay the already-collected diagnostic log as data to verify its
actual oversized IDs without executing tests again. Run affected runner,
diagnostics, streaming-tool and aggregate tests together in the existing Git
workspace, plus Ruff, compileall and diff checks. Do not replay consumed mixed
acceptance HEADs. Fresh complete CI remains required before main integration.

## Verification

Frozen tree `1e82a1fb2c60399d3f07efec728a059a294d76ac`: six complete files,
423/423 pass in 29.350027 seconds on Darwin, zero failure/error/skip and zero
retry. All 2736 tracked file bytes and Git modes stayed unchanged. Thirty new
cases include original sidecar/identity/error behavior, finite streaming, raw
retention and actual bash pipefail propagation. Manifest remains 83 groups/65
zero-skip groups, expected sum 7330. Ruff, compileall and diff checks passed.

The existing collection log was replayed as inert input bytes only: all
23,440,837 bytes retained exactly (SHA256
`dd11254b0172634e571009f2aab2387265bae33ce63747f1cad40f0de6aeae54`),
console 3,388,286 bytes, maximum line 4096 bytes. Each of 46 omission markers
matched its original full-line length and digest. No tests were re-executed by
this replay. Evidence is in primary ignored `validation/ci-followup-20261029/`.
Original unsuccessful/unknown CI stays preserved; only fresh CI can establish
whether the hosted-runner stall has cleared.


## Flush-order successor verification — 2026-10-30

Frozen `9f5dc6735c73ab4dcfc25993a98a403920d46403`: both complete console and
aggregate test files passed 105/105 under verified effective verbose reporting,
zero failure/error/skip, 1.625887 seconds on Darwin, one dispatch and zero retry.
All 2,738 tracked bytes/modes remained unchanged. The 263-node regression group
was collected only, with zero test body dispatches; its count includes the one
new buffered-file visibility test. Manifest remains 83 groups / 65 zero-skip,
expected sum 7331. Existing failure propagation coverage additionally requires
empty console output when the original raw flush fails.

Earlier 315/45/67 focused domains are retained without repetition. This is not
a single complete final-tree CI pass. The same cumulative PR must pass fresh
complete CI/source gates; original unsuccessful runs remain preserved.
