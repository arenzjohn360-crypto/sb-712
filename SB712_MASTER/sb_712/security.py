from __future__ import annotations

import base64
import hmac
import json
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sb688 import MerkleTree

from .system import LedgerEntry, ProofLedger


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _json_dumps(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


class TokenValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    role: str
    issuer: str
    audience: str
    expires_at: datetime
    scopes: Tuple[str, ...] = ()
    token_use: str = "access_token"
    grant_type: str = "oauth2"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_payload(self) -> Dict[str, Any]:
        issued_at = int(_utcnow().timestamp())
        return {
            "sub": self.sub,
            "role": self.role,
            "iss": self.issuer,
            "aud": self.audience,
            "exp": int(self.expires_at.timestamp()),
            "iat": issued_at,
            "scope": " ".join(self.scopes),
            "token_use": self.token_use,
            "grant_type": self.grant_type,
            "sid": self.session_id,
        }


class JWTAuthManager:
    def __init__(self, secret: bytes, issuer: str, audience: str) -> None:
        if len(secret) < 32:
            raise ValueError("JWT secret must be at least 32 bytes")
        self._secret = secret
        self.issuer = issuer
        self.audience = audience

    def issue_token(self, claims: TokenClaims) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        payload = claims.to_payload()
        encoded_header = _b64url_encode(_json_dumps(header))
        encoded_payload = _b64url_encode(_json_dumps(payload))
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(self._secret, signing_input, digestmod="sha256").digest()
        return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"

    def validate_bearer_header(self, authorization_header: str) -> Dict[str, Any]:
        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise TokenValidationError("Authorization header must use ******")
        return self.validate_token(token)

    def validate_token(self, token: str) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenValidationError("JWT must contain header, payload, and signature")
        encoded_header, encoded_payload, encoded_signature = parts
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        expected_signature = hmac.new(self._secret, signing_input, digestmod="sha256").digest()
        signature = _b64url_decode(encoded_signature)
        if not hmac.compare_digest(signature, expected_signature):
            raise TokenValidationError("JWT signature validation failed")

        header = json.loads(_b64url_decode(encoded_header))
        payload = json.loads(_b64url_decode(encoded_payload))
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise TokenValidationError("Unsupported JWT header")
        if payload.get("iss") != self.issuer:
            raise TokenValidationError("Unexpected JWT issuer")
        if payload.get("aud") != self.audience:
            raise TokenValidationError("Unexpected JWT audience")
        if payload.get("token_use") != "access_token":
            raise TokenValidationError("JWT must be an access token")
        if payload.get("grant_type") != "oauth2":
            raise TokenValidationError("JWT must originate from OAuth2 flow")
        if int(payload.get("exp", 0)) < int(_utcnow().timestamp()):
            raise TokenValidationError("JWT has expired")
        if not payload.get("sub") or not payload.get("role"):
            raise TokenValidationError("JWT must include subject and role")
        payload["scope"] = tuple(filter(None, str(payload.get("scope", "")).split(" ")))
        return payload


@dataclass(frozen=True)
class SecurityPolicy:
    allowed_origins: Tuple[str, ...] = ("https://app.sb712.local",)
    role_hierarchy: Tuple[str, ...] = ("viewer", "operator", "admin")
    rate_limit_window_seconds: int = 60
    rate_limit_max_requests: int = 120
    secure_storage: str = "memory-access-token + httpOnly refresh cookie"
    csp_directives: Mapping[str, Tuple[str, ...]] = field(
        default_factory=lambda: {
            "default-src": ("'self'",),
            "script-src": ("'self'",),
            "style-src": ("'self'", "'unsafe-inline'"),
            "img-src": ("'self'", "data:"),
            "connect-src": ("'self'", "https://*.supabase.co", "wss://*.supabase.co"),
            "frame-ancestors": ("'none'",),
            "base-uri": ("'self'",),
            "object-src": ("'none'",),
        }
    )

    def role_allowed(self, actual_role: str, required_role: str) -> bool:
        if required_role not in self.role_hierarchy or actual_role not in self.role_hierarchy:
            return False
        return self.role_hierarchy.index(actual_role) >= self.role_hierarchy.index(required_role)

    def cors_headers(self, origin: str) -> Dict[str, str]:
        if origin not in self.allowed_origins:
            raise ValueError(f"Origin {origin} is not allowed")
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Trace-ID",
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
            "Vary": "Origin",
        }

    def csp_header(self) -> str:
        return "; ".join(f"{directive} {' '.join(values)}" for directive, values in self.csp_directives.items())

    def backend_manifest(self) -> Dict[str, Any]:
        return {
            "jwt_auth": True,
            "cors": list(self.allowed_origins),
            "rate_limit": {
                "window_seconds": self.rate_limit_window_seconds,
                "max_requests": self.rate_limit_max_requests,
            },
            "audit_encryption": "AES-256-GCM",
            "audit_log_mode": "encrypted + tamper evident",
        }

    def frontend_manifest(self) -> Dict[str, Any]:
        return {
            "oauth2_jwt_validation": True,
            "secure_storage": self.secure_storage,
            "role_based_access_control": list(self.role_hierarchy),
            "content_security_policy": self.csp_header(),
        }


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        current_time = time.monotonic() if now is None else now
        events = self._events[key]
        while events and current_time - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.max_requests:
            return False
        events.append(current_time)
        return True


