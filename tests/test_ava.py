"""
Tests for sb_712.ava — AVA Business Operator Layer.

Covers:
    - Room guard (CLIPPERX must report LIVE_ROOM)
    - Shield guard (RED blocks the action)
    - Prevention registry blocked patterns
    - Brick routing (approved vs unapproved bricks)
    - Draft-type detection (content, sales, plan, reply, music, general)
    - AVAState transitions
    - AVADecision record fields
    - Session history (all_decisions / last_decision)
    - Integration with PreventionRegistry
"""

import pytest

from sb_712.prevention import PreventionRegistry
from sb_712.incident import IncidentType
from sb_712.ava import AVAState, AVADecision, AVASession, BRICK_ROUTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_session(**kwargs) -> AVASession:
    registry = kwargs.pop("registry", PreventionRegistry())
    return AVASession(prevention_registry=registry, **kwargs)


def live_inspect(
    session: AVASession,
    text: str = "write a caption for the new post",
    approved_bricks=None,
    shield_state: str = "GREEN",
    human_approval_required: bool = False,
):
    return session.inspect(
        text=text,
        clipperx_state="LIVE_ROOM",
        shield_state=shield_state,
        approved_bricks=approved_bricks or ["content_brick"],
        human_approval_required=human_approval_required,
    )


# ---------------------------------------------------------------------------
# Room guard — CLIPPERX must be LIVE_ROOM
# ---------------------------------------------------------------------------

def test_room_locked_when_clipperx_not_live():
    session = make_session()
    decision = session.inspect(
        text="write a post",
        clipperx_state="OFFLINE",
        shield_state="GREEN",
    )
    assert decision.state == AVAState.ROOM_LOCKED
    assert not decision.can_draft
    assert not decision.approval_required
    assert decision.blocked_reason is not None
    assert "LIVE_ROOM" in decision.blocked_reason


def test_room_locked_when_clipperx_is_empty_string():
    session = make_session()
    decision = session.inspect("book appointment", clipperx_state="", shield_state="GREEN")
    assert decision.state == AVAState.ROOM_LOCKED


def test_room_locked_has_note():
    session = make_session()
    decision = session.inspect("do something", clipperx_state="PENDING", shield_state="GREEN")
    assert any("Memory Chip" in n for n in decision.notes)


# ---------------------------------------------------------------------------
# Shield guard — RED blocks the action
# ---------------------------------------------------------------------------

def test_shield_red_blocks_action():
    session = make_session()
    decision = session.inspect(
        text="post the legal statement now",
        clipperx_state="LIVE_ROOM",
        shield_state="RED",
        approved_bricks=["content_brick"],
    )
    assert decision.state == AVAState.APPROVAL_REQUIRED
    assert not decision.can_draft
    assert decision.approval_required
    assert decision.blocked_reason is not None
    assert "SHIELDBRICK" in decision.blocked_reason


def test_shield_green_does_not_block():
    session = make_session()
    decision = live_inspect(session)
    assert decision.state != AVAState.ROOM_LOCKED
    assert decision.state != AVAState.APPROVAL_REQUIRED or decision.can_draft


def test_shield_yellow_is_not_blocked():
    session = make_session()
    decision = session.inspect(
        text="write a caption",
        clipperx_state="LIVE_ROOM",
        shield_state="YELLOW",
        approved_bricks=["content_brick"],
    )
    # YELLOW is not RED, so not hard-blocked
    assert decision.state != AVAState.ROOM_LOCKED
    assert decision.draft_type != "none" or decision.can_draft is False  # still proceeds to routing


# ---------------------------------------------------------------------------
# Brick routing — approved vs unapproved
# ---------------------------------------------------------------------------

def test_routing_to_approved_content_brick():
    session = make_session()
    decision = live_inspect(session, text="write a caption", approved_bricks=["content_brick"])
    assert decision.routed_brick == "content_brick"
    assert decision.can_draft


def test_unapproved_brick_triggers_approval_required():
    session = make_session()
    decision = session.inspect(
        text="book an appointment",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["content_brick"],  # booking_brick not in approved list
    )
    assert decision.state == AVAState.APPROVAL_REQUIRED
    assert not decision.can_draft
    assert decision.routed_brick == "booking_brick"
    assert decision.blocked_reason is not None


