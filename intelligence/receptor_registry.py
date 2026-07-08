"""
receptor_registry.py — SB-712 IronBraid Radiant Core

Controls which nodes may receive which signal types.  No modulator signal
reaches a node unless that node has a registered receptor for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class Receptor:
    """Describes a node's permission to receive a particular signal type."""

    node_id: str
    signal_type: str
    active: bool = True


class ReceptorRegistry:
    """
    Maintains a registry of node → signal-type permissions.

    Usage::

        reg = ReceptorRegistry()
        reg.register("vera-gate", "ARBITRATION_REQUEST")
        reg.register("phoenix-a", "RECOVERY_TRIGGER")

        assert reg.can_receive("vera-gate", "ARBITRATION_REQUEST")
        assert not reg.can_receive("phoenix-a", "ARBITRATION_REQUEST")
    """

    def __init__(self) -> None:
        # node_id → set of allowed signal types
        self._receptors: Dict[str, Set[str]] = {}
        self._log: List[str] = []

    def register(self, node_id: str, signal_type: str) -> None:
        """Allow *node_id* to receive *signal_type*."""
        self._receptors.setdefault(node_id, set()).add(signal_type)
        self._log.append(f"REGISTERED:{node_id}:{signal_type}")

    def deregister(self, node_id: str, signal_type: str) -> None:
        """Remove permission for *node_id* to receive *signal_type*."""
        if node_id in self._receptors:
            self._receptors[node_id].discard(signal_type)
            self._log.append(f"DEREGISTERED:{node_id}:{signal_type}")

    def can_receive(self, node_id: str, signal_type: str) -> bool:
        """Return True if *node_id* is permitted to receive *signal_type*."""
        return signal_type in self._receptors.get(node_id, set())

    def receptors_for(self, node_id: str) -> List[str]:
        """Return all signal types registered for *node_id*."""
        return sorted(self._receptors.get(node_id, set()))

    def nodes_for_signal(self, signal_type: str) -> List[str]:
        """Return all nodes permitted to receive *signal_type*."""
        return sorted(
            nid for nid, sigs in self._receptors.items() if signal_type in sigs
        )

    @property
    def audit_log(self) -> List[str]:
        """Return a copy of the immutable registration log."""
        return list(self._log)
