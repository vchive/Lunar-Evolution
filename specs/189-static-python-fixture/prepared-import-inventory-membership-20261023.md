# Feature 189 — prepared import target inventory projection (2026-10-23)

The nine pinned prepared Python source observations contain 28 import edges and
21 distinct target names. The focused profile test projects those exact targets
onto the synthetic descriptor's frozen and builtin name inventories:

- 16 targets have an exact-name entry in one of those inventories.
- Five targets are absent by exact name: `importlib.metadata`,
  `importlib.readers`, `nt`, `tokenize`, and `winreg`.

This is only a finite metadata comparison. It does not establish whether any
edge executes, whether a conditional or platform branch is reachable, whether
an absent target is refused, or whether aliases/other import mechanisms resolve
to those names. In particular, `_tokenize` being declared does not count as an
exact `_tokenize` match for the observed `tokenize` edge. The source observer's
unsupported sites remain unchanged, and all production/admission claims remain
false.
