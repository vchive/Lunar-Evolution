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
