# Plan

Continue from Feature 183 source 5561c30. Its independent Linux acceptance is
tracked separately; this feature must not borrow earlier source CI evidence.

1. Author owns http_transport.py, controller_http_transport.py,
   producer_broker_ipc.py and a new focused local loopback test module.
2. Root owns SDD, dedicated workflow result preservation, documentation and
   HANDOFF. Independent review checks effective destination behavior and legacy
   compatibility before submission.
3. Keep private worker wire backward compatible. Freeze one recognized versioned
   fixed direct policy and reject unexpected fields/values. Preserve TLS trust.
4. Run focused tests, Ruff, compileall and git diff --check. Preserve original
   failed results. Final exact-source Python 3.11/3.12/3.13 Linux CI and raw audit
   precede main merge; prerequisite Feature 183 acceptance remains separate.

Do not broaden this slice into DNS/IP pinning, runtime delivery or kernel filters.
