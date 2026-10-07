# Tasks

- [x] T170-01 Freeze producer config with create-only byte/inode/contract/launch bindings.
- [x] T170-02 Integrate exact config read paths and drift checks throughout native attempt/recovery.
- [x] T170-03 Add typed OpenEvolve opt-in, immutable execution binding and one-shot admission claim.
- [x] T170-04 Compose formal lifecycle → independent local single-file admission → atomic seed commit.
- [x] T170-05 Reconstruct retained seed admission from independently pinned receipts without evaluation.
- [x] T170-06 Cover actual local C/broker success, cancellation, timeout, drift, unknown and exact replay.
- [x] T170-07 Run legacy/focused/static verification; publish PR, pass final-head full CI, merge main.
  PR #6 tested head `2503589`, run `37651610902`, merged as `b3b2f13`. All current phases
  passed first run; Python3.11 archived required the one permitted known-node retry.

Python runtime manifests and real campaigns are not completion criteria for this slice.
