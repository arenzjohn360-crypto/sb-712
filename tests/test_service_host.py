import pytest

from sb_712 import service_host


def test_heartbeat_payload_uses_runtime_telemetry(monkeypatch):
    monkeypatch.setattr(service_host, "_read_total_ram_gb", lambda: 4.0)
    monkeypatch.setattr(service_host, "_read_cpu_load_ratio", lambda: 0.5)
    for key in (
        "SB712_JWT_SECRET",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SB712_AUDIT_LOG_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    heartbeat = service_host._heartbeat_payload()["heartbeat"]

    assert heartbeat["node_readiness"] == pytest.approx(0.5)
    assert heartbeat["recovery_readiness"] == pytest.approx(0.0)
    assert heartbeat["trust_ratio"] == pytest.approx(0.0)
    assert heartbeat["score"] == pytest.approx(25.0)
    assert heartbeat["level"] == "DEGRADED"
    assert heartbeat["telemetry"]["cpu_load_ratio"] == pytest.approx(0.5)
    assert heartbeat["telemetry"]["total_ram_gb"] == pytest.approx(4.0)


def test_heartbeat_payload_reflects_env_configuration(monkeypatch):
    monkeypatch.setattr(service_host, "_read_total_ram_gb", lambda: 16.0)
    monkeypatch.setattr(service_host, "_read_cpu_load_ratio", lambda: 0.1)
    monkeypatch.setenv("SB712_JWT_SECRET", "secret")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SB712_AUDIT_LOG_KEY", "audit-key")

    heartbeat = service_host._heartbeat_payload()["heartbeat"]

    assert heartbeat["node_readiness"] == pytest.approx(0.95)
    assert heartbeat["recovery_readiness"] == pytest.approx(1.0)
    assert heartbeat["trust_ratio"] == pytest.approx(1.0)
    assert heartbeat["score"] == pytest.approx(97.5)
    assert heartbeat["telemetry"]["configured_env_vars"] == 4
    assert heartbeat["telemetry"]["required_env_vars"] == 4
