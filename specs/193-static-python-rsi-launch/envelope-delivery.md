# Explicit original generic-envelope delivery successor

## Problem and boundary

The frozen `fixed-producer-lifecycle-v1` target commits candidate and producer
wrapper/database artifacts, but never creates `output/producer-result.json`.
The native capture requires that generic envelope before an original completion
can be acquired. Supplying an envelope through an inert fixture tests the host
join, but cannot establish that the actual target delivered it.

This bounded successor closes that software gap. It remains explicitly selected
and default-off. It generates a candidate proposal; it never executes/evaluates
the candidate, adds a model request, grants runtime/build/admission authority,
opens a provider connection, or substitutes for an accepted isolated build.
Existing v1 source, pins, control semantics and default behavior remain frozen.
Pycache capability coverage and independently surviving guardian custody remain
separate work; this successor cannot clear their missing-evidence boundaries.

## Original input delivery

The profile is `fixed-producer-lifecycle-v2`. Its precise argv is:

```text
executable --lunar-fixed-producer-envelope-v1 RUN_ID PRODUCER_FINGERPRINT --lunar-rsi-input-v1 MANIFEST_SHA256
```

The run identifier has exactly the existing intent identifier syntax
`[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`. Both digests are exactly 64 lowercase hex
characters. The final existing RSI marker pair is unchanged, so the original
input protocol and its two read-only file grants need no extension. No ambient
environment value, extra manifest file or new read grant supplies these fields.

The host must compare argv against the same original intent's `run_id` and
`producer_fingerprint` before consuming/releasing the attempt, and must
independently compare request solver against the original producer. Complete
argv bytes are bound by the original intent digest, attestation and original
native bootstrap control. A target's own matching strings are not authority.
The launch binding file is not exposed as a new target capability. Episode ID
does not substitute for run ID, and the descriptor cannot contain its own intent
digest because that would make the argv/intent digest construction circular.

The new pinned C launcher accepts exactly six argv elements, validates their
syntax, performs the unchanged original startup capture, closes FD 198, and
only then calls the frozen dispatch with:

```python
_rsi_launch(manifest_sha256, deadline_monotonic_ns, run_id, producer_fingerprint)
```

FD 197 remains borrowed by Python and solely closed by the C launcher. Existing
bootstrap v4 already delivers these argv and private writers; no new control
version or descriptor is necessary. The original absolute deadline is unchanged.

## Actual target output and ordering

The new frozen `_lunar_envelope_main` follows this order:

1. Check the fixed launch fields and original deadline; emit `begun`.
2. Read original request/memory, construct the fixed body, perform sole `req-1`,
   validate its successful reply and compute the constrained candidate proposal.
3. Commit and read back the same two producer artifacts: OpenEvolve
   `candidate.py`/`result.json`, or Shinka `gen_0/main.py`/`programs.sqlite`.
4. Generate the generic envelope from that actual candidate and original input.
   Create `output/producer-result.json` exclusively with no-follow semantics and
   mode 0400; write, fsync, read back and verify stable file identity/bytes.
5. Fsync the output directory, recheck the same deadline, and emit `committed`.

Failure at any step prevents a committed record. Existing files/symlinks are
refused. Partial files after a failed original attempt confer no success and are
not repaired through a host-written fallback.

The canonical envelope uses schema `1`, the fixed solver as `producer_id`, the
bound run/fingerprint, status `completed`, the original request contract,
`budget={"requests":1}`, and exactly one `candidate_source` material. Its path is
the actual candidate path and its digest/size are computed from actual proposed
bytes. Lineage is empty. Producer wrappers/databases remain auxiliary artifacts.

Top-level and OpenEvolve material evidence are the exact empty summary:

```json
{"present":false,"score_present":false,"payload_sha256":null}
```

Shinka material evidence is the normalized summary of canonical
`{"correct":false,"generation":0,"program_id":"proposal"}`: present is true,
score_present is false, payload_sha256 hashes those canonical bytes. This agrees
with the existing material semantics and never claims a verified score.

## Completion wire and original join

Protocol `lunar-fixed-producer-completion-v2` retains two canonical ASCII JSON
lines (`begun` sequence 0, `committed` sequence 1), a 16 KiB total bound and the
existing strict PID/manifest/solver/original-deadline fields. The committed
record retains request/memory/broker and exactly two producer artifacts, adding
only:

```json
{"envelope":{"path":"producer-result.json","size":123,"sha256":"..."}}
```

Size/digest are actual generated envelope-byte facts, never independently
accepted assertions. The host must compare them to the exact original captured
envelope bytes, retain that original acquisition, join the original reader,
broker, candidate/artifact semantics, PID and sealed image, and recheck freshness
and deadline before acquiring completion. The generic envelope still undergoes
the original strict native capture/parser/budget checks. A reconstructed DTO or
same-value public copy cannot replace any original retained object.

The new pure comparer returns the existing comparison type with every authority
flag false. A strict internal projection reuses legacy material comparisons;
the legacy parser itself remains unchanged and refuses v2 shape/protocol. The
v2 parser likewise refuses v1. No extra broker request or deadline renewal is
allowed.

## Implementation and validation

New assets and `static_python_producer_envelope_source.py` independently pin the
new producer fragment, C launcher and composed producer bytes. Pure composition
preserves the original upstream fixed entrypoints and expanded startup tail;
only explicit dispatch changes. `tools/static_python_rsi_fixture/envelope_source.py`
reads the independently pinned sources for explicit build selection.

`static_python_producer_envelope_completion.py` owns the bounded pure wire join.
The host must include its callable, borrowed strict wire helpers and new argv
builder/validator in its implementation pin, alongside existing source/runtime
identity checks. Recipe/runtime integration is a separate explicit branch,
never metadata-only reauthentication of an existing image.

Compiler-dependency, compiler/linker-dependency, standalone-linker and explicit
Zig-support recipe APIs accept the same optional `producer_lifecycle_profile`
and forward a supplied value unchanged to the original concrete recipe gate.
They cannot infer or upgrade a profile from source bytes, a bundle or an image.
Omitted and explicit `None` preserve the original lower-level call shape and
recipe/source/manifest bytes. Their existing base recipe and manifest digests
bind the selected source composition; no successor manifest authority field or
consumer fallback is added. The original dependency consumer still validates
the actual generated command graph and capture plan under its original budget.

Focused target tests use actual local input/output files and a real pipe while
substituting inert upstream diff helpers and broker responses. They cover both
solvers, canonical material summaries, a run ID distinct from episode ID,
single request, exact output ordering, create-only/symlink refusal, fsync/readback
and partial-write failures, launch-field validation, source pins and wrapper
forwarding. Pure tests cover mismatched envelope bytes, path/shape/type/size
errors, copied wire properties, argv mismatch, cross-version refusal and legacy
compatibility. These are local software tests, not an isolated runtime/model or
kernel acceptance result. Consolidated regression is owned by the parent batch;
no separate per-agent pytest campaign is run.
