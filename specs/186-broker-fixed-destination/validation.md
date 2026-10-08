# Validation

Implementation and independent source review are complete; submission and
final-source CI are pending. Author final reviewed XMLs are
/tmp/lunar186-destination-author-reviewed.xml (81 passed, zero skips/errors/failures)
and /tmp/lunar186-related-author-reviewed.xml (122 passed, zero skips/errors/failures).
Logs share their XML basename. Ruff, compileall and diff checks passed.

The first 80-case run had two fixture failures (legacy system proxy bypass on
Darwin and generic request constructor's IPv6 error wording). Original XML/logs
remain /tmp/lunar186-destination-author-first.xml and .log. The generic proxy
fixture explicitly disables platform bypass in its worker to exercise proxy
routing; production generic defaults are unchanged. The invalid endpoint test
checks strict helper refusal and no spawn independently of generic wording.
Final validation adds the legitimate IDN uppercase-lowercase length/port edge.
The earlier 80-pass XML and related first XML are retained independently.

Actual disposable loopback origin/proxy/redirect servers verify one original
POST, no trap request in fixed mode, generic proxy/redirect compatibility, all
3xx status/body failures (including missing/malformed Location/URI), TLS trust,
slow response deadline/exact reap, cancellation accounting and actual private
pipe broker selection. Invalid private worker policies fail before network I/O.
Root reviewed code and raw local XML and independently passed the modified
legacy stop fixture (5 cases, /tmp/lunar186-stop.xml).

Only local loopback fixtures and GitHub CI are authorized. The dedicated
broker-destination.xml workflow phase preserves raw results. Final exact-head
three-version Linux audit and prerequisite Feature183/185 acceptance remain
required before main merge. No provider or DNS/IP pinning acceptance is claimed.

After composing Feature185, root focused tests in /tmp/lunar186-root-composition.xml
passed: 191 cases, 151 passed, 40 Darwin skips, zero failure/error. Preserved log:
/tmp/lunar186-root-composition.log. This combines broker destination/stop, mq,
formal selector bindings and original-owner cancellation. Root full Ruff,
compileall, diff and workflow YAML/XML wiring checks passed on the combined source.
