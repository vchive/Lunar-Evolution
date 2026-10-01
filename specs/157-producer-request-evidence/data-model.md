# Feature 157 data model

```text
ProducerRequestEvent
  sequence / request_id / status / duration_ms

ProducerRequestEvidence
  schema_version / protocol
  launch_id / journal_id / run_id / parent_task_id / task_id
  intent_sha256
  request_timeout_seconds / max_requests
  observed_request_count / coverage / clock_source
  events[]
  evidence_sha256
```

`status` is one of `completed`, `failed`, `cancelled`, or `timed_out`. `coverage` is `complete`
or `partial`; `clock_source` is fixed to `producer_sdk_monotonic`. The protocol bounds the JSON to
256 KiB and at most 16,384 events. Event sequence numbers are contiguous from one and request IDs
are unique. Self-digests are SHA-256 over canonical JSON with `evidence_sha256` omitted.

`ProducerRequestEvidenceAssessment` contains a fixed status and `enforcement=cooperative_declaration`.
It is diagnostic evidence only and cannot be substituted for a controller-owned timeout receipt.

For the native broker path, the host journal identity and admitted-count coverage are projected
into the Feature 156 formal `ProducerExecutionReceipt`; the process-only terminal and this DTO
remain separate records. Feature 153 accepts the receipt digest as an optional publication-journal
link and checks `broker_coverage=brokered_requests_only` before staging. This records the observed
broker boundary without claiming that requests bypassing the broker were impossible or that a
post-crash transport was recovered.