def test_approved_booking_brick_routes_correctly():
    session = make_session()
    decision = session.inspect(
        text="book an appointment for the barber",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["booking_brick"],
    )
    assert decision.routed_brick == "booking_brick"
    assert decision.can_draft


def test_no_specific_route_defaults_to_first_approved_brick():
    session = make_session()
    decision = session.inspect(
        text="help me with a general task",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["alpha_brick", "beta_brick"],
    )
    assert decision.routed_brick == "alpha_brick"  # sorted first
    assert decision.can_draft


def test_empty_approved_bricks_with_unknown_route():
    session = make_session()
    decision = session.inspect(
        text="help me with a general task",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=[],
    )
    assert decision.can_draft
    assert decision.routed_brick is None


# ---------------------------------------------------------------------------
# Draft-type detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_draft_type", [
    ("write a caption for the post", "content_draft"),
    ("create a facebook post", "content_draft"),
    ("create social media content", "content_draft"),
    ("draft a sales pitch for the lead", "sales_draft"),
    ("write a close offer for the customer", "sales_draft"),
    ("build a strategy plan", "plan_draft"),
    ("create a roadmap for Q3", "plan_draft"),
    ("write a customer reply to the complaint", "customer_reply_draft"),
    ("draft a support response", "customer_reply_draft"),
    ("plan the music release", "music_draft"),
    ("write the song description", "music_draft"),
    ("help me with the next album", "music_draft"),
    ("do something unrecognised", "general_business_draft"),
])
def test_draft_type_detection(text, expected_draft_type):
    session = make_session()
    decision = session.inspect(
        text=text,
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=[
            "content_brick", "sales_brick", "strategy_brick",
            "support_brick", "music_brick", "general_brick",
        ],
    )
    assert decision.draft_type == expected_draft_type


# ---------------------------------------------------------------------------
# Human approval required flag
# ---------------------------------------------------------------------------

def test_human_approval_required_sets_state_and_flag():
    session = make_session()
    decision = live_inspect(session, human_approval_required=True)
    assert decision.state == AVAState.APPROVAL_REQUIRED
    assert decision.approval_required
    assert decision.can_draft  # AVA can prep the draft, just not commit


def test_human_approval_not_required_sets_drafting_state():
    session = make_session()
    decision = live_inspect(session, human_approval_required=False)
    assert decision.state == AVAState.DRAFTING
    assert not decision.approval_required
    assert decision.can_draft


# ---------------------------------------------------------------------------
# Prevention registry integration
# ---------------------------------------------------------------------------

def test_blocked_pattern_in_registry_halts_ava():
    registry = PreventionRegistry()
    # Add a rule for LEDGER_DRIFT and block the pattern.
    from sb_712.prevention import PreventionRule
    registry.add_rule(PreventionRule(
        rule_id="test-ledger-drift",
        incident_type=IncidentType.LEDGER_DRIFT,
        trigger_condition="ledger drift detected",
        action="Halt and alert owner",
    ))
    registry.block_pattern(IncidentType.LEDGER_DRIFT.value)
    session = make_session(registry=registry)
    decision = session.inspect(
        text="fix the LEDGER_DRIFT in the system",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["ledger_brick"],
    )
    assert decision.state == AVAState.APPROVAL_REQUIRED
    assert not decision.can_draft
    assert decision.blocked_reason is not None
    assert "LEDGER_DRIFT" in decision.blocked_reason


def test_unblocked_pattern_does_not_halt_ava():
    registry = PreventionRegistry()
    # Do NOT block anything
    session = make_session(registry=registry)
    decision = live_inspect(session, text="write a caption")
    assert decision.can_draft


def test_prevention_rules_checked_populated():
    registry = PreventionRegistry()
    session = make_session(registry=registry)
    decision = live_inspect(session, text="write a caption")
    # Should have checked the default rules
    assert isinstance(decision.prevention_rules_checked, list)


# ---------------------------------------------------------------------------
# AVADecision record fields
# ---------------------------------------------------------------------------

def test_decision_has_unique_session_id():
    session = make_session()
    d1 = live_inspect(session, text="caption one")
    d2 = live_inspect(session, text="caption two")
    assert d1.session_id != d2.session_id


