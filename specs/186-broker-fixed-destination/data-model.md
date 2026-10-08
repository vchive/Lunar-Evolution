# Private transport policy

The legacy worker configuration retains exactly proxies, proxy_source and trust.
Fixed mode adds policy=fixed-direct-no-redirect-v1 and requires proxy_source=direct
and an empty proxies mapping. Unknown policy versions, unexpected fields and
inconsistent proxy configuration are invalid; they never select generic behavior.
TLS trust retains the existing bounded SSL_CERT_FILE/SSL_CERT_DIR projection.

No public receipt, request admission, broker journal or result fields change.
The existing HTTPError projection carries the original 3xx status and bounded
body. Private policy fields are controller-selected and are not producer input.
