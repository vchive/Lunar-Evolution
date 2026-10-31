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
- [ ] Verify original retained header compatibility without replacing its pins.
- [ ] Freeze the completed slice, then run the complete affected files once.
  Run Ruff, compileall and git diff --check; preserve the original results.
- [ ] Complete its separate final-source CI and main integration gate.

No worker/namespace mechanism, toolchain campaign, model or remote evaluator is
part of this slice. Actual immutable consumption, complete driver closure,
accepted runtime, scheduler/production CLI and copied-case acceptance remain
separate open work. All authority claims remain false.
