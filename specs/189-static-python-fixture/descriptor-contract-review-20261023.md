# Feature 189 — v1 descriptor contract review (2026-10-23)

## Decision

Freeze the existing `lunar-static-python-installation-v1` wire shape and parser
bounds for the bounded installation-owned static/frozen CPython fixture. The
normative v1 field list and declared nested record shapes are in
[`wire-contract.md`](wire-contract.md); the parser is
`src/lunar_evolution/static_python_installation.py`. New wire fields, altered
bounds, new inherited FDs, general solver adapters, or production admission
require a separate contract revision. No runtime or production claims are
enabled by this review.

The parser takes three caller-supplied pins: `expected_descriptor_sha256`,
`expected_installation_version`, and `expected_artifact_sha256`. There is no
fourth `expected_target_profile` argument. The descriptor digest commits the
fixed Linux/x86_64/CPython profile; the external artifact digest and independent
ELF inspection compare actual image bytes with the descriptor's declared ELF
projection; existing caller-owned launch/attestation/grant/deadline bindings
continue to bind sealed-target mode and lifecycle. This resolves the wording
mismatch without widening the wire.

## Declared fields versus observations

Descriptor nested records are declarations. Parser success proves canonical
shape, fixed-profile consistency, internal manifest-digest consistency, and
agreement with the three external pins. It does not prove that source,
toolchain, generated modules or object files were acquired or used by a build;
it does not verify the source signature; and it does not establish a CPython
executable or runtime startup. The parser fixes
`signature_verification="not-performed"` and all execution/admission claims to
false. The separate artifact verifier checks retained image bytes against the
declared ELF profile; it does not verify CPython identity or startup. The
`StaticPythonFixtureObservation` model remains a future observation contract,
not an implemented acceptance wire. These boundaries are reflected in
[`data-model.md`](data-model.md), `artifact-verification.md`, and G1–G3 tasks.

## Bounds reviewed against implementation

| Limit | v1 maximum |
|---|---:|
| Descriptor bytes | 262,144 (256 KiB) |
| JSON nodes | 8,192 |
| Nesting depth | 12 |
| Aggregate UTF-8 text | 196,608 bytes (192 KiB) |
| Individual input file record | 1,073,741,824 bytes (1 GiB) |
| Artifact bytes | 134,217,728 (128 MiB) |
| Patches | 32 |
| Tool executables / archives | 16 / 256 |
| Link inputs | 256 |
| Frozen / builtin / alias entries | 128 each as a scan ceiling; accepted profile is exactly 9 / 19 / 2 |
| Embedded startup arrays | Exactly empty (0); nonempty arrays require a revised contract |

These are rejection ceilings and shape limits, not evidence of complete input,
source, link or module closure. The 128 MiB image ceiling is unchanged.

## G0 outcome

The bounded SDD and v1 descriptor field/bound contract are aligned and frozen at
this scope. Feature 189 remains incomplete: source/toolchain custody,
configure/build recipe, complete startup closure, actual configured build and
ELF, sealed runtime, and target-owner lifecycle acceptance remain open G1–G3
gates. Keep `production_admission=false` and `online_publication=false`.
