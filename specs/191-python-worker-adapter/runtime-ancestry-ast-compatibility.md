# Historical ancestry AST compatibility

The original Python 3.11 and 3.12 current-5 jobs failed the historical ancestry
loop fingerprint while Python 3.13 accepted the same retained source. These
original failures remain failures. The loop in the independent `_ORIGINAL`
fixture is structurally and textually identical to the loop in historical
`869198bc` and PR189 `2486`; product ancestry behavior did not change.

Python 3.13 added `ast.dump(show_empty=...)` and its default representation
omits empty list fields. The same historical loop therefore has default-dump
SHA256 `9f3d71e360b06d6ad9353ad7dc88fa1dcec0024f8c1407f7fb3c750edd9a0cb4`
on Python 3.13, but complete-dump SHA256
`54b721b763e926e500e7f42235588ea3d6f7f9c75237981c04f0b8ceb97f5f29`
on Python 3.11 and 3.12. A source-only observation on Python 3.13 with
`show_empty=True` produces that same complete-dump fingerprint. Empty `args`,
`keywords`, and `orelse` fields account for this representation difference.

Keep the existing test identity and independent historical loop assertion.
For Python 3.13 and later, explicitly dump empty fields; earlier interpreters
already include them and retain their existing `ast.dump` call. Require one
fixed complete-structure digest across all supported interpreters. Do not
accept alternative hashes, ignore AST fields, regenerate the historical loop
from current product code, or change any product/runtime behavior.

The root's combined verification must include the complete ancestry test file,
with the other affected current-5 tests and static checks. Retain the original
Linux 3.11/3.12 failures and validate all three versions through final CI. The
source-only AST comparisons used for diagnosis execute no test or solver
bodies and are not substitute acceptance results.


## Coherent focused verification

Frozen tree `28f7164b2ea5a5af061ca2f0b07cdcb7b4e5128d`, 2,741 tracked files:
ten complete affected files on Linux/Python3.12.3 passed408 cases with zero
failure/error and one Darwin-only skip, 409unique collected, 39.026092 seconds,
one dispatch and zero retry. Complete ancestry files on Darwin/Python3.11.15
and3.13.12 independently passed the same37 cases without skips, in1.076127 and
1.010370 seconds. Do not add repeated identities across versions. Source bytes
and modes stayed unchanged; exact collection/JUnit and module origins are
retained. Ruff, compileall and diff checks pass. Original unsuccessful CI
results remain unsuccessful; new complete CI is still needed before main.
