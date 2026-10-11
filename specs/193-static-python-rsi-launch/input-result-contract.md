# F04 input/result cross-pin contract

This provider-free continuation joins caller-owned digests from the F03 runtime
startup observation with the F04 two-grant input-read report. The schema is
`lunar-static-python-input-result-v1`. It checks startup, build-closure,
installation binding, launch-intent, manifest, report, request and memory pins,
the fixed report schema, input sizes and computation `285`. Five capability
claims remain false.

`parse_static_python_input_result` accepts only bounded canonical JSON bytes and
returns an immutable digest/size DTO. It never opens a file, reads `/proc`,
starts a process, invokes a producer/evaluator, or creates a solver result
envelope. Matching hashes and sizes are only a cross-pin comparison, not proof
of original file ownership, actual input consumption, runtime startup, memory
usefulness, output validity or admission.

Duplicate keys, non-canonical JSON, non-finite values, unsupported types, pin
drift, changed report schema, size/computation drift and true claims are fixed
refusals. The wire contains no raw request/memory bytes and public errors do not
retain malformed caller input. Live marker-to-file authority, same-attempt
consumption and producer result generation remain later F04/F05 acceptance work.
