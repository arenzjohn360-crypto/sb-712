import json
from datetime import timedelta
from pathlib import Path

import pytest

from sb_712 import (
    EncryptedAuditTrail,
    JWTAuthManager,
    SecurityPolicy,
    SupabaseSecurityBlueprint,
    TokenClaims,
    TrustedOperationGateway,
    VSCodeWorkspaceBlueprint,
    WindowsServiceInstallerBlueprint,
    build_runtime_manifest,
    render_env_template,
)
from sb_712.security import _utcnow


def test_trusted_operation_requires_verification_before_trust():
    auth = JWTAuthManager(secret=b"s" * 32, issuer="sb712", audience="sb712-web")
    claims = TokenClaims(
        sub="user-123",
        role="admin",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() + timedelta(minutes=5),
        scopes=("trust:write",),
    )
    gateway = TrustedOperationGateway(auth=auth, policy=SecurityPolicy())
    token = auth.issue_token(claims)

    result = gateway.authorize_operation(
        authorization_header="Bearer " + token,
        origin="https://app.sb712.local",
        action="deploy.release",
        resource="spine",
        required_role="admin",
        metadata={"component": "upgrade"},
    )

    assert result.trusted is True
    assert all(result.verification_steps.values())
    assert result.cors_headers["Access-Control-Allow-Origin"] == "https://app.sb712.local"
    assert "connect-src 'self' https://*.supabase.co wss://*.supabase.co" in result.csp_header


def test_trusted_operation_rejects_invalid_origin_and_rate_limit():
    auth = JWTAuthManager(secret=b"r" * 32, issuer="sb712", audience="sb712-web")
    claims = TokenClaims(
        sub="user-456",
        role="operator",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() + timedelta(minutes=5),
    )
    policy = SecurityPolicy(rate_limit_max_requests=1, rate_limit_window_seconds=60)
    gateway = TrustedOperationGateway(auth=auth, policy=policy)
    token = auth.issue_token(claims)

    bad_origin = gateway.authorize_operation(
        authorization_header="Bearer " + token,
        origin="https://evil.example.com",
        action="trace.audit",
        resource="audit-log",
        required_role="viewer",
    )
    assert bad_origin.trusted is False
    assert bad_origin.verification_steps["cors"] is False

    first = gateway.authorize_operation(
        authorization_header="Bearer " + token,
        origin="https://app.sb712.local",
        action="trace.audit",
        resource="audit-log",
        required_role="viewer",
    )
    second = gateway.authorize_operation(
        authorization_header="Bearer " + token,
        origin="https://app.sb712.local",
        action="trace.audit",
        resource="audit-log",
        required_role="viewer",
    )
    assert first.trusted is True
    assert second.trusted is False
    assert second.verification_steps["rate_limit"] is False


def test_encrypted_audit_trail_is_tamper_evident_and_merkle_verified():
    trail = EncryptedAuditTrail(key=b"k" * 32)
    first = trail.append("user-1", "login", "frontend", "accepted", {"role": "viewer"})
    second = trail.append("user-1", "publish", "trust-ledger", "accepted", {"role": "admin"})

    assert trail.verify_integrity() is True
    assert trail.verify_membership(first) is True
    assert trail.verify_membership(second) is True
    assert trail.decrypt(second)["metadata"]["role"] == "admin"
    assert len(trail.merkle_root()) == 64

    tampered = trail.records()[0]
    trail._records[0] = tampered.__class__(**{**tampered.__dict__, "ciphertext_b64": "tampered"})
    assert trail.verify_integrity() is False


def test_supabase_blueprint_covers_rls_realtime_encryption_and_rollback():
    blueprint = SupabaseSecurityBlueprint()
    migration_sql = blueprint.render_migration_sql()
    rollback_sql = blueprint.render_rollback_sql()

    assert "enable row level security" in migration_sql
    assert "payload_ciphertext bytea not null" in migration_sql
    assert "create publication sb712_realtime" in migration_sql
    assert "verification_count integer not null check (verification_count >= 3)" in migration_sql
    assert "drop publication if exists sb712_realtime;" in rollback_sql
    assert blueprint.manifest()["rls_enabled"] is True


def test_workspace_artifacts_match_blueprints():
    repo_root = Path(__file__).resolve().parents[1]
    vscode = VSCodeWorkspaceBlueprint()
    installer = WindowsServiceInstallerBlueprint()
    supabase = SupabaseSecurityBlueprint()

    launch_json = json.loads((repo_root / ".vscode" / "launch.json").read_text(encoding="utf-8"))
    settings_json = json.loads((repo_root / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    extensions_json = json.loads((repo_root / ".vscode" / "extensions.json").read_text(encoding="utf-8"))
    assert launch_json == vscode.launch_json()
    assert settings_json == vscode.settings_json()
    assert extensions_json == vscode.extensions_json()

    installer_script = (repo_root / "scripts" / "install-sb712-service.ps1").read_text(encoding="utf-8")
    assert installer_script == installer.render_script()
    assert str(repo_root / "supabase" / "migrations" / "0001_sb712_security.sql").endswith("0001_sb712_security.sql")
    assert (repo_root / "supabase" / "migrations" / "0001_sb712_security.sql").read_text(encoding="utf-8") == supabase.render_migration_sql()
    assert (repo_root / "supabase" / "migrations" / "0001_sb712_security_rollback.sql").read_text(encoding="utf-8") == supabase.render_rollback_sql()
    assert (repo_root / ".env.example").read_text(encoding="utf-8") == render_env_template()


def test_runtime_manifest_summarizes_upgrade_readiness():
    manifest = build_runtime_manifest()

    assert manifest["backend_security"]["jwt_auth"] is True
    assert manifest["frontend_security"]["role_based_access_control"][-1] == "admin"
    assert manifest["supabase"]["schema_version"] == "0001_sb712_security"
    assert manifest["installer"]["install_root"] == r"$env:ProgramFiles\SB712\system"
    assert manifest["upgrade"]["trust_rule"] == "No active state becomes trusted state without verification"


def test_jwt_validation_rejects_expired_token():
    auth = JWTAuthManager(secret=b"x" * 32, issuer="sb712", audience="sb712-web")
    claims = TokenClaims(
        sub="expired-user",
        role="viewer",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() - timedelta(seconds=1),
    )
    token = auth.issue_token(claims)

    with pytest.raises(ValueError):
        auth.validate_token(token)
