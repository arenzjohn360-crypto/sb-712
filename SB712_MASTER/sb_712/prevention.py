from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from .incident import IncidentType


@dataclass
class PreventionRule:
    rule_id: str
    incident_type: IncidentType
    trigger_condition: str
    action: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = True
    source_incident_id: Optional[str] = None


class PreventionRegistry:
    """
    Stores prevention rules and blocked patterns.
    Seeded with default rules derived from known JGA Brick 1 failure modes.
    """

    def __init__(self) -> None:
        self._rules: List[PreventionRule] = []
        self._blocked_patterns: set = set()
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        defaults = [
            PreventionRule(
                rule_id="default-001",
                incident_type=IncidentType.BAD_UPLOAD,
                trigger_condition="file uploaded without project ID",
                action="Require project ID before intake accepts upload",
            ),
            PreventionRule(
                rule_id="default-002",
                incident_type=IncidentType.PROOF_MISSING,
                trigger_condition="proof missing watermark flag",
                action="Block proof export unless watermark flag exists",
            ),
            PreventionRule(
                rule_id="default-003",
                incident_type=IncidentType.FINAL_RELEASE_BLOCK,
                trigger_condition="final file release attempted before final payment",
                action="Add final payment check before release",
            ),
            PreventionRule(
                rule_id="default-004",
                incident_type=IncidentType.CONTRACTOR_PAYOUT_MISMATCH,
                trigger_condition="contractor payout does not match deposit",
                action="Recalculate payout from cleared deposit only",
            ),
            PreventionRule(
                rule_id="default-005",
                incident_type=IncidentType.PAYMENT_MISMATCH,
                trigger_condition="payment screenshot used as proof of clearance",
                action="Reject screenshots as clearance proof",
            ),
            PreventionRule(
                rule_id="default-006",
                incident_type=IncidentType.FILE_CORRUPTION,
                trigger_condition="client file corrupted project folder",
                action="Quarantine uploads before project entry",
            ),
            PreventionRule(
                rule_id="default-007",
                incident_type=IncidentType.REVISION_ERROR,
                trigger_condition="revision count exceeded",
                action="Lock extra revision until fee or owner approval",
            ),
            PreventionRule(
                rule_id="default-008",
                incident_type=IncidentType.COMPLIANCE_RECORD_ERROR,
                trigger_condition="state tag missing on record",
                action="Block archive until jurisdiction tag exists",
            ),
            PreventionRule(
                rule_id="default-009",
                incident_type=IncidentType.RAM_PRESSURE,
                trigger_condition="RAM overload detected",
                action="Slow dashboard refresh and stop duplicate launcher",
            ),
        ]
        self._rules.extend(defaults)

    def add_rule(self, rule: PreventionRule) -> None:
        self._rules.append(rule)

    def block_pattern(self, pattern: str) -> None:
        self._blocked_patterns.add(pattern)

    def is_blocked(self, pattern: str) -> bool:
        return pattern in self._blocked_patterns

    def get_rules_for_type(self, incident_type: IncidentType) -> List[PreventionRule]:
        return [r for r in self._rules if r.incident_type == incident_type and r.active]

    def all_rules(self) -> List[PreventionRule]:
        return list(self._rules)

    def deactivate_rule(self, rule_id: str) -> bool:
        for rule in self._rules:
            if rule.rule_id == rule_id:
                rule.active = False
                return True
        return False
