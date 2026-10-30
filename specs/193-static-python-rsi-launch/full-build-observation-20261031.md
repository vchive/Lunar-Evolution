# Actual configured build observations — 2026-10-31

The initial observations use software `01d740f08df65674f3791db6c8c034b329fb286c`,
tree `78eacb0f0b42261e4c662afdb6815832ef54fa18`, and the independently approved
configuration packets in `delegated-configuration-review-20261030.md`. Later
test-budget and documentation commits do not rewrite this execution provenance.
Each fresh build has one original 3000-second budget and zero automatic retries.
No model, evaluation campaign, target image or production CLI is run.

## OpenEvolve

The earlier complete command execution remains a refused build: all 298
commands returned zero, but the old compiler comparator rejected an include
path. That attempt was not a timeout and has not been relabelled successful.
Pure comparison of its retained depfiles through the explicit source-directory
profile is a separate observation.

A new fresh original execution using that profile completed all 298 commands,
202 compiler and two linker comparisons. Remote monotonic duration was
1882.0478494348936 seconds; the separately retained local transport duration
was 1688.9919820418581 seconds. These are distinct host clocks, not interchangeable
measurements. The original SSH child returned zero and was reaped before archive
collection. Product source bytes and Git execution-bit projection matched before
and after execution.

The independent review matched all 13,545 regular archived files, 298 commands,
596 command logs, 502 output records, 202 depfiles with 44,304 entries, 18 source
directory-alias references across 12 allowed spellings and both linker records.
VFS/control records and raw retained blobs also matched. The uncompressed
archive is 255,385,600 bytes, SHA256
`0181c3bb5c98eb73cf7920cefec3bf6301c8c4dcf3f5b157b334a10f30119cf9`.
The report/dependency audit receipt SHA256 is
`9ab891465cd5d4d9777cc7058f48b28682056253564ccf75ef66d9b4ac6d836d`.

A separately reviewed, once-only 300-second read-only observation then called
the implemented candidate API against the original retained source/toolchain
workspace. It completed in 21.31382774701342 seconds, without rebuilding,
executing the image, retrying or extending the build budget. Product source
readback matched before and after. Independent reconstruction of the entire
candidate from original closure/report records matched its canonical bytes,
including 93 frozen modules, 33 native units, image mode 0555 and initialization
configuration. Candidate comparison pin:
`46e4e4be5f84ea8f0959074029aee7311eacf4c979cfa471d04d1df8085464ad`,
46,427 bytes. Actual-observation audit receipt SHA256:
`517041e0ff96d73aeafe7d5bd914de8a67bd441ddd44fbfc48857c3ce023d043`.

## Shinka

The fresh original 318-command execution returned a consumer failure after
2143.9325685151853 remote monotonic seconds, inside its original 3000-second
budget, with zero retries. Its runner report is complete and all 318 commands
returned zero (configure1/freeze311/compile4/link2). The separate dependency
consumer failed with `build_dependency_readback_or_evidence_failure`; the
original failed attempt remains failed.

Independent review matched all 14,441 regular archive members, 532 outputs,
636 command logs, 318 VFS manifests/5406 records/1276 blobs, original control
chains, all original directory identities and four input trees' FD/hash readback.
The uncompressed archive is 357,365,760 bytes, SHA256
`56058487a4f786062ced5477558441cce7d4edd78d0ae4e308d63ed3cf2c151e`.
Pure retained comparison of 212 compiler/two linker depfiles passed separately;
it did not convert the original failed consumer into a success.

