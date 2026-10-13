# Pinned local build execution mechanism

This continuation adds `run_pinned_build` in
`tools/static_python_rsi_fixture/execution_backend.py`. It is a separately callable
installer mechanism that actually starts child processes. It does not supply a
CPython recipe, replace the existing mock-only `run_controlled_build`, enable a
CLI or accept an installation. The original Feature 189 plan-only scripts and
Feature 193 mock API keep their execution refusals.

The current source/toolchain acquisition, release authentication, configured
compiler/cache/module/library closure and static image remain unobserved. A
reviewed executable CPython recipe cannot be derived honestly from the existing
candidate plan. This implementation closes the process-execution mechanism gap;
G1/F02c and live F03–F06 remain open.

## Inputs and integrity checks

The API takes the original `RSIProfilePreparation`, canonical recipe bytes,
mandatory independent recipe SHA256, existing source/toolchain roots, a fresh
workspace and one absolute monotonic deadline. It first reuses the existing
preparation validator, then checks the recipe pin/canonical wire and binding to
that same preparation. It neither re-emits preparation nor regenerates expected
pins from current input bytes.

The recipe schema is `lunar-static-python-pinned-execution-recipe-v1`. Its exact
fields are `schema`, `preparation_sha256`, `inputs`, `environment` and `stages`.
Source and toolchain inputs are sorted, duplicate-free regular-file records with
relative path, strict integer size, SHA256 and strict executable boolean. All
path components refuse symlinks, traversal and noncanonical names. The source
and toolchain snapshots are create-only copies with observed byte/mode readback.
Every declared original input and snapshot is reverified before and after each
command. Unlisted original files are not copied or implicitly admitted.

The recipe's independent digest is only an integrity comparison. It is not
source/toolchain authentication, build authorization or configured closure. Its
producer and tools are trusted installation inputs, to be reviewed separately
before a real build. The mechanism does not claim that the declared manifest
covers dynamic loader dependencies, all subprocess inputs, system configuration
or all possible filesystem access.

## Process graph and arguments

The stage order is exactly `configure`, `freeze`, `compile`, `link`. Each stage
contains nonempty bounded command and output lists. Executable argv[0] must name
a declared executable toolchain/source snapshot or a previously observed
executable stage output. `@source/path`, `@toolchain/path` and `@work/path`
references expand to the attempt's local roots; source/toolchain references must
be declared in the input manifest. Environment references use the same preflight
validation. No path lookup substitutes a host executable.

`subprocess.Popen` receives a list with `shell=False`, a fixed work directory,
closed inherited descriptors, disabled stdin, separate bounded stdout/stderr
pipes and a new process session. Literal compiler flags such as `-c` are allowed;
the installer must review its actual tool semantics. This is a trusted-tool
execution mechanism, not a shell/interpreter policy or an untrusted-code sandbox.

The environment is constructed explicitly from finite recipe build variables,
plus attempt-local PATH, HOME and TMPDIR. It never copies `os.environ` or reads
`.env`, model credentials or user configuration. PATH names only the toolchain
snapshot's `bin` directory. A missing declared tool refuses; ambient tools do not
fill the gap.

The complete recipe is at most 1 MiB, has at most 512 commands, and each command
captures at most 1 MiB combined stdout/stderr. Declared source/toolchain input
bytes have a separate aggregate 4 GiB bound and an individual 4 GiB bound; the
128 MiB image ceiling is not applied to compiler input files. Observed output
files retain the original 128 MiB ceiling, or their stricter recipe bound. These
are wire/capture/observation bounds, not a filesystem quota or proof of complete
static link closure.

## Deadline, cleanup and evidence

The original deadline is checked before and after each bounded file-read chunk, input/previous-output
verification, child startup, pipe servicing and stage completion. It is not
reset per command or stage. Timeout, cancellation, malformed callbacks,
nonzero exit, output/log overflow, missing outputs and drift stop the graph;
no later stage dispatches. Child pipes are drained using readiness polling,
without retaining unbounded subprocess output in memory.

For an in-flight direct child, cancellation/failure kills its still-owned process
group and waits for the direct child. A child already reaped by `wait`/`poll` is
never signalled using its numeric PID: that number could have been reused.
Evidence records direct-child reap separately and always keeps
`descendant_cleanup_verified=false`. No independent descendant ownership/cleanup
proof is introduced. A cleanup error remains `cleanup_unknown` and cannot become
successful command evidence.

The fresh workspace retains create-only recipe, started-attempt record, input
snapshots, bounded logs, outputs and a terminal `report.json`; failures do not
remove or replace partial evidence. A failed/partial stage stays outside
`completed_stages`, even when one of its commands exited successfully. Previously
observed outputs are hashed again before later commands. Public errors carry
fixed reasons and immutable detached stage evidence rather than tool exception
messages. A terminal report write failure returns an explicitly partial report.

Successful completion means that the pinned recipe's commands exited zero and
its declared outputs passed readback in that attempt. Every report retains
`configured_closure_verified=false`, `installation_accepted=false`,
`runtime_execution_performed=false` and `production_admission=false`.

## Remaining actual-build work

Obtain and independently verify actual CPython/Zig/musl bytes and identities,
freeze the reviewed configure/freezer/compiler/linker command and environment
recipe, close complete generated/static link inputs, and independently audit
ELF/artifact/inventory results before installation acceptance. The existing
nine-header/role contracts remain the reviewed candidate; this mechanism does
not manufacture generated-header pins or promote its output to F01/F02 evidence.
Actual sealed startup, authoritative request/memory/result consumption, solver
campaigns and production CLI remain separate acceptance steps. No real CPython,
solver, evaluator, WebAgent or company platform is run by this continuation's
validation.
