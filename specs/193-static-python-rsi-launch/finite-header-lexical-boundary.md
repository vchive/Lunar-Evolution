# Finite configuration-header lexical boundary

This successor continues the explicitly selected configuration-review v2 reader.
PR206 remains frozen at `041e5ca2`; its source, original tests and CI have their
own gate. The existing literal-operand check covers recognized direct includes,
but the reader silently ignores alternative directive introducers and comments
before or between their tokens. Full original-byte and independent review pins
remain effective; this gap does not establish a bypass of that approval.

## Contract

Add a bounded, pure lexical refusal before the existing v2 directive inventory.
Use a separate classification view that removes backslash-LF pairs and tracks
block comments, line comments and quoted strings/characters. Only ASCII space
and tab may precede a supported direct `#` followed by the existing ordinary
identifier spelling. Pure comment and empty lines remain allowed. Reject other
noncomment content, comment-prefixed directives, comments between `#` and its
keyword, and alternative introducers such as `%:`. Do not normalize unsupported
spellings into accepted directives or evaluate macros, conditions or includes.
Treat ambiguous or unterminated lexical states as refusals. Explicitly reject
trigraph spellings rather than assuming the fixed compiler enables them; this
reader does not implement trigraph translation.

Keep original bytes, review pins, v1 behavior and successful v2 wire unchanged.
The existing inventory retains its separate backslash-LF-to-space convention;
the new classification view must not silently replace that encoding. Preserve
the supported complete-line `/* #undef ... */` convention and real multiline
comments and string macros. Comment-like characters inside quotes must not
alter comment state. If a line starts inside a block comment but its retained
inventory view would recognize a directive or disabled-undef item, reject the
conflict instead of letting commented-out features contribute to the contract.
Top-level supported disabled-undef comments retain their existing meaning.
Unsupported lexical forms fail with a fixed error code,
without running a preprocessor or resolving any input.

## Tasks and verification

- [x] Implement the pure v2 lexical refusal in configuration_review_v2.py.
- [x] Add meaningful comment-prefix, digraph, split-line, malformed lexical and
  quoted/comment-text cases, including re-signed facts at the public binder.
- [x] Independently inspect the combined code and tests before freezing.
- [x] Verify original retained header compatibility without replacing its pins.
- [x] Freeze the completed slice, then run the complete affected files once.
  Run Ruff, compileall and git diff --check; preserve the original results.
- [ ] Complete its separate final-source CI and main integration gate.

No worker/namespace mechanism, toolchain campaign, model or remote evaluator is
part of this slice. Actual immutable consumption, complete driver closure,
accepted runtime, scheduler/production CLI and copied-case acceptance remain
separate open work. All authority claims remain false.

## Frozen results and separate compatibility supplement

Commit `1fd007327262cdc23f66aed6f50f6fa93aa6ad43`, tree
`bacbfd869b49f6a97136b355ef7c36a3e4536c23`, passed all458 pytest cases in four
complete Linux3.12.3 files, including69 additions, in27.364831811s/600s with
zero failure/error/skip/retry. All2,803 source files/308directories and273 actual
module origins match before/after and Git/archive pins. Independent review
`7de57ee4…` verifies all17 original members, every JUnit key, static69 additions
and the original191 v2 keys. Ruff,compileall and diff checks pass.

The original overall batch is still failed. The same child's compatibility
harness used `facts['header_directives']` instead of the actual nested
`facts['observed_review_fields']['header_directives']`, causing KeyError after
the parser returned. Actual pytest rc0, child97 and SSH1 remain recorded;
archive `fb304d4b…` and all17 originals are preserved. The first collection also
emitted file counts because two quiet flags combined; its local output parser
failed before selection creation. Clearing project addopts produced the exact
458-key selection, with no test bodies executed in either collection.

After actual nested-field/schema inspection and independent exact-plan review
`b7d534b3…`, only the necessary pure-parser supplement ran. It passed in
1.166622257s/120s, rc0/reaped, zero retry, one parser call, zero pytest/collection.
The699 actual directives match both complete observed-facts lists. The2,803
source files/308directories,245 actual loaded origins and complete input pins,
including the failed original archive, match before/after. Supplement archive
`a3bd7be0…` is separate; no prior result or approval pin is overwritten.
These observed facts and compatibility results do not create review approval.

Evidence lives under primary ignored `validation/finite-header-lexical-20261101/`.
The code is pushed on `codex/header-directive-prefixes`; its own full CI and
main integration remain open after PR206's gate. The27,973-key inventory is
expected-only (predicted27,839pass plus the original134skip), with83focused
groups/65zero-skip gates, source group2,137 and configured sum8,953. No CI or
runtime success follows from that prediction.
