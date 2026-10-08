# Inert CPython source fixtures

These three `.source` files preserve exact bytes from CPython commit
`1cbe481834751b0125e006042ffbd8cd5eaec8a8` (`v3.13.12`). They are data for
whole-file digest and source-transformation tests. Tests read or parse these
bytes; they never execute the complete upstream files or build CPython.
The full upstream license is retained in `LICENSE`; byte provenance is in
`provenance.json`. Copied snippets in the preparation module retain this same
upstream license.

This Git source review is distinct from acquiring or verifying the advertised
python.org release archive. No archive signature, toolchain, generated frozen
header, static ELF, startup or production admission is established here.
Only individually extracted fixed refusal methods may be compiled and called
with inert fake objects to verify that they raise before callbacks.
