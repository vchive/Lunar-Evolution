"""Explicit child gateway selector; the original producer gateway remains fixed."""

from .rsi_producer_gateway import resolve_python_producer_episode_gateway

__all__ = ["resolve_python_producer_episode_gateway"]
