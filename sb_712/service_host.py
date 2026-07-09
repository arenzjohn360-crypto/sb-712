from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, Iterable, Optional

from .security import build_runtime_manifest
from .system import HeartbeatMonitor, SystemConfig


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _read_total_ram_gb() -> Optional[float]:
    page_size_name = "SC_PAGE_SIZE"
    phys_pages_name = "SC_PHYS_PAGES"
    if not hasattr(os, "sysconf"):
        return None
    try:
        page_size = int(os.sysconf(page_size_name))
        phys_pages = int(os.sysconf(phys_pages_name))
    except (ValueError, OSError, TypeError, AttributeError):
        return None
    if page_size <= 0 or phys_pages <= 0:
        return None
    return (page_size * phys_pages) / (1024**3)


def _read_cpu_load_ratio() -> Optional[float]:
    if not hasattr(os, "getloadavg"):
        return None
    try:
        one_minute_load = float(os.getloadavg()[0])
    except (OSError, TypeError, ValueError, AttributeError):
        return None
    cpu_count = max(1, int(os.cpu_count() or 1))
    return _clamp(one_minute_load / cpu_count)


def _telemetry_snapshot(config: SystemConfig) -> Dict[str, float]:
    total_ram_gb = _read_total_ram_gb()
    cpu_load_ratio = _read_cpu_load_ratio()

    if total_ram_gb is None:
        ram_readiness = 0.5
    else:
        ram_readiness = _clamp(total_ram_gb / float(config.minimum_ram_gb))

    if cpu_load_ratio is None:
        cpu_headroom = 0.5
    else:
        cpu_headroom = _clamp(1.0 - cpu_load_ratio)

    node_readiness = _clamp((ram_readiness + cpu_headroom) / 2.0)

    required_env = (
        "SB712_JWT_SECRET",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SB712_AUDIT_LOG_KEY",
    )
    configured_count = sum(1 for key in required_env if os.environ.get(key))
    recovery_readiness = configured_count / len(required_env)
    trust_ratio = recovery_readiness

    heartbeat_score = (
        node_readiness * 0.5 + recovery_readiness * 0.3 + trust_ratio * 0.2
    ) * 100.0

    return {
        "heartbeat_score": _clamp(heartbeat_score / 100.0) * 100.0,
        "node_readiness": node_readiness,
        "recovery_readiness": recovery_readiness,
        "trust_ratio": trust_ratio,
        "cpu_load_ratio": cpu_load_ratio if cpu_load_ratio is not None else -1.0,
        "total_ram_gb": total_ram_gb if total_ram_gb is not None else -1.0,
        "configured_env_vars": float(configured_count),
        "required_env_vars": float(len(required_env)),
    }


def _load_env_file(path: Optional[str]) -> None:
    if not path or not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _heartbeat_payload() -> dict:
    config = SystemConfig()
    monitor = HeartbeatMonitor(config)
    telemetry = _telemetry_snapshot(config)
    health = monitor.evaluate(
        heartbeat_score=telemetry["heartbeat_score"],
        node_readiness=telemetry["node_readiness"],
        recovery_readiness=telemetry["recovery_readiness"],
        trust_ratio=telemetry["trust_ratio"],
    )
    manifest = build_runtime_manifest()
    manifest["heartbeat"] = {
        "score": health.heartbeat_score,
        "level": health.heartbeat_level.value,
        "node_readiness": health.node_readiness,
        "recovery_readiness": health.recovery_readiness,
        "trust_ratio": health.trust_ratio,
        "timestamp": health.timestamp.isoformat(),
        "telemetry": {
            "cpu_load_ratio": None if telemetry["cpu_load_ratio"] < 0 else telemetry["cpu_load_ratio"],
            "total_ram_gb": None if telemetry["total_ram_gb"] < 0 else telemetry["total_ram_gb"],
            "configured_env_vars": int(telemetry["configured_env_vars"]),
            "required_env_vars": int(telemetry["required_env_vars"]),
        },
    }
    return manifest


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SB-712 security host")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--heartbeat-once", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    _load_env_file(args.env_file)
    if args.heartbeat_once:
        print(json.dumps(_heartbeat_payload(), sort_keys=True))
        return 0

    while True:
        print(json.dumps(_heartbeat_payload(), sort_keys=True), flush=True)
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
