# Finite compiler-language and configuration-header inputs

This continuation tightens the existing actual dependency-build preflight. It
does not change the runner, backend, independent review authority or successful
recipe/report bytes, and does not establish complete configured-driver closure.

## Contract

The actual dependency command graph accepts compilation only from a declared
`@source/` reference ending in `.c`, as emitted by the fixed recipe generators.
Other driver-selected languages or preprocessed/object input suffixes refuse
before runner preflight or workspace creation. Keep the generic dependency
capture generator and unselected execution APIs unchanged.

The explicitly selected configuration-review v2 header reader accepts only the
supported literal include spelling with a canonical relative operand. Reject
absolute paths, empty or dot path components, backslashes, control bytes, macro
operands and extra expressions. Inspect the already retained real reviewed
header first and preserve any supported original lexical comment shape.
Preserve the exact original directive inventory; this parser does not evaluate
conditional C directives or prove which header a compiler will select. The v1
header reader keeps its separate existing contract.

Do not infer include search order from sets. Any additional order check must
respect the already reviewed source-owned v2 adaptation: its generated include
order intentionally differs from stock Make variables. This batch must not
silently replace that adaptation or claim that the existing independent
manifest's complete argv/order binding is absent.

## Tasks and validation

- [x] Require `.c` at the actual command graph and add valid v3/v4 graph tests
  plus non-C language refusals before execution.
- [x] Review retained real header include spelling, implement the finite v2
  operand gate and test literal, conditional and malformed input boundaries.
- [ ] Review both changes together, then run the complete affected files once
  on frozen Linux source, preserving source/module origins and original results.
- [ ] Update focused inventory as needed; run Ruff, compileall and diff checks.
- [ ] Complete final-source CI/source review and main integration separately.

No compiler campaign, target interpreter, model or remote evaluator is part of
this development batch. Existing tests may compile their inert local helper.
Immutable input consumption, directory stability, external-writer exclusion,
accepted image/material ownership, sealed startup and production CLI/local-case
acceptance remain open; every existing custody/runtime/admission/publication
claim remains false.

## Retained header spelling and include-order decision

The original reviewed packet's complete `pyconfig.h` is58,752bytes, SHA256
`c300e7c60168ea35f2761aa4b1876bd0d9f306f1236297dc5a6e767126d862f3`.
It matches the retained eight-output pin and contains zero include directives.
There is therefore no original include-tail comment spelling requiring an
exception. This read-only observation creates no manifest or approval pin.

V2 accepts exactly one `<relative>` or `"relative"` operand. Its path uses only
ASCII letters, digits, underscore, slash, dot, plus and minus; every component
must be nonempty and different from `.` or `..`. There is no required filename
suffix. Only ASCII space/tab may surround the operand; trailing comments and
expressions are explicitly unsupported. Split logical header lines only at LF
after the existing continuation normalization, then check the original raw
directive operand before inventory whitespace normalization. Non-LF control
separators and Unicode whitespace must not disappear through `splitlines()` or
generic `strip()`. Preserve valid original directive inventory text and the
unchanged v1 reader contract; this gate does not preprocess or resolve a header.

The retained stock Makefile has
`BASECPPFLAGS = -IObjects -IInclude -IPython`. The reviewed source-owned v2
compile graph instead begins with configuration, Include, Include/internal,
Include/internal/mimalloc, Objects and Python roots, followed by finite runtime
roots. Both retained original graphs show this exact order: OpenEvolve stage
SHA256`2d1dd8d0ab81521faf2a58e9de0bd6b4bc3dd1e8ff920788772e76d376b4aede`
and Shinka stage
SHA256`23c56c396837d25c909198779067838ef70cb8f391ff194b9b4cf7445b6641c4`,
matching the separately recorded delegated review.

Do not add an ordered-equality requirement against stock Make in this batch.
The existing independently pinned `recipe_semantics` retains complete actual
role-flag arrays, and `concrete_stages_sha256` binds every original command
vector including its order. Reordering actual argv without the reviewed facts
fails those existing comparisons. A set-based Make coverage check does not
itself prove order equivalence, but requiring stock order would contradict the
already reviewed source-owned adaptation rather than add an independent
authority boundary. Any future new include-order policy needs a separately
specified adaptation/review; it must not silently invalidate these original
approved graph bytes or claim complete configured-driver closure.
