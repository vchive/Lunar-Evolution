# Validation

Use only inert temporary files; the file labelled interpreter is never executed. Validate
canonical roundtrip and external pins, each role's byte/stat drift, identical-byte inode
replacement, root/parent/import-directory replacement, links, special files, bounded inputs,
read-time mutation, no execution/writes and descriptor closure on failure/interrupt.

The explicit limitation case adds an unlisted file and verifies the unchanged declared inventory.
It demonstrates why this API cannot establish complete imports or runtime-loaded byte protection.

Local Python3.11 installed environment: focused210 passed, no skips/failures/errors
(`/tmp/lunar-python-runtime-tests-agent.xml`). Final joint runtime/isolation/bootstrap/attempt/
OpenEvolve/config suite385 cases:351 passed,34 Darwin platform skips,0 failures/errors,
57.183s (`/tmp/lunar-local-runtime-final-oct8.xml`). Counts overlap and must not be summed.
The final joint run had no cleanup warnings. Public exports, documentation Python syntax,
Ruff `src tests tools`, compileall and diff checks passed. Independent implementation review passed.

The final-head Ubuntu matrix/PR merge remain pending at this source commit. Its checks/merge
record are authoritative for later status; PR6 CI is not evidence for this new slice.

Final-head validation supersedes the source-time pending statements above: PR #7 head
`16fb8ac0b0f00233a8aee60208fc5a9ba767b966`, run `37660700817`, complete Ubuntu3.11/3.12/3.13
all passed on the first run with zero failures/errors and no retry. Each runtime-preflight phase
had240 cases/1 i386 ABI skip; current10108/31 skips, archived2294/0 skips and frozen24/0 skips.
Original XML was independently audited. Merged into main at
`009691a13d2fd99ee141659216f1e7f13eaff63b`; main tree equals tested head.
