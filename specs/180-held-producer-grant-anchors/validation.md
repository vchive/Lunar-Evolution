# Validation

Standalone final focused suite: 95 cases, all passed, zero failures/errors/skips. Raw XML
`/tmp/lunar180-grant-anchors-final-focused.xml`, SHA256
`4623ff1b2cfb230162952075104be7c975b89c20d698456a6d552f5d4a233d39`.
First 89-case suite is retained and included in this 95, not added to it.

Existing policy compatibility: 5 cases, 4 passed/1 platform skip, zero failures/errors.
Raw XML `/tmp/lunar180-policy-compatibility.xml`, SHA256
`60d0fa93d09d085522be038bc3ab988c872809e2f16cad60dbf234452c7cc7c1`.
Ruff, compileall, diff check, workflow XML preservation and 693 public exports passed.

Independent review passed after narrowing FD-lifetime prose to its actual device/inode/
type guarantee. A separate 95-case inert run passed; it overlaps the first suite and is not
added to the count. Review `/tmp/lunar180-independent-review.md`; probe evidence
`/tmp/lunar180-independent-probes.json` explicitly demonstrates same-object reopen is
outside the borrowed-lifetime contract. Cleanup OS failures are refusal/best effort.

Exact final-head three-version CI/merge remain pending at this source checkpoint.
Darwin host path/FD fixtures are evidence for this standalone owner;
they are not Linux Landlock, native producer, Python runtime, or campaign acceptance.
No formal control or selector changes are made. Later CI outcomes are recorded on the PR
and ignored report, without modifying its tested head merely to update source status.