The exact cause is freeze233's original `stopped` state: its original wait was
zero and Running/PID/ExitCode/OOM fields were terminal, but the runner and
validator disagreed on the terminal tag. A separate read-only diagnostic
reproduced the original validator refusal. Root-cause review receipt SHA256:
`a8bfa3d0ab0517600057d770d2a7e8805bd7765e458b3f4f254d7989d8c5a97c`.
The common finite predicate is corrected in `terminal-state-consistency.md`;
all 73 additions passed in the 826-case concentrated Linux batch, with no
failures/errors/skips/retries and unchanged source bytes/Git execution bits.
On an independently reconstructed clean `0de18312` product, a new once-only
300-second read-only diagnostic passed the original report/VFS validation,
all four input trees and all 532 output FD readbacks in 20.712070 seconds.
The original failed report and workspace were not modified; no dependency
receipt, comparison artifact or candidate was written. An earlier diagnostic
preflight correctly refused the test product's extra pytest cache before any
product import; the test product was preserved and the clean build copy was
constructed from the pinned source archive instead. This is separate post-build
readback, not a successful rerun of the original consumer.
Its final-source CI and a fresh corrected-source build remain required. No
successful original dependency receipt or Shinka installation candidate is
claimed from this failed attempt.

## Shinka with original VFS lifetime

A separate fresh execution used software
`02347d6861273ef7c66423e166019002aa54ef60`, tree
`a94ab84e762ee558ffd4ed0b38d6849cb088c31b`, the same independently reviewed
318-command graph and its original 3,000-second budget, without retry. All
318 commands and the original 212 compiler/two linker comparisons completed.
Remote monotonic duration was 2828.000363613013 seconds; transport duration
was 2828.85052262526 seconds, return code zero, original SSH child reaped and
no timeout. All 2,777 product-source records matched before and after.

Independent review matched 22,397 archived files, 3,181 controls/6,362 log
references, 318 VFS manifests/5,406 raw records, 318 lifetime manifests/5,724
raw records across five original phases, and 532 current/promoted outputs.
The 46,558 dependency entries retained the finite 12-spelling source-directory
profile. The linked static image is 12,669,464 bytes, mode 0555, SHA256
`6cf887932006df4861da955e88279a0847622924af463318eae9af0fe95cd835`.
The original full-review receipt is SHA256
`35ceb2dfc44bf4309cd1ea79c84d9e3f3ffb5160a4d3346c83bb3fe894879a54`.

One separately reviewed candidate observation then returned a harness failure
`independent_mapping_pin` after 31.788106217049062 remote seconds, within its
original 300-second budget. Its transport returned one and was reaped without
timeout; source bytes matched before and after. That failed observation remains
failed. Passive reconstruction identified two audit-derived comparison hashes
using the build JSON domain with a trailing newline instead of the installation
JSON domain without one. This is an audit expectation defect, not a product or
full-build defect. The create-only correction addendum replaces only those two
derived expectations; it does not change the original review, build evidence or
failed candidate result. Any corrected observation needs its own exact review
and distinct output path.

The full original tar is 516,997,120 bytes, SHA256
`8a40e482809267806fcc4f0cd87cb46a7cda64725384a3884ddf583c311af701`.
Its complete bytes remain in the remote original tar and local lossless
`originals-v1/finite-originals.tar.gz`; the redundant local plain tar was removed
only after independent streaming decompression matched the original size/hash.
The storage ledger preserves that path change. Source/toolchain/prior inputs
are manifest references rather than copied archive members; this archive does
not recreate live ownership or immutable input custody. No ELF, runtime or
solver was executed by this build or the candidate observation.

## Unaccepted boundaries

These results establish actual command execution, the finite dependency
comparison and present candidate readback. They do not prove all implicit driver
inputs or immutable input consumption during the original build. Matching
retained files and VFS observations cannot supply missing original authority.

Original immutable custody, accepted executable/runtime root, sealed startup,
live owner and native lifecycle acceptance remain open. The first production
scheduler-context loader, production RSI CLI and copied local cases depend on
that chain. Fixed-U interval exclusivity, external-writer acquisition and real
root/account/ACL/cgroup prerequisites retain their separate missing conditions.
All original authority claims, `production_admission` and `online_publication`
remain false. Final-source CI and its independent source/original audit are
required for each successor; these build observations do not replace them.
PR199 has since completed its own 45-job CI/original-source review and merged
as `3de1e92d`. PR200 retains its separate final-source CI gate.

Evidence is retained beneath the primary checkout's ignored
`validation/native-support-export-20261030/`, in the corresponding
`full-cpython-*`, `actual-retained-candidate-*` and
`delegated-configuration-review/` directories.
