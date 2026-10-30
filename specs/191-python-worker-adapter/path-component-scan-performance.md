# Canonical runtime path component scans

Status: narrow implementation, local focused checks and independent root-agent
source review complete; final-source acceptance remains pending. This changes only
`producer_python_runtime._path` under the existing Feature191 parser contract;
it grants no runtime or publication admission.

## Contract and measured problem

The [whole-case diagnostic](../189-static-python-fixture/whole-case-profile-20261026.md)
records 6,857,884 runtime `_path` calls, 11.30 self seconds and 21.93 cumulative
seconds. Its threaded attribution is imperfect, so these values are a hotspot
selection clue, not a prediction of wall-time savings or a passing Linux gate.

The existing lexical validator still splits, filters and constructs a tuple of
every path component, then joins them to compare the normalized spelling. Exact
canonical POSIX text can instead be recognized by rejecting repeated/trailing
slashes and complete `.`/`..` components. Strings are immutable and these scans
invoke no caller callback. Accepted non-root text has `slash_count + 1` parts;
`.` has zero parts and `/` has one anchor part. The UTF-8 byte limit and all
exact-type, control-character, absolute/relative, component and dot checks stay
mandatory. Invalid inputs retain `python_runtime_path_invalid`.

The original pathlib `_path_reference` stays unchanged as a differential oracle.
Before product edits, a separately compiled copy of the actual old `_path` AST
matched the proposed validator over 78,264 input/flag combinations. Nine local
alternating timing groups per workload measured candidate/baseline median ratios
0.6252 for representative canonical paths, 0.6199 for long canonical paths and
0.5665 for invalid paths. This is a pure-memory helper measurement, not an
end-to-end or target-platform acceptance result.

## Tasks and validation

- [x] Retain the exact old source and independently compiled AST before edits.
- [x] Establish differential equivalence and nine alternating timing groups.
- [x] Replace only component reconstruction in `_path` with bounded string scans.
- [x] Extend exhaustive/pathlib, Unicode, byte and 127–129 component boundaries;
  verify root/dot counting, exact type and foreign `__str__`/`encode` rejection,
  fixed refusal codes and absence of filesystem effects.
- [x] Run focused runtime/path/tree tests, Ruff, compileall and diff checks.

The four-module focused pytest process returned raw rc0 and reached 100% with
passing progress. A separate collect-only inventory contains 482 distinct cases:
73 path, 210 runtime, 151 runtime-tree and 48 directory-path cases. The original
run did not request JUnit, and pytest cleanup of old read-only temporary trees
emitted enough PermissionError warnings for the tool to truncate its stream;
there is no complete retained raw output or JUnit claim. Tests were not rerun to
replace that evidence. Ruff, focused compileall and `git diff --check` returned
zero. The landed function AST matches the separately measured candidate, and the
pathlib reference is unchanged.

No cache or retained parser marker is added. The validator runs on every call;
fresh SQL, filesystem, source/control and public DTO revalidation are unchanged.
No mixed case, model, evaluator, SSH, backend or package execution is authorized
by this slice. Full CI and separate Linux acceptance remain open.

Ignored primary-workspace measurement evidence:
`release-closeout-20261025/path-component-scan-candidate-pqzbusoy/measurement.json`,
SHA256 `5c6a709011c644e5d943813e2795f4165e359087de5b324823a6119e32b58c07`.
The separate collect-only inventory and post-edit checks are in its
`focused-validation-k4ddnum1/validation.json`, SHA256
`f366717efcb59e8b827c013e576ff5d350721a64d034fcc04bfdaba6739be494`.
