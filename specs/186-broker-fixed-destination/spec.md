# Feature 186: fixed producer broker HTTP destination

Priority P0. The producer broker already supplies a controller-owned endpoint,
headers and request body. Its isolated HTTP worker currently inherits host proxy
configuration and follows redirects, so that endpoint alone does not constrain
the effective HTTP destination. Close these two paths with an explicit direct,
no-redirect transport policy selected only by the producer broker.

The generic HTTP transport keeps its existing proxy and redirect defaults.
ControllerHttpTransport gains an optional fixed-destination mode. This mode
validates an HTTP(S) endpoint before spawn, rejects userinfo, fragments, control
characters and invalid host/port, sends no proxy configuration, and disables all
redirect following. A 3xx response remains the existing bounded HTTPError status
and body projection. A versioned private configuration policy is strictly
validated by the isolated worker; missing policy preserves legacy behavior and
unknown or malformed policy fails closed. TLS trust configuration is preserved.

Do not change original absolute deadlines, cancellation, exact worker ownership,
admission accounting, broker journal or response schemas. The generic
`ProducerBrokerConfig` retains its historical light validation and error
contract. Strict fixed-destination validation runs at native attempt admission
and again in `serve_producer_broker` before journal creation, ready signalling,
budget/nonce effects or worker spawn; the isolated worker revalidates it too.
This does not pin DNS
answers or IP addresses. The host resolver, TLS trust and original endpoint are
still trusted inputs; arbitrary kernel egress remains a separate work item.

Verification uses only local loopback origin, redirect trap and proxy trap
servers. Assert the original origin receives the expected POST and traps receive
no request in fixed mode. Verify generic proxy/redirect compatibility, invalid
endpoint/policy rejection, bounded 3xx status/body and existing deadline/reap
behavior. No credentials, provider, solver campaign, WebAgent or remote evaluator.
P2 multi-host ownership and service/scheduler work remain deferred.
