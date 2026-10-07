# Tasks

- [x] Audit current runner pass_fds and bootstrap child descriptor lifetime.
- [x] Implement native Linux close_range keep-set handoff and endpoint/alias validation.
- [x] Add new Linux default/formal descriptor gate without changing historical read-only recovery.
- [x] Implement fixtures for extra file/socket/pipe and high-FD closure; retained target/broker channels; invalid pair,
  direction/type/reserved alias; close_range errors/unsupported; original lifecycle composition.
- [x] Local focused tests, Ruff, compileall, diff check and independent source/evidence review.
- [ ] Preserve final-head three-version CI XML/logs and exact tested tree before main merge.

Local Darwin results and skips are recorded in validation.md. Actual Linux execution and final-head
full matrix remain pending; fixture implementation is not campaign or complete containment proof.
