# Expanded runtime observation and mapper

Status: implementation prepared for concentrated regression; not production or
real static-image acceptance. No result here closes the existing build, custody,
solver lifecycle, installed-account or CLI acceptance gates.

## Contract and separation

The explicit source profile `fixed-live-runtime-private-sink-v1` extends the
existing fixed expanded solver preparation and native private pipe. The default
source, old module-only collector bytes, C launcher, control v3 framing and old
nine-module policy remain unchanged. A separately SHA-pinned supplement is
appended to the existing frozen main and supplies its reviewed collector entry
point. Both sources and their exact composition are checked against the expanded
installation's `_lunar_static_main` source record. Every selected image must be
built again; a changed source pin cannot authenticate an old image.

The original C launcher calls the selected collector before solver import and
writes its result to the original bounded private pipe. The existing target PID,
held image device/inode, marker, deadline, image byte check and complete module
metadata comparison apply. There is no new process, sink, stdout protocol,
retry, timeout, gate release or publication authority.

## Actual observations

The supplement reads facts from the executing interpreter's `sys` object and
`posix.uname`: version major/minor/micro/releaselevel/serial, implementation name,
cache tag, ABI flags, debug-build observation, actual GIL state, platform,
architecture, pointer-sized `sys.maxsize`, Python `argv` and `orig_argv`, actual
hash-randomization flag, filesystem encoding/errors and each of stdin/stdout/
stderr's encoding/errors. It retains the existing actual isolated flags, empty
path and whole `sys.modules` snapshot with original module identities.

Streams must be the original-shaped exact builtin `_io.TextIOWrapper` type.
Missing streams/facts or unrepresentable values refuse; no selected descriptor,
OS launch arguments or caller expectations supply a missing observation. Runtime
facts and the original table identities are checked again after the image and
module observation window. This only detects that window's drift; it does not
prove future immutability.

The resulting bounded canonical wire has the distinct schema
`lunar-static-python-fixed-live-runtime-v1`, collector profile
`fixed-live-runtime-v1` and the independently pinned supplement source digest.
It carries all legacy module/image fields plus `runtime` and
`runtime_source_sha256`. Legacy consumers cannot silently interpret it as the
old module-only schema.

## Comparison and mapping

`map_fixed_python_runtime_observation` compares the exact expanded source/image,
original target identity/manifest and captured runtime fields. The separate
`validate_fixed_python_runtime_observation_policy` rechecks a retained original
snapshot against mandatory installation and observation pins, original image
bytes and composed source. The complete original module metadata comparison is
repeated, so a fabricated bound DTO cannot bypass it. The entry point is also
exported from `python_runtime_observation_policy`, alongside the unchanged exact
legacy entry point.

The fixed source baseline is CPython 3.13.12, Linux x86-64, release GIL build.
The comparison checks actual version, empty ABI flags, debug false, GIL enabled,
cache tag and 64-bit `maxsize`. Its ABI label derives from those actual checked
facts. Actual Python arguments, flags and encodings must match the independently
parsed `FixedPythonInstallation` initialization config. Stderr deliberately
requires CPython's `backslashreplace`; stdin/stdout use configured `strict`.
This distinction follows the pinned `Python/pylifecycle.c` `init_sys_streams`
implementation: stdin/stdout use `config->stdio_errors`, while stderr passes
`L"backslashreplace"` explicitly.
Available modules are never filled in as imported modules: `startup_modules`
contains the actual collected whole-table names.

The result is `FixedPythonRuntimeFacts`, retaining the original bound sink wire.
It is not a fabricated `PythonProducerRuntimeObservation`: startup collection
has no broker transcript/computation digest, terminal state or pycache-absence
observation. Those remain actual lifecycle requirements. All live-authentication,
immutable-custody, production-admission and online-publication claims remain
false. Detached supplied bytes do not establish provenance; original native
sink acquisition and accepted build/custody remain required.

## Concentrated validation

The new focused file covers actual-value extraction, missing-fact refusal,
expanded installation/config comparison, ABI/platform/argument/encoding drift,
original image/source/PID/inode/manifest binding, retained-wire and DTO drift,
strict legacy separation, required independent supplement pin and unchanged
default/legacy source bytes. Tests use explicit local synthetic objects and
inert image descriptions, never host Python as a static-image acceptance or a
real solver/model/evaluator. Ruff and compileall are static checks; no runtime
result is asserted before the root's shared focused regression.
