from .incident import IncidentStudyRecord


def generate_report(record: IncidentStudyRecord) -> str:
    """Generate the standard Incident Study Report for an IncidentStudyRecord."""
    touched = (
        ", ".join(record.what_it_touched) if record.what_it_touched else "NONE"
    )
    when_started = (
        record.when_started.isoformat() if record.when_started else "UNKNOWN"
    )
    repeat_risk = "YES" if record.repeat_risk else "NO"
    hunter_updated = "YES" if record.hunter_pattern_updated else "NO"
    verification_updated = "YES" if record.verification_rule_updated else "NO"
    checkpoint_created = "YES" if record.checkpoint_created else "NO"
    rescan = record.hunter_rescan_outcome or "NOT YET PERFORMED"

    lines = [
        "=" * 62,
        "  INCIDENT STUDY REPORT",
        "=" * 62,
        f"INCIDENT_ID:               {record.incident_id}",
        f"DATE:                      {record.date.isoformat()}",
        f"PROJECT_ID:                {record.project_id}",
        f"LOCATION:                  {record.location or 'UNKNOWN'}",
        f"SOURCE:                    {record.source.value}",
        f"INCIDENT_TYPE:             {record.incident_type.value}",
        f"SEVERITY:                  {record.severity.value}",
        "-" * 62,
        f"WHAT_HAPPENED:             {record.what_happened or 'NOT RECORDED'}",
        f"WHEN_STARTED:              {when_started}",
        f"WHERE_IT_CAME_FROM:        {record.where_it_came_from or 'UNKNOWN'}",
        f"HOW_IT_GOT_IN:             {record.how_it_got_in or 'UNKNOWN'}",
        f"WHAT_IT_TOUCHED:           {touched}",
        f"DAMAGE_FOUND:              {record.damage_found or 'NONE'}",
        "-" * 62,
        f"CONTAINMENT_ACTION:        {record.containment_action or 'NONE'}",
        f"REPAIR_ACTION:             {record.repair_action or 'NONE'}",
        f"VERIFICATION_RESULT:       {record.verification_result or 'PENDING'}",
        f"CERTIFICATION_RESULT:      {record.certification_result or 'PENDING'}",
        f"RETURN_CHECK_RESULT:       {record.return_check_result or 'PENDING'}",
        f"HUNTER_RESCAN_OUTCOME:     {rescan}",
        "-" * 62,
        f"ROOT_CAUSE:                {record.root_cause or 'UNDER INVESTIGATION'}",
        f"REPEAT_RISK:               {repeat_risk}",
        f"PREVENTION_RULE_ADDED:     {record.prevention_rule_added or 'NONE'}",
        f"HUNTER_PATTERN_UPDATED:    {hunter_updated}",
        f"VERIFICATION_RULE_UPDATED: {verification_updated}",
        f"CHECKPOINT_CREATED:        {checkpoint_created}",
        "-" * 62,
        f"STATUS:                    {record.status.value}",
        "=" * 62,
    ]
    return "\n".join(lines)
