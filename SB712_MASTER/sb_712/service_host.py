from __future__ import annotations

import argparse
import json
import os
import time
from typing import Iterable, Optional

from .security import build_runtime_manifest
from .system import HeartbeatMonitor, SystemConfig


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
    monitor = HeartbeatMonitor(SystemConfig())
    health = monitor.evaluate(
        heartbeat_score=100.0,
        node_readiness=1.0,
        recovery_readiness=1.0,
        trust_ratio=1.0,
    )
    manifest = build_runtime_manifest()
    manifest["heartbeat"] = {
        "score": health.heartbeat_score,
        "level": health.heartbeat_level.value,
        "node_readiness": health.node_readiness,
        "recovery_readiness": health.recovery_readiness,
        "trust_ratio": health.trust_ratio,
        "timestamp": health.timestamp.isoformat(),
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
