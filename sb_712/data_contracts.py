from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping, Optional, Sequence, Tuple
import uuid


CANONICAL_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, 2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(parts: Sequence[str]) -> str:
    payload = "|".join(parts)
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalMetadata:
    object_id: str
    source: str
    created_at: datetime = field(default_factory=utcnow)
    schema_version: int = CANONICAL_SCHEMA_VERSION
    integrity_proof: str = ""
    lineage_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_lineage_id: Optional[str] = None


@dataclass(frozen=True)
class DataContractIssue:
    code: str
    message: str


class DataContractError(ValueError):
    def __init__(self, issue: DataContractIssue):
        self.issue = issue
        super().__init__(f"{issue.code}: {issue.message}")


class DataContractValidator:
    @staticmethod
    def require_supported_schema(schema_version: int) -> None:
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise DataContractError(
                DataContractIssue(
                    code="SCHEMA_UNSUPPORTED",
                    message=f"Schema version {schema_version} is not supported",
                )
            )

    @staticmethod
    def require_non_empty(value: str, field_name: str) -> None:
        if not value or not value.strip():
            raise DataContractError(
                DataContractIssue(
                    code="FIELD_INVALID",
                    message=f"{field_name} must be a non-empty string",
                )
            )

    @staticmethod
    def normalize_source(source: str) -> str:
        DataContractValidator.require_non_empty(source, "source")
        normalized = source.strip().lower().replace(" ", "_")
        if not normalized:
            raise DataContractError(
                DataContractIssue(
                    code="SOURCE_INVALID",
                    message="source cannot normalize to empty value",
                )
            )
        return normalized

    @staticmethod
    def validate_contract(
        *,
        object_id: str,
        source: str,
        schema_version: int,
        lineage_id: Optional[str],
    ) -> Tuple[str, str]:
        DataContractValidator.require_non_empty(object_id, "object_id")
        normalized_source = DataContractValidator.normalize_source(source)
        DataContractValidator.require_supported_schema(schema_version)
        if lineage_id is not None:
            DataContractValidator.require_non_empty(lineage_id, "lineage_id")
        return object_id.strip(), normalized_source

    @staticmethod
    def migrate_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        schema_version = int(payload.get("schema_version", 1))
        DataContractValidator.require_supported_schema(schema_version)
        if schema_version == CANONICAL_SCHEMA_VERSION:
            return payload
        upgraded = dict(payload)
        upgraded["schema_version"] = CANONICAL_SCHEMA_VERSION
        upgraded.setdefault("lineage_id", uuid.uuid4().hex)
        upgraded.setdefault("created_at", utcnow().isoformat())
        upgraded.setdefault("integrity_proof", "")
        return upgraded
