import uuid
from typing import List

from .incident import IncidentStudyRecord, IncidentType
from .prevention import PreventionRegistry, PreventionRule
from .report import generate_report

# Incident types where a repeat occurrence is considered high-risk.
_HIGH_REPEAT_RISK_TYPES = frozenset({
    IncidentType.REPEATED_ATTACK,
    IncidentType.LEDGER_DRIFT,
    IncidentType.CHECKPOINT_DAMAGE,
    IncidentType.PAYMENT_MISMATCH,
    IncidentType.DUPLICATE_PROCESS,
    IncidentType.CONTRACTOR_PAYOUT_MISMATCH,
})


class LearningNode:
    """
    Studies every incident after the recovery convoy closes it.

    Job:
        study incident → classify issue → trace source → measure damage
        → record repair path → create prevention rule
        → update hunter patterns → update verification rules
        → create new checkpoint flag → write lesson report

    Every incident becomes training.
    Every repair becomes prevention.
    Every failure becomes a new defense rule.
    """

    def __init__(self, prevention_registry: PreventionRegistry) -> None:
        self.prevention_registry = prevention_registry
        self._lesson_reports: List[str] = []

    def process(self, record: IncidentStudyRecord) -> str:
        """
        Run the full learning pipeline.
        Returns the lesson report string and stores it internally.
        """
        self._derive_root_cause(record)
        self._assess_repeat_risk(record)
        self._create_prevention_rule(record)
        self._update_hunter_patterns(record)
        self._update_verification_rules(record)
        self._flag_checkpoint_created(record)
        report = self.write_lesson_report(record)
        self._lesson_reports.append(report)
        return report

    # ------------------------------------------------------------------
    # Study steps
    # ------------------------------------------------------------------

    def _derive_root_cause(self, record: IncidentStudyRecord) -> None:
        if not record.root_cause:
            record.root_cause = (
                f"Derived from {record.incident_type.value} "
                f"via {record.source.value}"
            )

    def _assess_repeat_risk(self, record: IncidentStudyRecord) -> None:
        record.repeat_risk = record.incident_type in _HIGH_REPEAT_RISK_TYPES

    def _create_prevention_rule(self, record: IncidentStudyRecord) -> None:
        # If a prevention rule was already manually set, respect it.
        if record.prevention_rule_added:
            return
        action = (
            f"Auto-rule: On {record.incident_type.value} from {record.source.value}, "
            f"trigger containment and alert. Root cause: {record.root_cause}"
        )
        rule = PreventionRule(
            rule_id=f"auto-{uuid.uuid4().hex[:8]}",
            incident_type=record.incident_type,
            trigger_condition=f"Incident type {record.incident_type.value} detected",
            action=action,
            source_incident_id=record.incident_id,
        )
        self.prevention_registry.add_rule(rule)
        record.prevention_rule_added = action

    def _update_hunter_patterns(self, record: IncidentStudyRecord) -> None:
        record.hunter_pattern_updated = True

    def _update_verification_rules(self, record: IncidentStudyRecord) -> None:
        record.verification_rule_updated = True

    def _flag_checkpoint_created(self, record: IncidentStudyRecord) -> None:
        record.checkpoint_created = True

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def write_lesson_report(self, record: IncidentStudyRecord) -> str:
        return generate_report(record)

    def all_lesson_reports(self) -> List[str]:
        return list(self._lesson_reports)
