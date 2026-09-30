# Feature 156 quickstart

This feature is a local, provider-free execution primitive. The caller must already have a
`ProducerLaunchIntent` and a `preflight_passed` observation from Feature 154, plus an explicit
one-time `ProducerLaunchAttestation`.

Conceptual call:

```text
receipt = run_producer_process(
    workspace,
    intent=intent,
    attestation=attestation,
    expected_run_id=run_id,
    expected_parent_task_id=parent_task_id,
    expected_task_id=task_id,
    cancelled=parent_control.is_cancelled,
)
```

The implementation performs this sequence:

```text
revalidate preflight and exact executable identity
  -> atomically consume attestation nonce
  -> Popen(argv, shell=False, start_new_session=True, close_fds=True)
  -> verify PID/PGID and persist registration receipt
  -> release the child work gate
  -> drain bounded stdout/stderr under one monotonic deadline
  -> owner-checked cleanup and stable no-follow envelope read
  -> persist terminal execution receipt
```

`completed` means the process exited successfully, cleanup is verified, the bounded envelope read
is stable, and all observed request/output limits hold. `cancelled` means the caller's cancellation
callback was observed while the child was registered and owner-checked cleanup completed. `failed`
means a deterministic local violation or nonzero exit was observed. `unknown` or `recovery_required` means the controller
cannot prove process, cleanup, output, or receipt state; the caller must inspect the exact receipt
and may not relaunch automatically.

Local fixtures should include a gate-aware executable, a large-output executable, a timeout
executable, and an executable that replaces or symlinks its envelope. The quickstart must not
start a provider, evaluator, external campaign, or publication transaction.
