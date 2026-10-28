# Original native observation handoff

Status: finite software passthrough; its 30 focused cases passed in both the
`7fca9111` and `7628e971` concentrated Linux batches. This does
not accept a build/runtime or enable native CLI, production admission or online
publication.

The existing one-shot scheduler gains an explicit optional
`python_handoff_after_native_execution(NativeTrustedProducerRun)` supplier. Its
argument contains the exact attempt, receipt and output just produced by this
invocation, after strict receipt/output preparation and before handoff or
publication. The historical two-argument `python_handoff_after_execution` stays
unchanged. Selecting both suppliers, or selecting the new supplier without an
original live sink request, refuses before process execution.

The new supplier requires the current attempt's original bound private-pipe
observation. The scheduler retains its canonical bytes/digest, installation,
image device/inode, target PID and manifest binding, the original request pin,
and the complete receipt/output evidence. Original object replacement or field
drift before/after the supplier and final handoff read refuses. No observation
is rediscovered from a pathname or reconstructed from a detached descriptor.

Native success/outcome/private-preparation wrappers, the immutable RSI context,
its fingerprint projection and its existing late prepared join explicitly carry
this alternative. The reserved BRS path reuses its original owner/claims,
preparation exchange and finite policy graph. There is no second scheduler,
registry, launch protocol, retry or added publication authority.

The supplier still returns the original create-only handoff sidecar and file
pin. Prepared observers and final evidence checks retain their existing order.
Startup facts do not supply terminal, broker, computation or pycache evidence,
and are never converted into the legacy runtime-observation DTO. Expanded
adapter/export/admission policy and an accepted-runtime authority root remain
separate follow-up work. Public CLI continues to refuse native execution.

Focused coverage must exercise exact original objects, both supplier forms,
dual-configuration refusal, missing sink/observation, raw/binding and nested
receipt/output drift, configured supplier drift and reserved-path forwarding.
Tests are prepared for the parent's consolidated batch, not run separately.
