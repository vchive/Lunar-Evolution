# Data model

No new durable DTO or control wire. The new implementation_version selects the IPC
control capability; privatev2 still carries original graph/leaf grants and fixed roles.
All existing attestation/deadline/registration/handoff/terminal/broker/receipt hashes and
schemas keep their original meaning. Historical records gain no new execution rights.

Only disposable test parents retain private IPC IDs and original bytes/state; these
fixtures are not producer configuration, durable ownership or publication authority.
