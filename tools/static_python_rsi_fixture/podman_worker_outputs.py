"""Finite readback of the original worker output role, without custody authority.

The caller retains the original role FD and supplies its copied output pins.
Reuse the inventory walk so output names, held objects and bytes are checked
together. This neither acquires an owner nor establishes writer exclusion,
protected output transitions, descendant drain or runtime acceptance.
"""

from __future__ import annotations


def verify_worker_outputs(output_fd, records, checkpoint):
    """Verify the complete original output tree using the output size bound.

    The original descriptor is borrowed and remains open. The returned value is
    the shared inventory summary; no output receipt or authority is created.
    Imports stay local because the lifetime owner calls this helper at readback.
    """
    from tools.static_python_rsi_fixture.execution_backend import MAX_OUTPUT_BYTES
    from tools.static_python_rsi_fixture.podman_vfs_lifetime import _observe_worker_inventory

    return _observe_worker_inventory(output_fd, records, checkpoint, maximum=MAX_OUTPUT_BYTES)
