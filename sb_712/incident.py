from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional
import uuid


class IncidentType(Enum):
    FILE_CORRUPTION = "FILE_CORRUPTION"
    MISSING_RECORD = "MISSING_RECORD"
    BAD_UPLOAD = "BAD_UPLOAD"
    PAYMENT_MISMATCH = "PAYMENT_MISMATCH"
    PROOF_MISSING = "PROOF_MISSING"
    REVISION_ERROR = "REVISION_ERROR"
    FINAL_RELEASE_BLOCK = "FINAL_RELEASE_BLOCK"
    CONTRACTOR_PAYOUT_MISMATCH = "CONTRACTOR_PAYOUT_MISMATCH"
    COMPLIANCE_RECORD_ERROR = "COMPLIANCE_RECORD_ERROR"
    LEDGER_DRIFT = "LEDGER_DRIFT"
    CHECKPOINT_DAMAGE = "CHECKPOINT_DAMAGE"
    DUPLICATE_PROCESS = "DUPLICATE_PROCESS"
    RAM_PRESSURE = "RAM_PRESSURE"
    UNKNOWN_CHANGE = "UNKNOWN_CHANGE"
    REPEATED_ATTACK = "REPEATED_ATTACK"
    USER_ERROR = "USER_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class SourceType(Enum):
    CLIENT_UPLOAD = "client_upload"
    OWNER_ACTION = "owner_action"
    CONTRACTOR_ACTION = "contractor_action"
    PAYMENT_SYSTEM = "payment_system"
    EMAIL_INTAKE = "email_intake"
    MANUAL_FILE_MOVE = "manual_file_move"
    DASHBOARD_ACTION = "dashboard_action"
    SCRIPT_ACTION = "script_action"
    IMPORTED_FILE = "imported_file"
    UNKNOWN_SOURCE = "unknown_source"


class Severity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WATCHING = "WATCHING"


# Valid outcomes for hunter rescan during the return-check loop.
HUNTER_RESCAN_OUTCOMES = frozenset({
    "problem_gone",
    "problem_still_active",
    "new_damage_found",
    "false_alarm",
    "repeat_attack",
})

# Rescan outcomes that trigger a convoy reopen.
HUNTER_RESCAN_REOPEN_OUTCOMES = frozenset({
    "problem_still_active",
    "new_damage_found",
    "repeat_attack",
})


@dataclass
class IncidentStudyRecord:
    project_id: str
    incident_type: IncidentType
    source: SourceType
    severity: Severity

    # Study questions
    what_happened: str = ""
    location: str = ""
    when_started: Optional[datetime] = None
    where_it_came_from: str = ""
    how_it_got_in: str = ""
    what_it_touched: List[str] = field(default_factory=list)
    damage_found: str = ""

    # Recovery actions
    containment_action: str = ""
    repair_action: str = ""
    verification_result: str = ""
    certification_result: str = ""
    return_check_result: str = ""

    # Analysis
    root_cause: str = ""
    repeat_risk: bool = False
    prevention_rule_added: str = ""

    # System update flags
    hunter_pattern_updated: bool = False
    verification_rule_updated: bool = False
    checkpoint_created: bool = False

    # Status
    status: IncidentStatus = IncidentStatus.OPEN

    # Auto-generated
    incident_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    date: datetime = field(default_factory=datetime.utcnow)

    # Recovery decision flags
    damage_is_local: bool = True
    damage_is_spreading: bool = False
    truth_verified: bool = False
    spine_threatened: bool = False
    ledger_corrupted: bool = False
    nodes_disagree: bool = False
    checkpoint_lineage_unclear: bool = False
    master_phoenix_confidence: bool = True

    # Return-check: hunter rescan outcome.
    # Valid values: "problem_gone", "problem_still_active",
    #               "new_damage_found", "false_alarm", "repeat_attack", or None.
    hunter_rescan_outcome: Optional[str] = None