@dataclass(frozen=True)
class EncryptedAuditRecord:
    event_id: str
    trace_id: str
    actor: str
    action: str
    resource: str
    status: str
    recorded_at: str
    key_id: int
    nonce_b64: str
    ciphertext_b64: str
    previous_hash: str
    entry_hash: str


class EncryptedAuditTrail:
    def __init__(self, key: Optional[bytes] = None) -> None:
        self._active_key_id = 0
        self._keys = {0: key if key is not None else AESGCM.generate_key(bit_length=256)}
        self._records: List[EncryptedAuditRecord] = []

    def rotate_key(self) -> int:
        new_key_id = max(self._keys) + 1
        self._keys[new_key_id] = AESGCM.generate_key(bit_length=256)
        self._active_key_id = new_key_id
        return new_key_id

    def append(
        self,
        actor: str,
        action: str,
        resource: str,
        status: str,
        metadata: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> EncryptedAuditRecord:
        recorded_at = _utcnow().isoformat()
        event_id = uuid.uuid4().hex
        trace_id = trace_id or uuid.uuid4().hex
        payload = {
            "event_id": event_id,
            "trace_id": trace_id,
            "actor": actor,
            "action": action,
            "resource": resource,
            "status": status,
            "metadata": dict(metadata or {}),
            "recorded_at": recorded_at,
        }
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._keys[self._active_key_id]).encrypt(nonce, _json_dumps(payload), None)
        previous_hash = self._records[-1].entry_hash if self._records else "GENESIS"
        nonce_b64 = _b64url_encode(nonce)
        ciphertext_b64 = _b64url_encode(ciphertext)
        entry_hash = sha256(
            "|".join(
                [
                    event_id,
                    trace_id,
                    actor,
                    action,
                    resource,
                    status,
                    recorded_at,
                    str(self._active_key_id),
                    nonce_b64,
                    ciphertext_b64,
                    previous_hash,
                ]
            ).encode("utf-8")
        ).hexdigest()
        record = EncryptedAuditRecord(
            event_id=event_id,
            trace_id=trace_id,
            actor=actor,
            action=action,
            resource=resource,
            status=status,
            recorded_at=recorded_at,
            key_id=self._active_key_id,
            nonce_b64=nonce_b64,
            ciphertext_b64=ciphertext_b64,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )
        self._records.append(record)
        return record

    def records(self) -> List[EncryptedAuditRecord]:
        return list(self._records)

    def decrypt(self, record: EncryptedAuditRecord) -> Dict[str, Any]:
        nonce = _b64url_decode(record.nonce_b64)
        ciphertext = _b64url_decode(record.ciphertext_b64)
        plaintext = AESGCM(self._keys[record.key_id]).decrypt(nonce, ciphertext, None)
        return json.loads(plaintext)

    def verify_integrity(self) -> bool:
        previous_hash = "GENESIS"
        for record in self._records:
            expected_hash = sha256(
                "|".join(
                    [
                        record.event_id,
                        record.trace_id,
                        record.actor,
                        record.action,
                        record.resource,
                        record.status,
                        record.recorded_at,
                        str(record.key_id),
                        record.nonce_b64,
                        record.ciphertext_b64,
                        previous_hash,
                    ]
                ).encode("utf-8")
            ).hexdigest()
            if record.previous_hash != previous_hash or record.entry_hash != expected_hash:
                return False
            previous_hash = record.entry_hash
        return True

    def merkle_root(self) -> str:
        tree = self._build_merkle()
        return tree.root.hex()

    def verify_membership(self, record: EncryptedAuditRecord) -> bool:
        tree = self._build_merkle()
        proof = tree.proof(record.event_id)
        if proof is None:
            return False
        return MerkleTree.verify_proof(record.event_id, record.entry_hash.encode("utf-8"), proof, tree.root)

    def _build_merkle(self) -> MerkleTree:
        return MerkleTree({record.event_id: record.entry_hash.encode("utf-8") for record in self._records})


