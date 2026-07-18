"""
AVA — Business Operator Layer
==============================

AVA is the business operator that activates inside a verified business room.

Core law:
    AVA may assist only inside a verified business room, using approved memory,
    approved bricks, and bounded actions.

Operating flow:
    ROOM VERIFIED BY CLIPPERX
        ↓
    AVA READS APPROVED CONTEXT
        ↓
    AVA ROUTES TASK TO APPROVED CLIP BRICK
        ↓
    SHIELDBRICK CHECKS RISK
        ↓
    VERA / HUMAN APPROVAL WHEN NEEDED
        ↓
    LEDGER RECORDS ACTION

AVA only operates when the room state is LIVE_ROOM and SHIELDBRICK has not
issued a RED block.  Every decision is returned as an AVADecision record so
the caller can ledger it and chain it into the braided topology.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid

from .prevention import PreventionRegistry


# ---------------------------------------------------------------------------
# AVA states
# ---------------------------------------------------------------------------

class AVAState(Enum):
    OFFLINE = "OFFLINE"                     # No verified room at all.
    ROOM_LOCKED = "ROOM_LOCKED"             # CLIPPERX has not opened the room.
    READY = "READY"                         # Room live; AVA can draft.
    DRAFTING = "DRAFTING"                   # AVA is preparing an output.
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED" # Sensitive action; must be approved.
    LEDGERED = "LEDGERED"                   # Session / action recorded.
    MEMORY_UPDATED = "MEMORY_UPDATED"       # Approved summary written to Memory Chip.


# ---------------------------------------------------------------------------
# AVA decision record
# ---------------------------------------------------------------------------

@dataclass
class AVADecision:
    session_id: str
    brick_id: str
    state: AVAState
    can_draft: bool
    approval_required: bool
    routed_brick: Optional[str]
    draft_type: str
    blocked_reason: Optional[str]
    notes: List[str]
    prevention_rules_checked: List[str]
    metadata: Dict[str, Any]
    decided_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Brick routing table
# ---------------------------------------------------------------------------

# Maps keyword fragments (lower-case) → target Clip Brick name.
BRICK_ROUTES: Dict[str, str] = {
    "music":       "music_brick",
    "song":        "music_brick",
    "release":     "music_brick",
    "merch":       "content_brick",
    "sales":       "sales_brick",
    "lead":        "sales_brick",
    "offer":       "sales_brick",
    "close":       "sales_brick",
    "brand":       "brand_brick",
    "logo":        "brand_brick",
    "caption":     "content_brick",
    "post":        "content_brick",
    "booking":     "booking_brick",
    "appointment": "booking_brick",
    "support":     "support_brick",
    "customer":    "support_brick",
    "reply":       "support_brick",
    "ledger":      "ledger_brick",
    "verify":      "vera_brick",
    "plan":        "strategy_brick",
    "strategy":    "strategy_brick",
    "roadmap":     "strategy_brick",
    "finance":     "finance_brick",
    "payment":     "finance_brick",
    "invoice":     "finance_brick",
}

# Draft-type detection keywords.
_CONTENT_WORDS: Set[str] = {"caption", "post", "facebook", "social", "content"}
_SALES_WORDS:   Set[str] = {"sales", "lead", "offer", "close", "pitch"}
_PLAN_WORDS:    Set[str] = {"plan", "strategy", "roadmap"}
_REPLY_WORDS:   Set[str] = {"reply", "customer", "support", "response"}
_MUSIC_WORDS:   Set[str] = {"music", "song", "release", "track", "album"}


# ---------------------------------------------------------------------------
# AVASession
# ---------------------------------------------------------------------------

class AVASession:
    """
    AVA business operator session.

    Each call to ``inspect()`` evaluates one user request inside the
    business room and returns a fully-populated AVADecision.

    Parameters
    ----------
    prevention_registry:
        The shared PreventionRegistry.  AVA checks it before drafting so that
        blocked incident patterns halt the action before it proceeds.
    brick_id:
        Identifier for this AVA brick instance (default ``"AVABRICK-001"``).
    """

    def __init__(
        self,
        prevention_registry: PreventionRegistry,
        brick_id: str = "AVABRICK-001",
    ) -> None:
        self.prevention_registry = prevention_registry
        self.brick_id = brick_id
        self._decisions: List[AVADecision] = []

    # ------------------------------------------------------------------
    # Primary entry-point
    # ------------------------------------------------------------------

    def inspect(
        self,
        text: str,
        clipperx_state: str,
        shield_state: str,
        approved_bricks: Optional[List[str]] = None,
        human_approval_required: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ) -> AVADecision:
        """
        Evaluate a business-room request and return an AVADecision.

        Parameters
        ----------
        text:
            The raw user / task text.
        clipperx_state:
            Room state string from CLIPPERX.  Must equal ``"LIVE_ROOM"``
            for AVA to operate.
        shield_state:
            Risk state from SHIELDBRICK.  ``"RED"`` blocks the action.
        approved_bricks:
            List of Clip Brick names approved for this room.
        human_approval_required:
            Set True when SHIELDBRICK flags a high-risk action.
        context:
            Optional extra metadata passed through to the decision record.
        """
        session_id = str(uuid.uuid4())
        approved: Set[str] = set(approved_bricks or [])
        notes: List[str] = []
        prevention_rules_checked: List[str] = []

        # 1. Room guard — CLIPPERX must open a verified room.
        if clipperx_state != "LIVE_ROOM":
            decision = AVADecision(
                session_id=session_id,
                brick_id=self.brick_id,
                state=AVAState.ROOM_LOCKED,
                can_draft=False,
                approval_required=False,
                routed_brick=None,
                draft_type="none",
                blocked_reason="CLIPPERX has not opened a verified LIVE_ROOM.",
                notes=[
                    "AVA is locked until room, key, Memory Chip, approved bricks, "
                    "and STITCH handshake pass."
                ],
                prevention_rules_checked=[],
                metadata={"clipperx_state": clipperx_state, "mode": "business_operator_guard"},
            )
            self._decisions.append(decision)
            return decision

        # 2. Shield guard — RED state blocks the action.
        if shield_state == "RED":
            decision = AVADecision(
                session_id=session_id,
                brick_id=self.brick_id,
                state=AVAState.APPROVAL_REQUIRED,
                can_draft=False,
                approval_required=True,
                routed_brick=None,
                draft_type="blocked",
                blocked_reason="SHIELDBRICK-001 blocked the action.",
                notes=["Human/legal/security review required before AVA may continue."],
                prevention_rules_checked=[],
                metadata={"shield_state": shield_state, "mode": "business_operator_guard"},
            )
            self._decisions.append(decision)
            return decision

        lower = text.lower()

        # 3. Prevention registry check — blocked patterns halt the draft.
        block_hit = self._check_prevention_registry(lower, prevention_rules_checked)
        if block_hit:
            decision = AVADecision(
                session_id=session_id,
                brick_id=self.brick_id,
                state=AVAState.APPROVAL_REQUIRED,
                can_draft=False,
                approval_required=True,
                routed_brick=None,
                draft_type="blocked",
                blocked_reason=f"Prevention registry blocked pattern: {block_hit}",
                notes=["Pattern matches a known blocked incident type."],
                prevention_rules_checked=prevention_rules_checked,
                metadata={"mode": "business_operator_guard"},
            )
            self._decisions.append(decision)
            return decision

        # 4. Brick routing — must be in approved set.
        routed = self._route(lower)
        if routed and routed not in approved:
            notes.append(
                f"Requested task maps to {routed}, but that brick is not "
                "approved for this room."
            )
            decision = AVADecision(
                session_id=session_id,
                brick_id=self.brick_id,
                state=AVAState.APPROVAL_REQUIRED,
                can_draft=False,
                approval_required=True,
                routed_brick=routed,
                draft_type="none",
                blocked_reason="Requested routed brick is not approved for this business room.",
                notes=notes,
                prevention_rules_checked=prevention_rules_checked,
                metadata={
                    "approved_bricks": sorted(approved),
                    "mode": "business_operator_guard",
                },
            )
            self._decisions.append(decision)
            return decision

        # 5. Draft — AVA may proceed.
        if not routed and approved:
            # No specific route detected; default to first approved brick.
            routed = sorted(approved)[0]

        draft_type = self._draft_type(lower)
        state = AVAState.APPROVAL_REQUIRED if human_approval_required else AVAState.DRAFTING

        if human_approval_required:
            notes.append(
                "AVA may draft only as approval-prep; do not commit externally."
            )
        else:
            notes.append("AVA may draft bounded output inside verified room.")

        decision = AVADecision(
            session_id=session_id,
            brick_id=self.brick_id,
            state=state,
            can_draft=True,
            approval_required=human_approval_required,
            routed_brick=routed,
            draft_type=draft_type,
            blocked_reason=None,
            notes=notes,
            prevention_rules_checked=prevention_rules_checked,
            metadata={
                "approved_bricks": sorted(approved),
                "mode": "business_operator_guard",
                **(context or {}),
            },
        )
        self._decisions.append(decision)
        return decision

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _route(self, lower: str) -> Optional[str]:
        for marker, brick in BRICK_ROUTES.items():
            if marker in lower:
                return brick
        return None

    @staticmethod
    def _draft_type(lower: str) -> str:
        if any(w in lower for w in _MUSIC_WORDS):
            return "music_draft"
        if any(w in lower for w in _CONTENT_WORDS):
            return "content_draft"
        if any(w in lower for w in _SALES_WORDS):
            return "sales_draft"
        if any(w in lower for w in _PLAN_WORDS):
            return "plan_draft"
        if any(w in lower for w in _REPLY_WORDS):
            return "customer_reply_draft"
        return "general_business_draft"

    def _check_prevention_registry(
        self, lower: str, checked: List[str]
    ) -> Optional[str]:
        """
        Check whether any part of the request text matches a blocked pattern
        in the PreventionRegistry.  Appends all checked rule IDs to *checked*.
        Returns the matched pattern string if blocked, else None.
        """
        for rule in self.prevention_registry.all_rules():
            if not rule.active:
                continue
            checked.append(rule.rule_id)
            pattern = rule.incident_type.value.lower()
            if pattern in lower:
                if self.prevention_registry.is_blocked(rule.incident_type.value):
                    return rule.incident_type.value
        return None

    # ------------------------------------------------------------------
    # Session history
    # ------------------------------------------------------------------

    def all_decisions(self) -> List[AVADecision]:
        """Return all AVADecision records made in this session."""
        return list(self._decisions)

    def last_decision(self) -> Optional[AVADecision]:
        """Return the most recent AVADecision, or None if no decisions yet."""
        return self._decisions[-1] if self._decisions else None
