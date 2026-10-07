# Validation

Use explicit temporary roots and inert bytes even for interpreter/loader roles. Verify canonical
roundtrip, independent tree/v1/target pins, all regular files and empty directory membership.
Compare Feature171's intentional unlisted acceptance with this API's refusal.

Negative cases: unlisted module/hook/resource/native/bytecode, missing declared file, added/removed
empty directory, same-content file/directory replacement, mode/time/root/ancestor drift, symlink,
hardlink, FIFO/socket, overlap/alias, unknown JSON/duplicate keys, malformed graph and digests,
entry/depth/file/total/schema bounds, file-read/scandir mutation, whole-snapshot drift, and FD cleanup
after errors, KeyboardInterrupt and SystemExit. Forbid subprocess/import/write/chmod during checks.

Run new and unchanged inventory focused tests, Ruff, compileall and git diff --check. Record actual
XML counts, first failures, skipped cases and unproved archive/loader/sealing boundaries here.

Local result, 2026-10-08, Darwin/Python 3.11.15:

```bash
PYTHONPATH=src /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest -q \
  tests/test_producer_python_runtime_tree.py tests/test_producer_python_runtime.py \
  --basetemp=/tmp/lunar-runtime-tree-bounded-proof-final \
  --junitxml=/tmp/lunar-runtime-tree-bounded-proof-final.xml
/Users/liminghan/miniforge3/bin/ruff check \
  src/lunar_evolution/producer_python_runtime_tree.py tests/test_producer_python_runtime_tree.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/python -m compileall -q \
  src/lunar_evolution/producer_python_runtime_tree.py tests/test_producer_python_runtime_tree.py
git diff --check
```

Final XML: **322 tests, 0 failures, 0 errors, 0 skipped, 8.727 seconds**. This is 112 new closed-tree
tests and 210 unchanged Feature171 tests. Ruff, compileall and diff check passed. Portable/venv
roundtrips, all declared role drift, empty directory membership, unlisted file refusals, canonical
parser limits and detached graph binding passed. Read/scandir OSError, KeyboardInterrupt and
SystemExit tests show no retained descriptor; local effect gates show parsing performs no filesystem
reads and build/verify perform no launch, import, write or chmod.

Root's subsequent mutation audit identified a real bounded-validation defect: verify serialized
an object.__setattr__-mutated tree before checking its collection type/count, and embedded v1
serialization similarly preceded its immutable shape check. A custom iterable could execute a
callback or remain unbounded. The preserved reproducer XML is
`/tmp/lunar-runtime-tree-mutation-first.xml` (one test, one failure, no errors/skips, 0.185 seconds).
The fix validates exact tuple/count/nested DTO/scalar shapes before any serialization or unchanged
v1 validation. It also bounds ancestor pin metadata (8320 per root, 10240 aggregate) and relative
file/import depth. The 25 added cases reject custom Sequence length/index/iteration callbacks,
oversized immutable tuples and aggregate pins before serialization, and mutated nested fields
before hash/set operations. Feature171 source/wire behavior remains unchanged.

The original pre-audit success XML is retained at `/tmp/lunar-runtime-tree-final.xml`: 297 tests,
0 failures/errors/skips, 7.179 seconds. The initial independent read-only cross-review also ran
the unchanged-v1/new-tree pair: **297 tests, 0
failures/errors/skips, 7.357 seconds**, XML
`/tmp/lunar-feature177-cross-review-20261008.xml`, with Ruff and compileall passing. Those earlier
results did not cover the forced-collection mutation defect corrected above. An inert mutation
after the final snapshot's root-chain
close demonstrates the documented tail boundary: build can return its earlier observation, and a
subsequent verify refuses the new unlisted file. This is why runtime_load_protection remains false
and immutable delivery is required before a future runtime launch claim.

The initial run exposed two test-fixture issues. Its monkeypatch leaked the import gate into pytest
failure reporting, so that run produced no usable XML. The first preserved failure is
`/tmp/lunar-runtime-tree-first-failure.xml` (12 collected/executed before `-x`, one failure):
`native.so` collided with the fixture's already-declared extension and was renamed
`unlisted-native.so`. `/tmp/lunar-runtime-tree-recovered.xml` records 87 tests with one failure:
monkeypatch's own import of inspect occurred while registering additional patches. Separate local
patch contexts now install import gates last. These were harness fixes; neither required weakening
runtime checks. The socket fixture binds a short relative path to fit Darwin's Unix socket limit;
permission fixtures restore their original modes before cleanup.

Full repository regression, Ubuntu CI and main merge are owned by root integration and are not
established by this focused result. No interpreter, producer, OpenEvolve/Shinka campaign, model or
evaluator was executed. Archive members, loader dependency closure, atomic snapshots, sealed runtime
delivery and execution binding remain unproved and explicitly false in the API.
