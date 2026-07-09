import uuid
from typing import FrozenSet, List, Set

from .incident import IncidentStudyRecord, Severity, SourceType
from .prevention import PreventionRegistry, PreventionRule


class ImmunityNode:
    """
    Converts lessons into defenses.

    Job:
        convert incident → system rule
        block repeated failure patterns
        tighten intake gates
        update quarantine triggers
        update Hunter detection patterns
        update Verification questions
        update Certification requirements
        update owner warning rules

    This is the "don't let it happen again" node.
    """

    def __init__(self, prevention_registry: PreventionRegistry) -> None:
        self.prevention_registry = prevention_registry
        self._tightened_gates: Set[str] = set()
        self._quarantine_triggers: Set[str] = set()
        self._hunter_detection_updates: List[str] = []
        self._verification_questions: List[str] = []
        self._certification_requirements: List[str] = []
        self._owner_warnings: List[str] = []

    def apply_immunity(self, record: IncidentStudyRecord) -> None:
        """Run the full immunity pipeline for a studied incident."""
        self.convert_to_rule(record)
        if record.repeat_risk:
            self.block_repeated_pattern(record.incident_type.value)
        self._tighten_gate_for_source(record.source)
        self._add_quarantine_trigger(record)
        self._apply_hunter_detection(record)
        self._apply_verification_questions(record)
        self._apply_certification_requirements(record)
        self._apply_owner_warnings(record)

    # ------------------------------------------------------------------
    # Rule conversion
    # ------------------------------------------------------------------

    def convert_to_rule(self, record: IncidentStudyRecord) -> None:
        """Register the incident's prevention rule if not already present."""
        if not record.prevention_rule_added:
            return
        existing = self.prevention_registry.get_rules_for_type(record.incident_type)
        already_registered = any(
            r.source_incident_id == record.incident_id for r in existing
        )
        if not already_registered:
            rule = PreventionRule(
                rule_id=f"imm-{uuid.uuid4().hex[:8]}",
                incident_type=record.incident_type,
                trigger_condition=(
                    f"Immunity rule from incident {record.incident_id}"
                ),
                action=record.prevention_rule_added,
                source_incident_id=record.incident_id,
            )
            self.prevention_registry.add_rule(rule)

    # ------------------------------------------------------------------
    # Pattern + gate management
    # ------------------------------------------------------------------

    def block_repeated_pattern(self, pattern: str) -> None:
        self.prevention_registry.block_pattern(pattern)

    def tighten_gate(self, gate: str) -> None:
        self._tightened_gates.add(gate)

    def add_quarantine_trigger(self, trigger: str) -> None:
        self._quarantine_triggers.add(trigger)

    # ------------------------------------------------------------------
    # Detection + question updates
    # ------------------------------------------------------------------

    def update_hunter_detection(self, pattern: str) -> None:
        if pattern not in self._hunter_detection_updates:
            self._hunter_detection_updates.append(pattern)

    def update_verification_questions(self, question: str) -> None:
        if question not in self._verification_questions:
            self._verification_questions.append(question)

    def update_certification_requirements(self, requirement: str) -> None:
        if requirement not in self._certification_requirements:
            self._certification_requirements.append(requirement)

    def add_owner_warning(self, warning: str) -> None:
        if warning not in self._owner_warnings:
            self._owner_warnings.append(warning)

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    def _tighten_gate_for_source(self, source: SourceType) -> None:
        gate = f"intake_gate:{source.value}"
        self._tightened_gates.add(gate)
        if source == SourceType.UNKNOWN_SOURCE:
            self._tightened_gates.add("intake_gate:all_unknown")

    def _add_quarantine_trigger(self, record: IncidentStudyRecord) -> None:
        trigger = f"quarantine:{record.incident_type.value}:{record.source.value}"
        self._quarantine_triggers.add(trigger)

    def _apply_hunter_detection(self, record: IncidentStudyRecord) -> None:
        self.update_hunter_detection(f"hunt:{record.incident_type.value}")

    def _apply_verification_questions(self, record: IncidentStudyRecord) -> None:
        question = (
            f"Was {record.incident_type.value} from "
            f"{record.source.value} ruled out?"
        )
        self.update_verification_questions(question)

    def _apply_certification_requirements(self, record: IncidentStudyRecord) -> None:
        requirement = (
            f"Certify no {record.incident_type.value} present before release."
        )
        self.update_certification_requirements(requirement)

    def _apply_owner_warnings(self, record: IncidentStudyRecord) -> None:
        if record.severity in (Severity.HIGH, Severity.CRITICAL):
            warning = (
                f"OWNER ALERT: {record.severity.value} — "
                f"{record.incident_type.value} from {record.source.value}. "
                f"Root cause: {record.root_cause}"
            )
            self.add_owner_warning(warning)

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def tightened_gates(self) -> FrozenSet[str]:
        return frozenset(self._tightened_gates)

    @property
    def quarantine_triggers(self) -> FrozenSet[str]:
        return frozenset(self._quarantine_triggers)

    @property
    def hunter_detection_updates(self) -> List[str]:
        return list(self._hunter_detection_updates)

    @property
    def verification_questions(self) -> List[str]:
        return list(self._verification_questions)

    @property
    def certification_requirements(self) -> List[str]:
        return list(self._certification_requirements)

    @property
    def owner_warnings(self) -> List[str]:
        return list(self._owner_warnings)
