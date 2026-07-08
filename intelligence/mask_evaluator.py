"""
mask_evaluator.py — SB-712 IronBraid Radiant Core

Scores the risk level of an action or data item relative to protected
assets (Spine, Ledger, Phoenix, VERA).  High-scoring items are escalated
to the VERA gate before execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

# Protected asset identifiers — anything that touches these gets a risk bump.
PROTECTED_ASSETS = {"spine", "ledger", "phoenix", "vera", "checkpoint", "root_manifest"}


@dataclass
class MaskResult:
    """Risk evaluation produced by the MaskEvaluator."""

    target: str
    risk_score: float   # 0.0 (safe) → 1.0 (maximum risk)
    risk_level: str     # LOW | MEDIUM | HIGH | CRITICAL
    flags: List[str]
    escalate_to_vera: bool


def _level(score: float) -> str:
    if score < 0.25:
        return "LOW"
    if score < 0.5:
        return "MEDIUM"
    if score < 0.75:
        return "HIGH"
    return "CRITICAL"


class MaskEvaluator:
    """
    Evaluates whether an action targeting *target* should be blocked or
    escalated based on proximity to protected Spine assets.

    Usage::

        evaluator = MaskEvaluator()
        result = evaluator.evaluate("ledger/ledger.jsonl", action="write")
    """

    PROTECTED_BASE_SCORE: float = 0.6
    WRITE_PENALTY: float = 0.2
    UNVERIFIED_PENALTY: float = 0.15

    def evaluate(
        self,
        target: str,
        action: str = "read",
        state: str = "VERIFIED",
    ) -> MaskResult:
        """
        Return a :class:`MaskResult` for *target* under *action*.

        Parameters
        ----------
        target:
            Path or identifier of the resource being accessed.
        action:
            One of ``read``, ``write``, ``delete``, ``execute``.
        state:
            Current trust state of the data or node (e.g. ``UNVERIFIED``).
        """
        flags: List[str] = []
        score = 0.0

        # Check proximity to protected assets.
        target_lower = target.lower()
        for asset in PROTECTED_ASSETS:
            if asset in target_lower:
                score += self.PROTECTED_BASE_SCORE
                flags.append(f"PROTECTED_ASSET:{asset}")
                break

        # Write/delete/execute to protected areas are riskier.
        if action in {"write", "delete", "execute"}:
            score += self.WRITE_PENALTY
            flags.append(f"MUTATING_ACTION:{action.upper()}")

        # Unverified data touching anything is a risk.
        if state in {"UNVERIFIED", "QUARANTINED", "FAILED"}:
            score += self.UNVERIFIED_PENALTY
            flags.append(f"UNTRUSTED_STATE:{state}")

        score = min(1.0, score)
        level = _level(score)
        escalate = score >= 0.5

        return MaskResult(
            target=target,
            risk_score=round(score, 4),
            risk_level=level,
            flags=flags,
            escalate_to_vera=escalate,
        )
