# F04 provider-free composition replay

`tests/test_static_python_input_result_composition.py` joins the already
implemented input and report comparators around one create-only
`NativeRSIInputDescriptor`:

1. Stage a canonical request and memory snapshot in a temporary workspace.
2. Derive the exact two protected-file grant proposals from that descriptor and
   verify their retained material bytes equal the original request and memory.
3. Run the source-level fixed input-report fixture with `open` routed only to
   those two retained grant bytes. The test asserts the exact two paths and
   bounded read sizes.
4. Compare the report against the original marker and grant bytes, then join its
   report/request/memory digests and sizes through
   `parse_static_python_input_result`.
5. Refuse a foreign marker, changed request or memory bytes, and a request digest
   changed after report comparison.

This is provider-free plumbing and replay coverage only. The test uses a Python
source fixture and an in-memory grant reader; it does not bind or launch the
sealed target, observe original grant FDs, prove that CPython consumed the files,
produce a solver result, or establish publication/recovery authority. Synthetic
startup/build/intent pins only exercise the existing DTO's cross-pin gate. All
five capability claims stay false, and production admission remains disabled.

F04 remains open until an accepted sealed runtime consumes the original
marker-bound request and memory grants during the same owned launch, emits a
bounded result attributable to that attempt, and the original verifier,
publication and recovery chain accepts the evidence.
