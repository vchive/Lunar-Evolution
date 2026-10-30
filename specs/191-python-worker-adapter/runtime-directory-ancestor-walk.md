# Runtime directory ancestor traversal

The unique exact `08fc60ce` Linux mixed run timed out at its unchanged outer
600-second control. Preserve that failure. Its single 120-second thread
snapshot includes runtime manifest parsing during producer staging; this is
an observation, not an end-to-end hotspot profile.

`_directory_paths` receives normalized platform Path objects through its two
internal callers. For each root label, the wanted set starts with the root
and all parents. After every directory succeeds, the wanted set contains all
of its ancestors. Walk a directory upward only until its first already-wanted
ancestor, using a parent loop to avoid eagerly constructing duplicate parents.
Do not share wanted sets between labels or retain them across calls.

Preserve every selected-file and import-directory `_path` check, including
duplicates; every unique-directory canonical encoding in its original order;
the initial declaration/import canonical bytes, cross-label byte accumulator,
exact manifest limit and final per-label sorting. The filesystem observation
and rechecks remain unchanged. No inventory truncation, cache, validation
shortcut, budget change or production authority is introduced.

Acceptance uses the previous helper as oracle for shared/overlapping ancestors,
multiple labels, deep paths, root/dot imports, Unicode/path boundaries and
exact manifest byte limits. Compare full return/errors and `_path`/canonical
event order, then run runtime/binding focused tests and static checks. A new
exact source still needs its own original-budget mixed run and full CI.

The pre-implementation independent pure comparison matched 24 scenarios and
12 byte-boundary scenarios. On the retained diagnostic manifest, 31 alternating
non-profiled measurements showed directory traversal 344.04 to 210.71 us and
full manifest parsing 954.73 to 823.71 us. This is a local observation only.
