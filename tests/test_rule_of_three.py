from sb688.rule_of_three import TrustGate, TrustStage


def test_rule_of_three_success_path_reaches_trusted_state():
    gate = TrustGate(object_id="client_record_001", payload={"client": "test"})

    assert gate.stage == TrustStage.UNKNOWN
    assert gate.verify(source="verifier_a", result=True) == TrustStage.VERIFIED
    assert gate.re_verify(source="verifier_b", result=True) == TrustStage.RE_VERIFIED
    assert gate.certify(source="certifier", result=True) == TrustStage.TRUSTED

    report = gate.report()

    assert gate.is_trusted is True
    assert report["trusted"] is True
    assert report["quarantined"] is False
    assert report["evidence_count"] == 4


def test_rule_of_three_verification_failure_quarantines():
    gate = TrustGate(object_id="unknown_payload")

    assert gate.verify(source="verifier_a", result=False, note="bad source") == TrustStage.QUARANTINED
    assert gate.is_quarantined is True
    assert gate.is_trusted is False


def test_rule_of_three_cannot_skip_reverification():
    gate = TrustGate(object_id="shortcut_attempt")

    gate.verify(source="verifier_a", result=True)
    result = gate.certify(source="certifier", result=True)

    assert result == TrustStage.QUARANTINED
    assert gate.is_quarantined is True
    assert gate.is_trusted is False


def test_rule_of_three_unknown_cannot_be_certified():
    gate = TrustGate(object_id="raw_input")

    result = gate.certify(source="certifier", result=True)

    assert result == TrustStage.QUARANTINED
    assert gate.is_quarantined is True
    assert gate.is_trusted is False
