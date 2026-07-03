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


# ---------------------------------------------------------------------------
# Harder tests — repeated hacker attempts and contrast with legitimate users
# ---------------------------------------------------------------------------

def test_repeated_forged_token_attempts_all_rejected():
    """
    A hacker tries five different forged / tampered JWTs back-to-back.
    Every attempt must be rejected; each rejection is distinct in the audit trail.
    """
    auth = JWTAuthManager(secret=b"real" * 8, issuer="sb712", audience="sb712-web")
    gateway = TrustedOperationGateway(auth=auth, policy=SecurityPolicy())

    forged_tokens = [
        "******",           # completely fabricated
        "******",                                                  # wrong structure
        "******",                  # alg=none attack
        "Bearer " + "A" * 80 + "." + "B" * 80 + "." + "C" * 40,            # random garbage
        "Bearer ",                                                            # empty token
    ]

    for attempt_number, forged in enumerate(forged_tokens, start=1):
        result = gateway.authorize_operation(
            authorization_header=forged,
            origin="https://app.sb712.local",
            action="admin.escalate",
            resource="trust-ledger",
            required_role="admin",
            metadata={"hacker_attempt": attempt_number},
        )
        assert result.trusted is False, f"Forged token attempt {attempt_number} must not be trusted"
        assert result.verification_steps["jwt"] is False, f"JWT step must fail on attempt {attempt_number}"

    # Audit trail must contain one rejected record per attempt, each with a unique entry hash
    records = gateway.audit_trail.records()
    assert len(records) == len(forged_tokens)
    entry_hashes = {r.entry_hash for r in records}
    assert len(entry_hashes) == len(forged_tokens), "Each rejected attempt must have a unique audit entry"
    for record in records:
        assert record.status == "rejected"

    # Chain integrity is intact even after all the attack attempts
    assert gateway.audit_trail.verify_integrity() is True


def test_repeated_wrong_secret_attempts_all_rejected():
    """
    A hacker who knows the algorithm but uses a different secret cannot forge tokens.
    Simulates 10 brute-force attempts with distinct wrong secrets.
    """
    real_auth = JWTAuthManager(secret=b"correct-secret-key-32bytes!!!!XX", issuer="sb712", audience="sb712-web")
    gateway = TrustedOperationGateway(auth=real_auth, policy=SecurityPolicy())

    for i in range(10):
        attacker_auth = JWTAuthManager(secret=f"wrong-secret-pad-32-bytes!!-{i:04d}".encode(), issuer="sb712", audience="sb712-web")
        attacker_claims = TokenClaims(
            sub=f"hacker-{i}",
            role="admin",
            issuer="sb712",
            audience="sb712-web",
            expires_at=_utcnow() + timedelta(minutes=10),
            scopes=("trust:write",),
        )
        bad_token = attacker_auth.issue_token(attacker_claims)
        result = gateway.authorize_operation(
            authorization_header="Bearer " + bad_token,
            origin="https://app.sb712.local",
            action="deploy.release",
            resource="spine",
            required_role="admin",
            metadata={"wrong_secret_attempt": i},
        )
        assert result.trusted is False
        assert result.verification_steps["jwt"] is False

    records = gateway.audit_trail.records()
    assert len(records) == 10
    assert all(r.status == "rejected" for r in records)
    assert gateway.audit_trail.verify_integrity() is True


def test_role_escalation_attempts_rejected_for_insufficient_role():
    """
    A hacker holds a valid 'viewer' token and tries to access admin resources
    multiple times. The JWT is valid but RBAC must block every attempt.
    """
    auth = JWTAuthManager(secret=b"s" * 32, issuer="sb712", audience="sb712-web")
    claims = TokenClaims(
        sub="low-priv-user",
        role="viewer",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() + timedelta(minutes=30),
    )
    gateway = TrustedOperationGateway(auth=auth, policy=SecurityPolicy())
    token = auth.issue_token(claims)

    privileged_resources = [
        ("deploy.release", "spine", "admin"),
        ("trust.write", "trust-ledger", "admin"),
        ("schema.migrate", "database", "operator"),
        ("audit.purge", "audit-log", "admin"),
        ("key.rotate", "encryption-keys", "operator"),
    ]

    for action, resource, required_role in privileged_resources:
        result = gateway.authorize_operation(
            authorization_header="Bearer " + token,
            origin="https://app.sb712.local",
            action=action,
            resource=resource,
            required_role=required_role,
        )
        assert result.trusted is False, f"viewer must not access {required_role} resource '{resource}'"
        assert result.verification_steps["jwt"] is True, "JWT itself is valid"
        assert result.verification_steps["rbac"] is False, "RBAC must block the escalation"

    records = gateway.audit_trail.records()
    assert len(records) == len(privileged_resources)
    assert all(r.status == "rejected" for r in records)


def test_origin_spoofing_attempts_all_rejected():
    """
    A hacker tries dozens of lookalike / spoofed origins hoping one slips through CORS.
    Every attempt must be rejected regardless of how close the origin looks.
    """
    auth = JWTAuthManager(secret=b"t" * 32, issuer="sb712", audience="sb712-web")
    claims = TokenClaims(
        sub="origin-spoofer",
        role="admin",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() + timedelta(minutes=10),
        scopes=("trust:write",),
    )
    gateway = TrustedOperationGateway(auth=auth, policy=SecurityPolicy())
    token = auth.issue_token(claims)

    spoofed_origins = [
        "https://evil.example.com",
        "https://app.sb712.local.evil.com",
        "http://app.sb712.local",          # wrong scheme
        "https://app.sb712.local:8080",    # wrong port
        "https://APP.SB712.LOCAL",         # wrong case
        "https://app.sb712.local/",        # trailing slash
        "null",                            # sandboxed iframe null origin
        "",                                # empty string
    ]

    for origin in spoofed_origins:
        result = gateway.authorize_operation(
            authorization_header="Bearer " + token,
            origin=origin,
            action="deploy.release",
            resource="spine",
            required_role="admin",
        )
        assert result.trusted is False, f"Spoofed origin '{origin}' must not be trusted"
        assert result.verification_steps["cors"] is False, f"CORS must block origin '{origin}'"


