# Feature 193 F03/F04/F05 raw/source/tree audit (2026-10-21)

This is an independent audit of the final source and retained GitHub Actions
artifacts for the F03 startup, F04 input/result and F05 runtime-handoff
contract lineage. It includes the correction source in PR59 and the PR54/55
dependencies that the correction was reviewed against. The audit used local
Git objects plus the GitHub API and artifact archives. It did not run CPython,
configure/build a target, launch a sealed image, call an evaluator or solver,
or modify any benchmark source.

## Scope and method

The audited CI runs are the final-source runs recorded for PR54, PR55, PR56,
PR57 and PR59:

| PR | source commit | run | synthetic checkout commit | source/synthetic tree |
| --- | --- | --- | --- | --- |
| 54 (F02) | `e08b04428bc3d72eb3621a71dab83895b447dcdc` | [38199240159](https://github.com/vchive/Lunar-Evolution/actions/runs/38199240159) | `bc802359803c8c0719c890a377f78104a93eb308` | `072fec9b92bb6ba44747952907a2907f6eb8377c` |
| 55 (F03) | `37aa8abe5faa94c6e1b8c493e016d9540b9b7dd1` | [38199245419](https://github.com/vchive/Lunar-Evolution/actions/runs/38199245419) | `6515ae16b092ce2e064053fc76c19cf1172ad7bb` | `a30effebc5c547041b57e96b556bd30856a6e9f6` |
| 56 (F04c) | `7665164e7c0bd64052c624da8c119c9972d01865` | [38199255630](https://github.com/vchive/Lunar-Evolution/actions/runs/38199255630) | `8596f4c3844f1850ed5ca209ab965b8f47a2fc00` | `f96f5239f4de8039dc22c251297fc16a36858f57` |
| 57 (F05c) | `7ca3816a4336fe0b5b1011294197fffc8f5538ac` | [38199260479](https://github.com/vchive/Lunar-Evolution/actions/runs/38199260479) | `475effe466dbe4296771a9af3a3a1678c68f60fc` | `4f19cf6a8d233f12fdbf0afbdcc6a17abd1b76df` |
| 59 (F02d/F05d correction) | `a6a8eb262a9ef79a6468e02f4d5c158afaf718a3` | [38200497242](https://github.com/vchive/Lunar-Evolution/actions/runs/38200497242) | `87214adf836893bd9f8c9412d06e139b23ad00d0` | `cd289591450463e2cdfa73b88d67aa9d789e40b0` |

For each run, all 15 non-expired artifacts were downloaded through the API
and checked with `unzip -t`. Each archive contains exactly one
`job-provenance.json`; all 15 provenance records in a run agree on the
synthetic commit, tree, parent tuple, schema and import origins, and expose
the expected 3 Python versions and five roles (`focused`, `current-0`,
`current-1`, `current-2`, `history`). The five artifact manifest digests
(sorted `artifact-id`, name, API size and archive SHA-256 records) are:

The GitHub run API independently reports `completed/success` for all five runs,
and the jobs API reports 15 completed-success jobs for each run. The reported
head SHA equals the named PR source commit in every row below.

| run | artifacts | manifest SHA-256 | XML files | tests | failures | errors | skips |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 38199240159 | 15 | `52bba675dad1da04a13e1fae53a8eaac3439d21274a22cbd05b9093111e7e54e` | 159 | 68,655 | 0 | 0 | 483 |
| 38199245419 | 15 | `0aa80efc10e7de1b48bb33530ee0f2ffa5fb53795daea7b1848b4b024aeddea8` | 159 | 68,691 | 0 | 0 | 483 |
| 38199255630 | 15 | `3a93b5a26e681bea3704008e7fe5412f4c58908d7f26761a0b62b341f04290d4` | 159 | 68,718 | 0 | 0 | 483 |
| 38199260479 | 15 | `63d4308cc1d01c2ee784cff28b720169c6868750a873ee4df51d2f3e41d15780` | 159 | 68,748 | 0 | 0 | 483 |
| 38200497242 | 15 | `59558b26ea512a79208aca933bcfc98640b76e33c8e3c840ad24428568721c76` | 159 | 69,492 | 0 | 0 | 483 |

The skips are the known platform/ABI skips in the retained matrix. They are
reported from the XML and are not converted into passes. Focused artifacts
contain overlapping selectors, so the aggregate test count is an artifact
inventory count, not a claim of that many distinct tests.

## Source/tree identity and correction lineage

The source commit tree was independently read with `git ls-tree`; the
synthetic merge commit recorded in each artifact has exactly the same tree
object as the PR source commit. The source trees contain respectively 1,879,
1,882, 1,885, 1,888 and 1,888 regular entries. Their regular-file byte totals
are 18,046,161; 18,064,404; 18,080,837; 18,098,978; and 18,140,720.

The tested checkout lineage is coherent:

* PR54 source `e08b044` is the reviewed build-closure merge from PR53's tree;
  synthetic `bc802359` merges that exact source into base `15f762b`.
* PR55 source `37aa8ab` is a child of the PR54 source; synthetic `6515ae16`
  merges `37aa8ab` into `e08b044` and retains the exact `a30effe` tree.
* PR56 source `7665164` is the F04 cross-pin source on top of PR55; synthetic
  `8596f4c3` has parents `37aa8ab` and `7665164` and the exact `f96f523` tree.
* PR57 source `7ca3816` is the F05 handoff source on top of PR56; synthetic
  `475effe4` has parents `7665164` and `7ca3816` and the exact `4f19cf6` tree.
* PR59 source `a6a8eb2` is the correction source. Its first parent is the
  repaired dependency merge `1991a99` (which includes PR57); its synthetic
  `87214adf` merges PR57 head `7ca3816` with `a6a8eb2`, retaining the exact
  `cd28959` source tree. The PR59 base merge `f296431` also has PR57 head as
  its second parent. This records the correction lineage without treating a
  stale PR57 tree as the final source.

Selected immutable blob checks (Git object ID, then byte size) include:

| source | path | blob | bytes |
| --- | --- | --- | ---: |
| PR54 | `src/lunar_evolution/static_python_build_closure.py` | `4bf153f1961096451e9931d96f065d7aa56d4b8b` | 19,130 |
| PR55 | `src/lunar_evolution/static_python_runtime_startup.py` | `bc1f2c62f951980bc8b24593a7c5b6eb4a34323d` | 8,726 |
| PR56 | `src/lunar_evolution/static_python_input_result.py` | `71c8dead840e7432f0f4c3fe03d37c647e49a648` | 7,858 |
| PR57 | `src/lunar_evolution/static_python_runtime_handoff.py` | `088db62cb6cb0a1f5dc2851201d2ce767655a046` | 8,190 |
| PR59 | `src/lunar_evolution/static_python_build_closure.py` | `a0a3c01b312812c0be59482ae3ae2b1a250620a6` | 23,576 |
| PR59 | `src/lunar_evolution/static_python_input_result.py` | `bf249c15926f14096362ddb6f3718a6f9b3f3eb2` | 7,907 |
| PR59 | `src/lunar_evolution/static_python_runtime_handoff.py` | `b61492c1669d8720119ea9295ddb409f0ac4055c` | 9,281 |
| PR59 | `src/lunar_evolution/static_python_runtime_startup.py` | `33ff60b16e2df52f997a8aa0a33fa7e590d2b767` | 9,214 |

The source tree and blob checks establish that the raw artifacts were produced
from the named immutable source trees, including the PR59 F04/F05 correction;
they do not establish a build or runtime.

## Result and limits

This audit closes the independent raw artifact, source object, tree identity
and PR54/55/56/57/59 correction-lineage obligations for the detached F03/F04c/
F05c contracts. It is now safe to mark those audit checkboxes complete. The
raw job logs themselves were not used: an earlier GitHub log-download attempt
timed out, so this report does not claim raw-log acceptance. The downloaded
archives are not committed to the repository; the API run IDs, artifact
manifest digests and immutable Git object IDs above are the retained replay
anchors.

Nothing here accepts F02c installation/build closure, sealed startup, owner or
native lifecycle, authoritative input consumption, producer publication,
durable recovery, or production admission. `production_admission=false`
remains in force.
