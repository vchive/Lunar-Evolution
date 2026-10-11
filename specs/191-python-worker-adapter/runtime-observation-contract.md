# Feature 191 — pinned runtime observation policy

Adopted bounded P0 contract, 2026-10-12. The shared pure comparison and its gate/adapter
call sites are implemented;303 focused and195 disjoint compatibility cases pass locally.
Independent Python3.13 focused replay and final source review pass; full three-version
CI and raw/source/tree audit remain required before merge. This
change repairs detached consistency checks. It does not implement runtime execution
or grant admission. Only inert local fixtures may be used for this slice.

## Concrete conflict

`producer_python_runtime._policy()` declares launcher `argv_flags=["-I","-S","-B"]`.
Those are launch policy tokens, not the observed representation of `sys.flags`.
`adapt_static_python_observation` faithfully projects Feature 189's actual named
flags to sorted `name=integer` strings. Both
`python_producer_admission_gate.verify_python_producer_admission_gate` and
`python_producer_adapter.build_python_producer_adapter_envelope` previously compared
that observation directly to the policy token tuple, so a valid emitted static
observation cannot pass either composition path. Synthetic admission fixtures
previously put the tokens in the observation and conceal this conflict.

Both functions also compare runtime `argv` and `orig_argv` to OS launch
`intent.argv`. Feature 189 intentionally fixes both PyConfig lists to
`["lunar-static-python-fixture"]`, with `parse_argv=0`, whereas the OS intent names
the executable path. These are distinct facts. Even conventional CPython gives
different meanings to `sys.argv` and `sys.orig_argv`.

## Three separate domains

1. The original OS launch intent owns the exact executable/path and OS argument
   vector. Its original attestation remains the only relevant launch identity.
2. Named runtime flags are observations emitted by the running Python process.
   They are not rewritten into command-line tokens and cannot be inferred merely
   from a declared launch policy.
3. Expected Python `argv`, `orig_argv`, flags, version/cache/ABI, encodings,
   `sys.path` and startup modules come from the independently pinned, reviewed
   installation initialization profile. The child's observation does not select
   its own expected profile.

The first repaired composition supports only the already reviewed finite Feature
189 static profile. A new general portable-tree policy or arbitrary Python entry
point is outside this slice. Feature 177's manifest policy wire, Feature 188's
frame, Feature 189's emitted observation and descriptor wire, and Feature 191's
binding/terminal/adapter-envelope/run/checkpoint/receipt wires stay unchanged.

## Independent installation pin: reuse the existing parser

The caller retains the original installation descriptor bytes and three original
pins independently of the child output and current filesystem:

```python
installation_descriptor: StaticPythonInstallationDescriptor
installation_descriptor_sha256: str
installation_version: str
initialization_profile_sha256: str
```

The existing production parser already has this contract:

```python
parse_static_python_installation_descriptor(
    raw,
    expected_descriptor_sha256=...,
    expected_installation_version=...,
    expected_artifact_sha256=...,
)
```

Use that parser from one shared runtime-policy comparison helper. Do not introduce
a new profile DTO or accept a detached parsed descriptor's self fields as its
independent expected pins. The helper takes existing binding and observation DTOs
plus the existing descriptor DTO and the original pins. The interpreter artifact
SHA comes from the separately retained original binding, never from the supplied
descriptor. The descriptor DTO's canonical bytes are reparsed with those pins, its
fields must equal that parsed result, and the original initialization-profile SHA
must match. The helper reparses existing canonical
wires after their exact-shape gates. It performs no filesystem read, launch,
clock sample, journal creation, budget consumption, or publication.

The gate, adapter build, and adapter verify receive those four inputs as explicit
keyword parameters and forward them unchanged to the common helper. Missing
parameters may default to `None` solely to yield fixed refusal codes for old
callers; no success path may use defaults, reconstruct pins, or infer a profile
from the observation. Adapter verify must forward the original pins when it
rebuilds the expected envelope. Parsing a historical envelope remains a pure wire
operation and does not require the external profile.

After parsing the existing descriptor, the shared helper joins its installation
artifact digest/size/mode to the
binding's already retained interpreter identity. Its fixed linux/x86_64/3.13.12,
cache-tag and ABI fields must agree with the original binding target and the
observed runtime. A descriptor for a different interpreter or target is rejected
even if it is internally valid and has matching caller-supplied descriptor pins.
Descriptor and pin equality prove only detached content consistency; they do not
prove actual ELF bytes, startup execution, private owner lifetime or code origin.