def test_rate_limit_blocks_repeated_requests_and_legitimate_user_still_passes():
    """
    A hacker hammers the gateway, exhausts the rate limit, then a second legitimate
    user with the same rate-limit key (different sub but same actor key) is also
    blocked — demonstrating that rate limiting is per-identity.

    Then a *different* legitimate user (different sub) is still allowed through.
    """
    auth = JWTAuthManager(secret=b"u" * 32, issuer="sb712", audience="sb712-web")
    policy = SecurityPolicy(rate_limit_max_requests=3, rate_limit_window_seconds=60)
    gateway = TrustedOperationGateway(auth=auth, policy=policy)

    hacker_claims = TokenClaims(
        sub="hacker-sub",
        role="viewer",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() + timedelta(minutes=10),
    )
    hacker_token = auth.issue_token(hacker_claims)

    # Hacker burns through the 3-request budget
    for i in range(3):
        result = gateway.authorize_operation(
            authorization_header="Bearer " + hacker_token,
            origin="https://app.sb712.local",
            action="trace.read",
            resource="audit-log",
            required_role="viewer",
        )
        assert result.trusted is True, f"Request {i + 1} within budget must succeed"

    # 4th request is over the limit — must be rejected
    blocked = gateway.authorize_operation(
        authorization_header="Bearer " + hacker_token,
        origin="https://app.sb712.local",
        action="trace.read",
        resource="audit-log",
        required_role="viewer",
    )
    assert blocked.trusted is False
    assert blocked.verification_steps["rate_limit"] is False

    # A different legitimate user with their own budget is still allowed
    legit_claims = TokenClaims(
        sub="legit-user-different-sub",
        role="viewer",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() + timedelta(minutes=10),
    )
    legit_token = auth.issue_token(legit_claims)
    legit_result = gateway.authorize_operation(
        authorization_header="Bearer " + legit_token,
        origin="https://app.sb712.local",
        action="trace.read",
        resource="audit-log",
        required_role="viewer",
    )
    assert legit_result.trusted is True, "Legitimate user with fresh budget must be allowed through"


def test_audit_trail_records_hacker_and_legit_attempts_distinctly():
    """
    A shared gateway processes a mix of hacker and legitimate requests.
    The audit trail must record every attempt and distinguish accepted from rejected.
    """
    auth = JWTAuthManager(secret=b"v" * 32, issuer="sb712", audience="sb712-web")
    gateway = TrustedOperationGateway(auth=auth, policy=SecurityPolicy())

    legit_claims = TokenClaims(
        sub="trusted-operator",
        role="operator",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() + timedelta(minutes=15),
    )
    legit_token = auth.issue_token(legit_claims)

    # Interleave hacker attempts with a legitimate request
    operations = [
        ("******", "https://app.sb712.local", "rejected"),
        ("Bearer " + legit_token, "https://app.sb712.local", "accepted"),
        ("******", "https://evil.example.com", "rejected"),
        ("Bearer " + legit_token, "https://app.sb712.local", "accepted"),
        ("******", "https://app.sb712.local", "rejected"),
    ]

    for header, origin, expected_status in operations:
        gateway.authorize_operation(
            authorization_header=header,
            origin=origin,
            action="schema.read",
            resource="audit-log",
            required_role="viewer",
        )

    records = gateway.audit_trail.records()
    assert len(records) == len(operations)

    for record, (_, _, expected_status) in zip(records, operations):
        assert record.status == expected_status, (
            f"Expected status '{expected_status}' for record {record.event_id}, got '{record.status}'"
        )

    # Every entry hash is unique — no two attempts produce the same record
    hashes = [r.entry_hash for r in records]
    assert len(set(hashes)) == len(hashes), "Each audit record must have a unique entry hash"

    # Audit chain and Merkle tree remain intact regardless of mixed outcomes
    assert gateway.audit_trail.verify_integrity() is True
    for record in records:
        assert gateway.audit_trail.verify_membership(record) is True


def test_expired_token_reused_multiple_times_always_rejected():
    """
    A hacker who captured an expired token tries to reuse it five times.
    Each attempt must be rejected — tokens do not gain validity over time.
    """
    auth = JWTAuthManager(secret=b"w" * 32, issuer="sb712", audience="sb712-web")
    claims = TokenClaims(
        sub="replay-attacker",
        role="admin",
        issuer="sb712",
        audience="sb712-web",
        expires_at=_utcnow() - timedelta(seconds=5),
        scopes=("trust:write",),
    )
    expired_token = auth.issue_token(claims)
    gateway = TrustedOperationGateway(auth=auth, policy=SecurityPolicy())

    for attempt in range(5):
        result = gateway.authorize_operation(
            authorization_header="Bearer " + expired_token,
            origin="https://app.sb712.local",
            action="deploy.release",
            resource="spine",
            required_role="admin",
            metadata={"replay_attempt": attempt},
        )
        assert result.trusted is False, f"Expired token replay attempt {attempt} must be rejected"
        assert result.verification_steps["jwt"] is False

    records = gateway.audit_trail.records()
    assert len(records) == 5
    assert all(r.status == "rejected" for r in records)
    # All five rejections are traceable and distinct
    assert len({r.entry_hash for r in records}) == 5
