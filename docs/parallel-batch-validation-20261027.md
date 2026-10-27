# Parallel P0–P2 integration validation

This report separates implemented source from actual runtime acceptance. The
batch starts from `869198bca78f0c0285b3ed8b64068ceb01be6cde` on
`codex/openevolve-fixed-profile`. Original failed executions remain failed.

## Implemented changes

- P0: one lexical runtime-tree ancestry computation; truthful bounded own-stack
  v2 termination and retained-output behavior. Original Path construction,
  callback order, fresh identities and refusal gates remain.
- P1: explicit full-toolchain recipe v3, concrete same-source CPython freezer,
  object/archive/static-link commands and fixed solver source/native closure
  preparation. It requires independently reviewed configuration bytes and does
  not substitute host Python, SQLite or compiler inputs.
- P2: opt-in fixed SSH byte transport, installed private wrapper/key, durable
  intent and once-only result, unknown reconciliation, CLI entrypoints and
  existing-only SQLite connections. Original request budgets remain binding.
  Private readers reject nonregular files and use nonblocking no-follow opens
  to avoid blocking on a regular-file-to-FIFO replacement.

## Source-only checks

The retained official CPython 3.13.12 archive SHA-256 is
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`.
After the existing fixed source patches, the 3,044-entry source inventory pin is
`ffa4d1e90dc7409a48ea155a9837358aa9d4bfdbd5951c7758c091af62892987`.
Actual prepared OpenEvolve and Shinka manifests remain
`03266224f20d99aaef794cb8c9d8688f9ba8c1d44faf8c46b207c3780d4a6b06`
and `5a6e716142cf71d944adbc7e1622cb1a147f7ef9eaba556e9bb1f707680ecffa`.

Official SQLite 3.50.4 source bytes were obtained separately. The `sqlite3.c`
SHA3-256 matches the official release page; both c/header version and SOURCE_ID
agree. The two-file inventory SHA-256 is
`0e3ac7b881a8578c1fdf1f71666b7cf3216c5ff9d9eb7d53e3cd01f0a3d17965`.
The archive, release page, copyright page, response headers and verification
report are retained in ignored evidence. No supplied upstream code was imported,
executed or built by these source checks.

Initial real-source closure refusals are retained separately: missing
`collections.abc`, POSIX branch recognition, interpreter-created `__main__` and
Java-specific imports. Corrections use actual source behavior. They do not
establish that every function-local import is usable. In particular, conservative
scanning reaches interactive-completion dependencies; an unresolved required edge
remains a refusal rather than an accepted runtime.

## Centralized regression

The root ran one 30-file selection covering all new tests, direct runtime-tree,
build/worker consumers, SQLite and existing RSI/CLI boundaries: **1,050 unique
cases, 1,047 passed / 3 failed / 0 errors / 0 skipped**, raw exit 1, 66.470128
seconds. The three failures were a synthetic unsorted Zig inventory correctly
refused by the original `input_order_invalid` gate; only the fixture was fixed.
Original logs, XML and source-before/after maps remain unchanged.

Only eight affected files were then rechecked: **217 passed**, exit 0,
8.839296 seconds. Fixture-import lint corrections additionally rechecked just
the affected v3 file (16 cases); these overlap that selection. Latest-node
coverage remains **1,050 unique cases, all passed**, not a sum of repeated
executions. All run source maps were unchanged during their respective runs.
Four product/tool style corrections retain identical ASTs; test corrections
cover fixture ordering, explicit fixture imports and equivalent pairwise links.

Original Ruff failures, including intermediate fixture-shadow/import formatting
reports, remain retained. Final repository Ruff and compileall pass. Staged diff
checks include every new file. These checks do not accept a real runtime.

Evidence is in the primary workspace ignored
`parallel-batch-20261027/integrated-local-89uppce3`,
`integrated-affected-vdylt09v`, and the retained `integrated-v3-style-*`
successors. Original XML SHA-256 is
`a71bb5f791840bbc70260f0f545007f6a5d58950164fdcb6a1ac605f5e8bfbad`;
the eight-file affected XML is
`c7474e1eb31d088718befcf98d616433fba50110fd9f9caf1efec2c09e16e2b4`.

## Actual execution gates

The final clean source still needs its original 600-second, zero-retry Linux
mixed run. Its v2 stack observation, construction and finish costs share that
same budget. Local focused tests and diagnostic collection cannot close P0.
Full integration CI follows a genuine resolution of the known mixed blocker.

The opt-in cross-host case uses only a fixed inert producer. It checks actual
SSH/HMAC/once-only receipt and lost-response reconciliation, without running a
candidate, model, upstream solver or remote evaluator. It is not an untrusted
worker isolation, network-partition or remote-cleanup proof.

Reviewed target configuration, isolated static build, actual ELF/image, expanded
installation/startup, owner/lifecycle, actual solver output and native production
CLI remain open. The previously reported KVM/isolation permission blocker remains;
there is no unisolated fallback. `production_admission=false` and
`online_publication=false` throughout this report.
