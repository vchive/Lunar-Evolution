# Producer broker HTTP destination

The producer broker selects a controller-owned direct HTTP policy. It validates
the configured endpoint before starting its isolated worker, bypasses host
environment/system proxies and refuses HTTP redirects. The original endpoint
receives the existing POST; a redirect response is retained as a bounded HTTP
failure with its original status and body. A malformed or unsupported private
policy fails closed. Existing admission deadlines, exact worker cancellation,
request accounting and broker journals retain their original behavior.

Generic model HTTP callers keep their existing proxy and redirect defaults.
TLS trust configuration is preserved in both modes. This policy constrains HTTP
redirect/proxy routing; it does not pin DNS answers, isolate the trusted host
resolver or certify arbitrary kernel egress. Local loopback acceptance is
separate from real provider or production campaign acceptance.
