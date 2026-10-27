# Feature 197 — Tasks

## Slice A

- [x] Record the local existing evidence boundary and the exact HMAC wire before coding.
- [x] Add private per-worker key and trusted fixed registry objects.
- [x] Add exact original-context binding and canonical bounded wire parsing.
- [x] Implement real HMAC-SHA256 signing and constant-time verification.
- [x] Author failure tests for unknown/revoked/key/host/boot/context/receipt/MAC mismatch.
- [x] Author secret-redaction, strict-wire and explicit stateless-replay tests.
- [x] Root: focused tests, Ruff, compileall and `git diff --check`.

## Local authoritative assignment slice

- [x] Specify and implement original claim/assignment/challenge binding and atomic consumption.
- [x] Fix generation at 1; reject duplicate reservation and late receipts without changing native claim ownership.
- [x] Preserve started/unknown gates through interruption and ledger reopen.
- [ ] Independently verify simultaneous competing owners and interruption behavior.

## Separate acceptance, not established by this feature's first slice

- [ ] Real cross-host secret provisioning, trusted-wrapper isolation and authenticated receipts.
- [ ] Actual remote lifecycle/cleanup observations and partition behavior.
- [ ] Any future multiple-controller ownership design and acceptance.

Remote evaluators, background services and a default microservice architecture are
outside the current requested delivery. Slice A does not close any task above by
merely producing or verifying a detached signature.
