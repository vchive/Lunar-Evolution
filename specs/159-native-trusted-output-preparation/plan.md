# Implementation plan

1. Reuse native terminal recovery as the process authority check and require successful cleanup.
2. Derive output paths exclusively from the launch intent. Apply the existing bounded, no-follow
   envelope reader, then reread exact bytes and compare the observed device, inode, timestamps,
   size and SHA-256 before parsing.
3. Compare envelope identity and declared requests to the launch intent. Reuse Features 150-152
   to verify explicit source groups, project drafts and build the immutable admission plan.
4. Keep this a read-only supporting API. Add provider-free positive and tamper tests; defer
   durable same-deadline output receipt and host-observed broker evidence to the native runner
   integration.