Expected Python argv and orig_argv are read independently from the descriptor's
`initialization_profile.config`; each is compared separately to its observation.
They are never compared to the OS vector. The declared launch-policy tokens are
checked only as the existing exact manifest policy; they are not used as the
observed flags representation. For this reviewed profile, the actual observation
must retain these canonical selected flags exactly:

```text
dev_mode=0
dont_write_bytecode=1
hash_randomization=0
ignore_environment=1
isolated=1
no_site=1
no_user_site=1
optimize=0
safe_path=1
utf8_mode=1
```

These named facts correspond to the exact preconfig/config already validated by
the existing installation parser. Comparison also uses the descriptor's empty
module search path, encoding/error settings and expected startup modules rather
than child-selected expectations. The helper rejects missing, extra, duplicate,
reordered, malformed, wrong-valued or argv-token-only flags. The observation DTO's
existing string-vector schema remains unchanged. `adapt_static_python_observation`
continues to preserve actual bool/int input types and produces its existing wire.

## Compatibility and effect boundary

Existing runtime-observation and adapter-envelope parsers may still inspect old
synthetic argv-token records if their existing v1 shapes are valid. A newly built
adapter or a successful composition gate cannot treat them as real named runtime
observations. There is no implicit migration and no fallback to comparing OS argv.

The gate still returns `production_admission=false`; `eligible` remains a detached
consistency projection. All other protection claims stay false. The helper does
not create postexecution evidence or replace any handoff/owner/broker/envelope
authority pin. The actual native receipt still lacks the Unix start/release/exit
observation and original executable inode needed for a completed Python terminal;
receipt projection must therefore remain `unknown`.

## Static RSI launch is a separate unresolved contract

Feature 189's current `launcher.c` accepts `argc==1` only. Native RSI input binding
requires original OS argv ending in `--lunar-rsi-input-v1` and the manifest digest.
These cannot be composed as currently specified. The frozen main currently emits
the fixed computation/broker observation only; it does not read RSI request or
memory files and does not produce a producer result envelope.

Do not relax the native RSI marker gate or fake matching runtime argv as part of
this observation repair. The existing native attempt already grants only the two
retained request/memory file paths read-only. A later accepted installation version
may consume those exact paths without adding inherited FDs or changing v2/frame
wires. If its OS launcher accepts fixed metadata, freeze precisely one marker and
manifest-digest pair in a new installation asset/profile version, preserve fixed
PyConfig argv, and reject arbitrary modules, paths, `-c`, `-m` and extra arguments.
That is a Feature 189 contract amendment with independent asset/runtime acceptance,
not a hidden change to the current v1 argc-one fixture. If OS argv must remain
unchanged instead, design an original intent/attestation-bound input carrier first;
ordinary environment variables or self-signed launch-record files cannot replace
the original manifest marker authority.

## Implementation and focused verification

Production changes: one shared policy comparison helper;
`python_producer_admission_gate.py`; `python_producer_adapter.py`. Existing parser
and observation adaptation can be reused without new public DTOs or wire changes.
This adopted contract is linked from Feature 191 spec/data-model/observation-adapter,
tasks and validation. Keep the separate static-RSI launch profile pending.

Focused tests must include:

1. The actual reviewed frozen-main encoder exercised with fake sys/loader/pipe
   facts, passed through the existing observation adapter and then both gate and
   adapter build/verify with an independently pinned matching installation. This
   is asset-level inert compatibility evidence, not runtime acceptance.
2. Different original OS executable argv and fixed PyConfig argv/orig_argv are
   accepted as separate domains; drift in either Python list is refused, including
   replacing either list with the OS arguments.
3. Named flag drift, missing/extra/duplicate/order changes and `-I/-S/-B` token
   replacement are refused; unchanged observations retain their exact digest.
4. Missing/wrong/replaced independent descriptor, installation-version and artifact
   pins, wrong binding target or a valid descriptor for another interpreter refuse
   without evaluator, provider, clock or filesystem effects.
5. The old Feature 189 argc-one/fixed-main versus native RSI marker incompatibility
   is explicitly preserved. No test fabricates a live scheduler success from this
   repaired detached observation helper.

Only inert local fixtures run; focused tests, ruff, compileall and diff-check are
required. Independent sealed image/owner/lifecycle/runtime acceptance, original
broker monotonic deadline and transcript, original terminal timestamps, pycache
inspection, bounded output capture and raw envelope/material pins remain external
gates before live handoff composition can be attempted.
