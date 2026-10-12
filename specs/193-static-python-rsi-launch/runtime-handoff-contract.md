# F05 runtime/post-execution handoff contract

This provider-free continuation defines the bounded
`lunar-static-python-runtime-handoff-v1` cross-pin projection. It joins the
startup, input/result, terminal, runtime binding, result and publication-intent
digests with one request budget and deadline projection.

`parse_static_python_runtime_handoff` accepts only canonical JSON bytes and
returns an immutable digest/state DTO. It performs no filesystem or process
I/O, does not invoke a producer/evaluator, and does not publish or recover a
run. Terminal state, cleanup state, publication state, request count, timeout
and deadline must match independently retained pins. A non-completed terminal
cannot claim a prepared publication. All six capability claims remain false.

Parsing also requires separate expected terminal, cleanup and publication
states; matching digest labels alone cannot establish those states. Counts and
sizes require exact integers (booleans refuse); time values require finite
positive exact int/float values (strings and booleans refuse). Comparison must
preserve integer precision and fractional deadlines. Prepared publication is
allowed only for completed terminal plus known cleanup; unknown cleanup remains
inspectable with rejected/unknown publication.

Matching detached hashes are consistency evidence only. They do not prove a
real CPython image, process owner, input authority, result validity, evaluator
authenticity, publication eligibility or durable recovery. The live F05 stage
still requires actual sealed launch, terminal/broker/material evidence,
authoritative result handoff and controller publication/recovery integration.
