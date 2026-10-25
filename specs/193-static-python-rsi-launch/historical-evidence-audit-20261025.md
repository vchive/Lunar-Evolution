# Historical source/CI evidence audit (2026-10-25)

This audit closes the remaining historical raw/source/tree evidence gaps in
Feature 193 and the final observation-policy gap in Feature 191. It uses the
original retained artifact ZIPs, job logs and source inventories, fresh GitHub
API snapshots, and immutable Git objects. It does not substitute PR187 or the
current main tree for an older PR's final source. No product module, test body,
test collection, build, worker or evaluator was executed during this audit.

## Final source and exact current inventories

Every run and all 69 jobs are `completed/success`. The current case count below
is independently verified for **each** Python version, 3.11, 3.12 and 3.13.
Every version has the exact source inventory, no missing or duplicate cases,
zero current failures/errors, and 92 retained platform/ABI skips.

| PR / scope | final source HEAD | final run | original ZIPs/jobs | current cases per Python |
| --- | --- | --- | ---: | ---: |
| 49 / Feature 191 observation policy | `87e579af373652c328cbd4f205221eaaef762700` | [38198657810](https://github.com/vchive/Lunar-Evolution/actions/runs/38198657810) | 3 | 14,070 |
| 50 / T11b launch | `861e068dfe78c2af9aae0aafa0195894ceb9456e` | [38198840702](https://github.com/vchive/Lunar-Evolution/actions/runs/38198840702) | 3 | 14,152 |
| 51 / F01f profile | `517593c144d6273995f9c615e074aef9fc6e4374` | [38198846690](https://github.com/vchive/Lunar-Evolution/actions/runs/38198846690) | 3 | 14,265 |
| 52 / F04e input/read report | `ac763f0313a97be54c41c8ad476c430c4d251dc2` | [38199122019](https://github.com/vchive/Lunar-Evolution/actions/runs/38199122019) | 15 | 14,607 |
| 53 / F01k installation contract | `4f4d88075eed6ae3f9170cf3eab15fe75f3ad437` | [38199235337](https://github.com/vchive/Lunar-Evolution/actions/runs/38199235337) | 15 | 14,796 |
| 66 / controlled mock build driver | `3551b9e65ac4152d2316ccd4366323dda5188ecd` | [38270514933](https://github.com/vchive/Lunar-Evolution/actions/runs/38270514933) | 15 | 15,179 |
| 88 / pinned process execution and producer gateway | `5bb90c915f8a3bd0e729ae6ede750595c406edb1` | [38358940938](https://github.com/vchive/Lunar-Evolution/actions/runs/38358940938) | 15 | 15,475 |

| PR | source tree | Linux current case-ID SHA-256 |
| --- | --- | --- |
| 49 | `32ce31b610772c8d4adb0f81d13f6530e22e40a5` | `bc75fc331e765a9b8bb991ed88f54c2378498adf50ad1ecbd200402af284b459` |
| 50 | `dfc132baaa1ed9d38149abf793bf318e79ebf333` | `07216975c6be8772dd135dea9ea7e4443d5e46cb270fb25e85fe49c58a1f5a34` |
| 51 | `146f5790ab1b19de198abc6a85a4455b33921043` | `8d96db790c1a7d9aa8e6beb56214fdc736c4a987984076352fcb3f1f930aba27` |
| 52 | `e227d056ac0ef30c83fa3f6c564537b950c56b48` | `190349597ebcf68ffe07b557c3f3ba25af1f42ff0cb21af48d7d06f76e109f12` |
| 53 | `1a8a82cc62674cceab89a9d6c75f148a81b418c3` | `d82b1bb42b71ee49dd0031a7df3abe4c4951f8e48e9ae1d70faff1fe65414d9b` |
| 66 | `89213b1ba5c2f0f2281316fec0afa1b7f4e6ae0e` | `5e27e45812c4bf496c91763b47ab7ca06b7ad157fe73eeda511ead162af0ae79` |
| 88 | `c94cd72d6667d609dacca9e985b9cd32110e2483` | `85595d8d763eec8e150af3a5249b0493f950be69b51c409c9b8d6b57ca296bd9` |

## Independent checks and preserved exceptions

All 69 original ZIP sizes and SHA-256 digests match the authenticated GitHub
artifacts API; CRCs and unique, safe member names pass. XML counts, testcase
keys and hashes match the original source inventories. Source tar entries and
extracted Git source files match immutable Git blob IDs and executable modes.
Each synthetic checkout has the exact final source tree and ordered parents
ending in that source HEAD. Signed synthetic commit objects were reconstructed
from GitHub's verification payload/signature and reproduce their Git SHA-1.

PR49/50/51 used the original three-job workflow, which did not emit the later
`job-provenance.json`. Their original ZIP runner summaries bind the XML hashes,
checkout commit and exact import origins; raw checkout/upload logs bind the
same GitHub job and artifact IDs. Their earlier source-collection commits are
reused only after proving identical final trees. PR52/53/66/88 retain all 15
version/role combinations: `focused`, `current-0`, `current-1`, `current-2` and
`history`. Their provenance and full/selected shard nodes, node-to-case mapping,
file assignment and disjoint current unions match the persisted source data.

The source-bound results include the 74-case observation-policy gate, 82-case
launch gate, 113 profile cases, 219 input-read-report cases, 189 installation
contract cases, 38 mock build-driver cases, and PR88's 26 execution-backend plus
30 producer-gateway cases where applicable. Overlapping focused XML records
are not counted as additional distinct current cases.

Two original historical archive failures remain visible: PR52 Python 3.12 and
PR88 Python 3.13 each failed only
`tests.test_measurement139_observation::test_preparation_ceiling_does_not_leak_between_threads`.
Both original failed `archived.xml` files and successful `archived.retry1.xml`
files match their recorded attempt hashes and exit statuses. Final archive
summaries pass; no current or focused XML has failures/errors. The fixed
2,294-case archive and 24-case frozen inventories retain their original source
and product pins. Skips and original failed attempts are not rewritten as passes.

The PR88 inventory directory has 2,167 extra unmanifested `__pycache__/*.pyc`
files observed before this audit. They were preserved and never loaded. Every
original manifest-defined payload still matches its size/hash; the original
`source.tar` has the exact Git file set, and every extracted Git source file
still matches its blob and mode. The cache additions are separately listed in
`pr88/extra-cache-observation.json`. This proves the original archive/source/tree
identity; it does **not** claim that the present extraction directory is pristine
or has a closed filesystem payload set. The original missing PR66/88 event list
is not reconstructed; binding uses authenticated run/jobs/artifact/commit APIs
and original checkout provenance/logs.

## Retained receipts and closure

Paths below are relative to the original evidence workspace
`/Users/liminghan/Documents/lunar_agent`. They are ignored local evidence, not
committed artifact archives. Each machine-readable audit records the original
ZIP/log/source paths and hashes, API snapshot hashes, source trees, synthetic
checkout parents, exact XML inventories and exceptions.

| scope | ignored receipt path | receipt SHA-256 |
| --- | --- | --- |
| Feature 193, PR50/51/52/53/66/88 | `.lunar-evolution/validation/feature193-historical-audit-20261025/receipt.json` | `781d66b3998f8ffde9533c23928b55cfecf7da65b8ad8ce4226164acce652fbd` |
| Feature 191, PR49 | `.lunar-evolution/validation/feature191-pr49-historical-audit-20261025/receipt.json` | `f42821b8e0c976c7a0774b8da4fd2f6486427a0660181b9e6505d35ce52e727f` |

The Feature 193 directory also retains `final-audit.json` (SHA-256
`eeac7094fc5fb6ba891e9e819aacc698faf8bdd821de43f54166c498747a1d39`)
and read-only `verify_retained.py` (SHA-256
`738b3242635a96ff14fac07eb436d837679cbec172c75d25667a1b5c73389f43`).
The Feature 191 directory retains `final-audit.json` (SHA-256
`9649dd959d88f62fcddf1fe001d977fbac96f4117774152131ccfdd79c8a2803`)
and `verify_pr49.py` (SHA-256
`07eea054f0fe42af3c77e0a938870ea966539dcda8623badef73e77f0096cec8`),
which pins and reuses that historical verifier.

The parent reviewer independently rechecked all69 ZIPs and their API/member
digests, exact XML inventories, original archive failure identities, source
tar/Git blobs/modes and source/synthetic commit hashes. All seven sources
passed without running tests or collection. The separate receipt is
`.lunar-evolution/validation/feature193-historical-audit-20261025/root-independent-audit.json`,
SHA-256 `70f9f9689e805eaf955bd4c1ec886e0b428c92c4b6d2a966e4cade136e58faab`.

These results support closing the seven named historical audit obligations.
They do not accept F02c/G1/G2 real installation/build closure, sealed startup,
runtime input consumption, producer publication, native lifecycle or production
admission. Those gates remain separate; `production_admission=false`.
