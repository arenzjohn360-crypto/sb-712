"""
route_healer.py — SB-712 IronBraid Radiant Core

Detects failed or isolated nodes and re-routes data flow around them
through the braided redundancy mesh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class RouteMap:
    """Describes available routes from a node."""

    node_id: str
    routes: List[str]   # Ordered list of peer node IDs
    active: bool = True


@dataclass
class HealResult:
    """Outcome of a route healing attempt."""

    target_node: str
    healed: bool
    bypass_route: Optional[List[str]]
    message: str


class RouteHealer:
    """
    Maintains a routing mesh and provides bypass routes around failed nodes.

    Usage::

        healer = RouteHealer()
        healer.add_node("spine-core", ["ledger-primary", "vera-gate"])
        healer.add_node("ledger-primary", ["ledger-mirror-a", "ledger-mirror-b"])
        healer.mark_failed("ledger-primary")
        result = healer.heal("spine-core", destination="ledger-mirror-a")
    """

    def __init__(self) -> None:
        self._routes: Dict[str, RouteMap] = {}
        self._failed: Set[str] = set()

    def add_node(self, node_id: str, routes: List[str]) -> None:
        """Register *node_id* and its peer routes."""
        self._routes[node_id] = RouteMap(node_id=node_id, routes=list(routes))

    def mark_failed(self, node_id: str) -> None:
        """Mark *node_id* as failed and deactivate its route map."""
        self._failed.add(node_id)
        if node_id in self._routes:
            self._routes[node_id].active = False

    def mark_recovered(self, node_id: str) -> None:
        """Mark *node_id* as recovered and reactivate its route map."""
        self._failed.discard(node_id)
        if node_id in self._routes:
            self._routes[node_id].active = True

    def heal(self, source: str, destination: str) -> HealResult:
        """
        Find a bypass route from *source* to *destination* that avoids
        all currently failed nodes.

        Uses a simple breadth-first search through the mesh.

        Returns a :class:`HealResult` describing the outcome.
        """
        if source not in self._routes:
            return HealResult(
                target_node=source,
                healed=False,
                bypass_route=None,
                message=f"Source node '{source}' not in routing mesh.",
            )

        path = self._bfs(source, destination)
        if path:
            return HealResult(
                target_node=source,
                healed=True,
                bypass_route=path,
                message=f"Bypass route found: {' → '.join(path)}",
            )
        return HealResult(
            target_node=source,
            healed=False,
            bypass_route=None,
            message=(
                f"No available route from '{source}' to '{destination}'. "
                "All paths are blocked by failed nodes."
            ),
        )

    def _bfs(self, start: str, goal: str) -> Optional[List[str]]:
        """Return the first path found via BFS, or ``None``."""
        from collections import deque

        queue: deque[List[str]] = deque([[start]])
        visited: Set[str] = set()

        while queue:
            path = queue.popleft()
            node = path[-1]

            if node == goal:
                return path

            if node in visited or node in self._failed:
                continue
            visited.add(node)

            for peer in self._routes.get(node, RouteMap(node, [])).routes:
                if peer not in visited and peer not in self._failed:
                    queue.append(path + [peer])

        return None

    @property
    def failed_nodes(self) -> List[str]:
        """Return sorted list of currently failed nodes."""
        return sorted(self._failed)
