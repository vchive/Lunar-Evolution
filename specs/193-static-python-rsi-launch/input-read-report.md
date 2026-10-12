# Fixed two-grant input-read report prototype

Status: bounded F04 source/mock continuation implemented and locally verified,
2026-10-12; final-source CI/audit remains pending.
This is a prototype and pure comparison seam, not an accepted installation or live
scheduler/publication integration. Existing source emitter/profile/pins are frozen.

## Contract and scope

The child is granted only `../.rsi-input/request.json` and
`../.rsi-input/memory.json`; it cannot read the manifest or launch record. Its finite
module closure lacks json/hashlib/base64. Add a separate source asset exposing
`read_input_report(manifest_sha256)` which validates exact built-in lowercase SHA256
syntax, opens only the two fixed paths in binary read mode, reads at most128KiB+1
from each, and refuses empty/oversized/non-exact byte results before producing any
report. Both files must complete before reporting the fixed Python computation285.
The source imports no module and accepts no path, environment or program selector.
The return value is canonical ASCII JSON bytes with exactly schema, manifest_sha256,
request_hex, memory_hex, computed and claims. Encoding uses builtin bytes.hex and
fixed fields only; no filesystem write, stdout/broker effect, task parsing or model
call is introduced. The report contains raw request/memory bytes and remains an
in-process value; it must not be logged or retained in completion evidence.

The report schema is `lunar-static-python-rsi-input-read-report-v1`. Five claims are
always false: input_authority_verified, runtime_execution_verified,
solver_result_accepted, memory_use_verified and production_admission. Reporting
bytes and computation is not independent manifest/file/launch authority or proof
of memory usefulness. All old launcher/encoder/sourceplan/overlay assets remain
unchanged; this prototype is not included in any accepted frozen/build inventory.

## Pure comparison

Add `compare_input_read_report(raw: bytes, *, expected_manifest_sha256: str,
expected_request: bytes, expected_memory: bytes) -> InputReadReportMatch` under
tools/static_python_rsi_fixture. The caller supplies its own independent marker and
original input bytes. Validate exact built-ins and bounds before parsing/hashing;
report maximum is4*128KiB+4096. Require exact schema/fields/five false claims,
computed exact int285, lowercase/even bounded nonempty hex, no duplicate keys,
nonfinite numbers or noncanonical encoding, and exact decoded input-byte matches.
Malformed/deep JSON and unsafe caller types use fixed
`static_python_rsi_input_report_*` errors without callbacks. Output is an immutable
DTO containing only marker, report/request/memory digests and input sizes; it has
no accepted result, eligibility or authority flag. The comparator performs no I/O,
process/environment/network/clock effects, and neither reads a descriptor nor
promotes a caller-created DTO into trusted evidence.

## Verification and later connection

Tests execute the actual prototype source with a fixed mock open map or local inert
files only. Require exact path/mode/read limits and no third read or effect. Cover
invalid metadata refusal before open, each failed/empty/oversized/nonbytes read,
maximal input/report sizes, exact two input differences, malicious claims/schema,
strict types/bounds, duplicate/deep/noncanonical JSON and deterministic immutable
comparison. Focused tests, compatibility against the existing113+82 preparation
modules, Ruff, compileall and diff checks are required; independent Python replay
must use frozen hashes. Full final-source CI/audit remains required before merge.

Live F04 stays open. Parent `validate_native_rsi_launch_inputs` and held-grant
revalidation remain the authority for marker-to-manifest/file/intent binding.
Current stdout capture retains only hash/count; this prototype returns bytes and
cannot pass as a retained runtime observation or producer envelope. Later live
composition must bind original bounded capture/materialization, request, report,
candidate and envelope within the same original attempt/deadline before terminal
capture, then use existing runtime/owner gates, exact evaluator and publication.
No post-hoc producer output or score may stand in for that evidence. No real
CPython build/runtime, external solver, WebAgent or remote evaluator is run.