def test_decision_brick_id_matches_session():
    session = make_session(brick_id="AVABRICK-CUSTOM")
    decision = live_inspect(session)
    assert decision.brick_id == "AVABRICK-CUSTOM"


def test_decision_has_decided_at_timestamp():
    session = make_session()
    decision = live_inspect(session)
    assert decision.decided_at is not None


def test_decision_notes_is_list():
    session = make_session()
    decision = live_inspect(session)
    assert isinstance(decision.notes, list)
    assert len(decision.notes) >= 1


def test_decision_metadata_contains_approved_bricks():
    session = make_session()
    decision = live_inspect(session, approved_bricks=["content_brick", "sales_brick"])
    assert "approved_bricks" in decision.metadata
    assert "content_brick" in decision.metadata["approved_bricks"]


def test_context_passed_through_to_metadata():
    session = make_session()
    decision = session.inspect(
        text="write a caption",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["content_brick"],
        context={"business": "JGA", "owner_id": "007"},
    )
    assert decision.metadata.get("business") == "JGA"
    assert decision.metadata.get("owner_id") == "007"


# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------

def test_all_decisions_returns_history():
    session = make_session()
    live_inspect(session, text="write a caption")
    live_inspect(session, text="book an appointment", approved_bricks=["booking_brick"])
    assert len(session.all_decisions()) == 2


def test_last_decision_returns_most_recent():
    session = make_session()
    live_inspect(session, text="first")
    d2 = live_inspect(session, text="write a caption second")
    assert session.last_decision() is d2


def test_last_decision_none_on_fresh_session():
    session = make_session()
    assert session.last_decision() is None


def test_all_decisions_returns_copy():
    session = make_session()
    live_inspect(session)
    decisions = session.all_decisions()
    decisions.clear()
    assert len(session.all_decisions()) == 1


# ---------------------------------------------------------------------------
# Brick route table sanity
# ---------------------------------------------------------------------------

def test_brick_routes_table_not_empty():
    assert len(BRICK_ROUTES) > 0


def test_brick_routes_all_values_end_in_brick():
    for key, val in BRICK_ROUTES.items():
        assert val.endswith("_brick"), f"Route '{key}' maps to '{val}' — expected to end in '_brick'"


# ---------------------------------------------------------------------------
# End-to-end: full AVA session for a music artist
# ---------------------------------------------------------------------------

def test_music_artist_session():
    """
    Simulates a full AVA session for a music artist business room.

    Room: LIVE_ROOM
    Approved bricks: music_brick, content_brick, booking_brick
    """
    registry = PreventionRegistry()
    session = AVASession(prevention_registry=registry, brick_id="AVABRICK-MUSIC")

    # Request 1: plan the release
    d1 = session.inspect(
        text="write the album release notes for next month",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["music_brick", "content_brick", "booking_brick"],
    )
    assert d1.state == AVAState.DRAFTING
    assert d1.routed_brick == "music_brick"
    assert d1.draft_type == "music_draft"

    # Request 2: write a caption
    d2 = session.inspect(
        text="write a caption for the new drop",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["music_brick", "content_brick", "booking_brick"],
    )
    assert d2.state == AVAState.DRAFTING
    assert d2.routed_brick == "content_brick"
    assert d2.draft_type == "content_draft"

    # Request 3: book a listening session
    d3 = session.inspect(
        text="book an appointment for the listening session",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["music_brick", "content_brick", "booking_brick"],
    )
    assert d3.state == AVAState.DRAFTING
    assert d3.routed_brick == "booking_brick"

    # Three decisions recorded
    assert len(session.all_decisions()) == 3
    assert session.last_decision() is d3


# ---------------------------------------------------------------------------
# End-to-end: blocked room then room opens
# ---------------------------------------------------------------------------

def test_room_lock_then_live():
    session = make_session()

    locked = session.inspect(
        text="do something",
        clipperx_state="PENDING",
        shield_state="GREEN",
        approved_bricks=["content_brick"],
    )
    assert locked.state == AVAState.ROOM_LOCKED

    live = session.inspect(
        text="write a caption",
        clipperx_state="LIVE_ROOM",
        shield_state="GREEN",
        approved_bricks=["content_brick"],
    )
    assert live.state == AVAState.DRAFTING
    assert len(session.all_decisions()) == 2
