"""
ava_coordinator.py — SB-712 IronBraid Radiant Core

AVA (Adaptive Verification Architecture) coordinates subsystems under
owner authority.  It routes tasks through VERA arbitration, delegates to
specialist nodes, and escalates irreversible or high-risk events to the
owner pager.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Task:
    """A unit of work submitted to AVA."""

    task_id: str
    action: str
    target: str
    payload: Optional[Dict] = None
    submitted_at: float = field(default_factory=time.time)


@dataclass
class TaskResult:
    """Outcome of a task processed by AVA."""

    task_id: str
    status: str  # APPROVED | DENIED | ESCALATED | COMPLETED | FAILED
    message: str
    processed_at: float = field(default_factory=time.time)


class AVACoordinator:
    """
    Coordinates subsystem workflows under the SB-712 doctrine.

    AVA receives tasks, checks each through VERA, and either
    dispatches them to registered handlers or escalates them.

    Usage::

        from intelligence.vera_gate import VERAGate, CertificationBundle

        gate = VERAGate()
        ava = AVACoordinator(vera_gate=gate)

        def my_handler(task: Task) -> TaskResult:
            return TaskResult(task.task_id, "COMPLETED", "Done.")

        ava.register_handler("write", my_handler)
        bundle = CertificationBundle(hash_check=True, validation_pass=True,
                                     certification_mark=True)
        result = ava.submit(Task("T1", "write", "data/active_brics/f.bric"),
                            bundle=bundle)
    """

    HIGH_RISK_ACTIONS = {"delete", "overwrite", "format", "shutdown", "restore"}

    def __init__(self, vera_gate=None, owner_pager: Optional[Callable] = None) -> None:
        from intelligence.vera_gate import VERAGate

        self.vera_gate = vera_gate or VERAGate()
        self.owner_pager = owner_pager
        self._handlers: Dict[str, Callable[[Task], TaskResult]] = {}
        self.history: List[TaskResult] = []

    def register_handler(self, action: str, handler: Callable[[Task], TaskResult]) -> None:
        """Register a callable *handler* for tasks with the given *action*."""
        self._handlers[action] = handler

    def submit(self, task: Task, bundle=None) -> TaskResult:
        """
        Submit *task* for processing.

        If *bundle* is omitted, a default all-False bundle is used (will be
        denied by VERA).
        """
        from intelligence.vera_gate import CertificationBundle

        bundle = bundle or CertificationBundle()

        # Escalate irreversible/high-risk actions before VERA check.
        if task.action in self.HIGH_RISK_ACTIONS and self.owner_pager:
            self.owner_pager(task)
            result = TaskResult(task.task_id, "ESCALATED",
                                f"Action '{task.action}' escalated to owner.")
            self.history.append(result)
            return result

        decision = self.vera_gate.evaluate(task.action, task.target, bundle)

        if not decision.approved:
            result = TaskResult(task.task_id, "DENIED", decision.reason)
            self.history.append(result)
            return result

        handler = self._handlers.get(task.action)
        if handler is None:
            result = TaskResult(task.task_id, "FAILED",
                                f"No handler registered for action '{task.action}'.")
            self.history.append(result)
            return result

        try:
            result = handler(task)
        except Exception as exc:  # noqa: BLE001
            result = TaskResult(task.task_id, "FAILED", str(exc))

        self.history.append(result)
        return result
