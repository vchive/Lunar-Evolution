# P0–P2 integration, 2026-10-28

The batch implements three software continuations before concentrated regression:
operation-local staging identity parsing, the opt-in native private collector
sink, and installed wrapper/native bridging with independently retained original
restart anchors. Default protocols and original budgets remain unchanged.
Production admission and online publication remain false.

## Implemented and tested

- P0 retains immutable plain-entry bytes only within one history walk. Fresh
  checkpoint observations, state/policy/capacity checks and the admission reader's
  second SELECT/decode remain. Direct parser/digest drift falls back to the old
  path; scheduler/BRS projections pin the new helpers.
- P1 extends the original native runner with private pipe control v3. The selected
  in-image launcher writes the bounded collector result and closes the pipe
  before solver entry. The host compares original target/image/PID/manifest
  inputs. This is not an acknowledgement gate before solver start or accepted
  build custody. Legacy launcher and v1/v2 remain selected by default.
- P2 explicitly wires the wrapper to the existing native runner and its original
  registered observer. The observer retains the original anchor in a separate
  private installation vault before gate release. A fresh process reads that
  anchor and invokes existing read-only native inspection. There is no generated
  attestation, launch retry, solver-success conversion or deadline renewal.
- README now reflects existing HMAC, durable assignment and fixed SSH support,
  with one authoritative local controller and explicit unknown reconciliation.

## Concentrated results

The original failed `12f987fb` Linux mixed run remains preserved and is not rerun.

| Execution | Actual result | Source check |
| --- | --- | --- |
| macOS 58-file initial union | 2,164 nodes: 1,839 pass, 8 fail, 317 platform skips; 876.705357s | All 2,535 Git source files unchanged |
| macOS 10-file affected union | 461 pass, no failures/errors/skips; 6.782417s | All 2,535 source files unchanged |
| Linux 55-file frozen-tree union | 2,035 nodes: 1,970 pass, 2 fail, 63 skips; 580.047717s | 2,843 archive entries/2,535 files match before/after; all 231 loaded Lunar module origins match |

The latest macOS union is **2,547 unique nodes: 2,230 pass and 317 skips**, not
2,625. All eight original failed nodes passed in the affected run. Linux's two
failures are the original recipe-selection cases; their corrected-source Linux
execution is still pending. Skips are not passing platform coverage.

One genuine integration bug was found: the new recipe branch compared a shortened
launcher path that did not match the source plan's actual fixed path. The fix
makes the opt-in profile compile `runtime/launcher_live_sink.c`; the default
continues to use its original full launcher path. The two recipe failures exposed that genuine opt-in selection bug and an
incorrect default-path assertion. The other six failures were fixture construction:
two unset thread-local cache attributes, two bindings enlarged by the unusually
long test temp root beyond the unchanged 32 KiB cap, and two Darwin C-harness
deadlines using a different clock base. A fresh short private temp root and C's explicit CLOCK_MONOTONIC fix these
fixtures without changing product caps, C marker or Linux deadline semantics.

The first Ruff results are retained. Final project Ruff, compileall and staged /
unstaged diff checks passed after the affected repair. No model, WebAgent or
remote/company evaluator was run.

Evidence is in the primary checkout's ignored directory
`.lunar-evolution/validation/parallel-batch-20261027/`:
`p0-p2-concentrated-local-tc3joq0u`, `p0-p2-affected-local-e2hfu9yz`,
`p0-p2-static-bq3w2vuq`, and `linux-native-focused-draft-3buch_cy/remote-records`.
The Linux archive is frozen Git tree `fa33b03c21315cd6e73db08f1bf1eae4034595f2`,
base HEAD `72c2f973`, archive SHA256
`ce91f6adeaeabfeab48e647a19eb3c6cc511043e55aa0a270c3214670c5551ba`.
It is not described as the later corrected commit.

## Still open

1. P0: the corrected clean source's original 600-second, zero-retry mixed run,
   then actual Linux completion and complete CI before main. The small parsing
   probe and focused passes do not establish resolution of the repeated timeout.
2. P1 software: actual accepted-build/input-custody consumption, complete implicit
   link inputs and the production per-episode configuration loader/composition.
   Source recipes, descriptions and collector output do not supply those facts.
3. P2 software/design: installed account transition and its actual access/runtime
   evidence consumers; an independently surviving trusted durable guardian sink
   with reviewed acknowledgement/deadline semantics. A parent-owned pipe does not
   survive that parent; regular-file fsync has no hard completion bound.
4. Actual acceptance: isolated x86 build/image/startup/solver/lifecycle, distinct
   account key/state access denial, hard disconnect and abnormal cleanup. The
   5090gpu sudo/KVM/userns/bwrap restrictions affect corresponding environment
   gates; they do not explain away unfinished software. macOS ARM cannot execute
   the current accepted x86 build profile natively. Host Python is not a substitute.

No P0–P2 production-complete or main-merge claim is made by this report.