@dataclass(frozen=True)
class TrustedOperationResult:
    trace_id: str
    trusted: bool
    reason: str
    claims: Dict[str, Any]
    verification_steps: Dict[str, bool]
    cors_headers: Dict[str, str]
    csp_header: str
    audit_entry_hash: str
    merkle_root: str
    ledger_entry_hash: str


class TrustedOperationGateway:
    def __init__(
        self,
        auth: JWTAuthManager,
        policy: Optional[SecurityPolicy] = None,
        audit_trail: Optional[EncryptedAuditTrail] = None,
        ledger: Optional[ProofLedger] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self.auth = auth
        self.policy = policy or SecurityPolicy()
        self.audit_trail = audit_trail or EncryptedAuditTrail()
        self.ledger = ledger or ProofLedger()
        self.rate_limiter = rate_limiter or RateLimiter(
            max_requests=self.policy.rate_limit_max_requests,
            window_seconds=self.policy.rate_limit_window_seconds,
        )

    def authorize_operation(
        self,
        authorization_header: str,
        origin: str,
        action: str,
        resource: str,
        required_role: str,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> TrustedOperationResult:
        verification_steps = {
            "jwt": False,
            "cors": False,
            "rbac": False,
            "rate_limit": False,
            "audit_chain": False,
            "merkle": False,
            "proof_ledger": False,
        }
        reasons: List[str] = []
        claims: Dict[str, Any] = {}
        actor = "anonymous"
        cors_headers: Dict[str, str] = {}
        trace_id = uuid.uuid4().hex

        try:
            claims = self.auth.validate_bearer_header(authorization_header)
            verification_steps["jwt"] = True
            actor = str(claims["sub"])
        except TokenValidationError as exc:
            reasons.append(str(exc))

        try:
            cors_headers = self.policy.cors_headers(origin)
            verification_steps["cors"] = True
        except ValueError as exc:
            reasons.append(str(exc))

        if claims:
            verification_steps["rbac"] = self.policy.role_allowed(str(claims["role"]), required_role)
            if not verification_steps["rbac"]:
                reasons.append(f"Role {claims['role']} cannot access {required_role} resource")
            if verification_steps["jwt"] and verification_steps["cors"] and verification_steps["rbac"]:
                verification_steps["rate_limit"] = self.rate_limiter.allow(actor)
                if not verification_steps["rate_limit"]:
                    reasons.append("Rate limit exceeded")
            else:
                verification_steps["rate_limit"] = False
        else:
            reasons.append("JWT validation failed")

        core_checks_passed = all(
            verification_steps[name] for name in ("jwt", "cors", "rbac", "rate_limit")
        )
        record = self.audit_trail.append(
            actor=actor,
            action=action,
            resource=resource,
            status="accepted" if core_checks_passed else "rejected",
            trace_id=trace_id,
            metadata={
                "origin": origin,
                "required_role": required_role,
                "reasons": list(dict.fromkeys(reasons)),
                "verification_steps": {
                    key: value for key, value in verification_steps.items() if key in {"jwt", "cors", "rbac", "rate_limit"}
                },
                **dict(metadata or {}),
            },
        )
        verification_steps["audit_chain"] = self.audit_trail.verify_integrity()
        verification_steps["merkle"] = self.audit_trail.verify_membership(record)

        preliminary_trust = core_checks_passed and verification_steps["audit_chain"] and verification_steps["merkle"]
        ledger_entry = self.ledger.append(
            LedgerEntry(
                event_type="security_gate_decision",
                object_id=resource,
                before_state="ACTIVE",
                after_state="VERIFIED" if preliminary_trust else "REJECTED",
                verification_result="VERIFY_PASSED" if preliminary_trust else "VERIFY_FAILED",
                repair_result="N/A",
                certification_result="CERTIFIED" if preliminary_trust else "NOT_CERTIFIED",
                metadata={
                    "trace_id": trace_id,
                    "actor": actor,
                    "action": action,
                    "origin": origin,
                    "required_role": required_role,
                },
            )
        )
        verification_steps["proof_ledger"] = self.ledger.verify_integrity()
        trusted = preliminary_trust and verification_steps["proof_ledger"]
        reason = "Operation verified and trusted." if trusted else "; ".join(list(dict.fromkeys(reasons)) or ["Verification failed"])

        return TrustedOperationResult(
            trace_id=trace_id,
            trusted=trusted,
            reason=reason,
            claims=claims,
            verification_steps=verification_steps,
            cors_headers=cors_headers,
            csp_header=self.policy.csp_header(),
            audit_entry_hash=record.entry_hash,
            merkle_root=self.audit_trail.merkle_root(),
            ledger_entry_hash=ledger_entry.entry_hash,
        )


@dataclass(frozen=True)
class SupabaseSecurityBlueprint:
    schema_version: str = "0001_sb712_security"
    audit_table: str = "sb712_audit_log"
    trust_table: str = "sb712_trust_ledger"
    version_table: str = "sb712_schema_versions"
    publication_name: str = "sb712_realtime"

    def render_migration_sql(self) -> str:
        return f"""-- SB-712 security + trust bootstrap
create extension if not exists pgcrypto;

create table if not exists public.{self.audit_table} (
    id uuid primary key default gen_random_uuid(),
    actor_id uuid references auth.users(id),
    trace_id uuid not null default gen_random_uuid(),
    action text not null,
    resource text not null,
    status text not null,
    payload_ciphertext bytea not null,
    payload_nonce bytea not null,
    payload_key_id integer not null default 0,
    previous_hash text not null,
    entry_hash text not null unique,
    merkle_root text not null,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.{self.trust_table} (
    id uuid primary key default gen_random_uuid(),
    trace_id uuid not null,
    operation_name text not null,
    verification_count integer not null check (verification_count >= 3),
    verification_proof jsonb not null,
    immutable_root text not null,
    trusted boolean not null default false,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.{self.version_table} (
    version text primary key,
    rollback_version text not null,
    rollback_sql text not null,
    applied_at timestamptz not null default timezone('utc', now())
);

alter table public.{self.audit_table} enable row level security;
alter table public.{self.trust_table} enable row level security;
alter table public.{self.version_table} enable row level security;

create policy "{self.audit_table}_actor_read"
    on public.{self.audit_table}
    for select
    to authenticated
    using (actor_id = auth.uid() or auth.role() = 'service_role');

create policy "{self.audit_table}_service_write"
    on public.{self.audit_table}
    for insert
    to authenticated
    with check (actor_id = auth.uid() or auth.role() = 'service_role');

create policy "{self.trust_table}_read"
    on public.{self.trust_table}
    for select
    to authenticated
    using (true);

create policy "{self.trust_table}_admin_write"
    on public.{self.trust_table}
    for all
    to authenticated
    using (coalesce(auth.jwt() ->> 'role', '') = 'admin' or auth.role() = 'service_role')
    with check (coalesce(auth.jwt() ->> 'role', '') = 'admin' or auth.role() = 'service_role');

create policy "{self.version_table}_service_only"
    on public.{self.version_table}
    for all
    to authenticated
    using (auth.role() = 'service_role')
    with check (auth.role() = 'service_role');

drop publication if exists {self.publication_name};
create publication {self.publication_name}
    for table public.{self.audit_table}, public.{self.trust_table};

insert into public.{self.version_table} (version, rollback_version, rollback_sql)
values ('{self.schema_version}', '0000', '{self.schema_version}_rollback.sql')
on conflict (version) do nothing;
"""

    def render_rollback_sql(self) -> str:
        return f"""drop publication if exists {self.publication_name};
drop policy if exists "{self.audit_table}_actor_read" on public.{self.audit_table};
drop policy if exists "{self.audit_table}_service_write" on public.{self.audit_table};
drop policy if exists "{self.trust_table}_read" on public.{self.trust_table};
drop policy if exists "{self.trust_table}_admin_write" on public.{self.trust_table};
drop policy if exists "{self.version_table}_service_only" on public.{self.version_table};
drop table if exists public.{self.audit_table};
drop table if exists public.{self.trust_table};
drop table if exists public.{self.version_table};
"""

    def manifest(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "realtime_publication": self.publication_name,
            "tables": [self.audit_table, self.trust_table, self.version_table],
            "rls_enabled": True,
            "encrypted_columns": ["payload_ciphertext", "payload_nonce", "payload_key_id"],
        }


@dataclass(frozen=True)
class VSCodeWorkspaceBlueprint:
    def launch_json(self) -> Dict[str, Any]:
        return {
            "version": "0.2.0",
            "configurations": [
                {
                    "name": "SB712: targeted security tests",
                    "type": "debugpy",
                    "request": "launch",
                    "module": "pytest",
                    "args": ["tests/test_security.py", "-q"],
                    "cwd": "${workspaceFolder}",
                    "envFile": "${workspaceFolder}/.env",
                    "justMyCode": True,
                },
                {
                    "name": "SB712: service host heartbeat",
                    "type": "debugpy",
                    "request": "launch",
                    "module": "sb_712.service_host",
                    "args": ["--heartbeat-once"],
                    "cwd": "${workspaceFolder}",
                    "envFile": "${workspaceFolder}/.env",
                    "justMyCode": True,
                },
            ],
        }

    def settings_json(self) -> Dict[str, Any]:
        return {
            "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
            "python.envFile": "${workspaceFolder}/.env",
            "python.testing.pytestEnabled": True,
            "python.testing.pytestArgs": ["tests", "-q"],
            "terminal.integrated.cwd": "${workspaceFolder}",
        }

    def extensions_json(self) -> Dict[str, Any]:
        return {
            "recommendations": [
                "ms-python.python",
                "ms-python.vscode-pylance",
                "supabase.supabase",
                "github.copilot",
            ]
        }

    def manifest(self) -> Dict[str, Any]:
        return {
            "launch": self.launch_json(),
            "settings": self.settings_json(),
            "extensions": self.extensions_json(),
        }


@dataclass(frozen=True)
class WindowsServiceInstallerBlueprint:
    service_name: str = "SB712SecurityHost"
    install_root: str = r"$env:ProgramFiles\SB712\system"
    module_name: str = "sb_712.service_host"

    def render_script(self) -> str:
        return f"""param(
    [string]$ServiceName = "{self.service_name}",
    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$InstallRoot = "{self.install_root}",
    [string]$PythonExe = "py",
    [string]$EnvFile = (Join-Path $InstallRoot ".env")
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -Path (Join-Path $SourceRoot "*") -Destination $InstallRoot -Recurse -Force
& $PythonExe -m pip install $InstallRoot

$BinaryPath = "$PythonExe -m {self.module_name} --env-file `"$EnvFile`""
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {{
    Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 1
}}

New-Service -Name $ServiceName `
    -BinaryPathName $BinaryPath `
    -DisplayName "SB-712 Security Host" `
    -Description "SB-712 verification, trace logging, and trust ledger host" `
    -StartupType Automatic

Start-Service -Name $ServiceName
Write-Host "Installed $ServiceName into $InstallRoot"
"""

    def manifest(self) -> Dict[str, Any]:
        return {
            "service_name": self.service_name,
            "install_root": self.install_root,
            "module_name": self.module_name,
        }


def render_env_template() -> str:
    return "\n".join(
        [
            "SB712_JWT_SECRET=replace-with-32-byte-secret",
            "SUPABASE_URL=https://your-project.supabase.co",
            "SUPABASE_ANON_KEY=replace-with-anon-key",
            "SUPABASE_SERVICE_ROLE_KEY=replace-with-service-role-key",
            "SB712_AUDIT_LOG_KEY=replace-with-32-byte-audit-key",
            "SB712_ALLOWED_ORIGINS=https://app.sb712.local",
            "",
        ]
    )


def build_runtime_manifest() -> Dict[str, Any]:
    policy = SecurityPolicy()
    supabase = SupabaseSecurityBlueprint()
    vscode = VSCodeWorkspaceBlueprint()
    installer = WindowsServiceInstallerBlueprint()
    return {
        "backend_security": policy.backend_manifest(),
        "frontend_security": policy.frontend_manifest(),
        "supabase": supabase.manifest(),
        "vscode": vscode.manifest(),
        "installer": installer.manifest(),
        "upgrade": {
            "schema_version": supabase.schema_version,
            "rollback": f"{supabase.schema_version}_rollback.sql",
            "trust_rule": "No active state becomes trusted state without verification",
        },
    }
