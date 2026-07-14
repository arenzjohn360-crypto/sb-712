"""
Strand — tamper-evident communication channel between bricks.

Each strand:
  - Carries MessageEnvelopes sealed with SHA-256(sender || receiver || payload)
  - Detects tampered messages on receive()
  - Supports simulated network delay
  - Records tamper counts for metrics
"""
from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional


@dataclass
class MessageEnvelope:
    """A message carried on a Strand, integrity-protected by a SHA-256 seal."""

    sender_id: str
    receiver_id: str
    payload: bytes
    timestamp: float = field(default_factory=time.time)
    seal: str = field(default="")
    tampered: bool = False

    def __post_init__(self) -> None:
        if not self.seal:
            self.seal = self._compute_seal(self.payload)

    def _compute_seal(self, payload: bytes) -> str:
        material = (self.sender_id + "|" + self.receiver_id).encode() + payload
        return hashlib.sha256(material).hexdigest()

    def verify_seal(self) -> bool:
        return self.seal == self._compute_seal(self.payload)

    def as_dict(self) -> dict:
        return {
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "payload_hex": self.payload.hex(),
            "seal": self.seal,
            "timestamp": self.timestamp,
            "seal_valid": self.verify_seal(),
            "tampered": self.tampered,
        }


class StrandChannel:
    """
    One-directional tamper-evident communication channel.

    send(payload) → enqueues a sealed MessageEnvelope
    receive()     → dequeues and verifies; returns envelope (tampered flag set if bad)
    inject_tamper()  → next send() will carry a corrupted payload
    set_delay(ms)    → simulate network latency on receive()
    clear_fault()    → remove delay and pending tamper flag
    """

    def __init__(self, sender_id: str, receiver_id: str) -> None:
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self._queue: Deque[MessageEnvelope] = deque()
        self._delay_ms: float = 0.0
        self._tamper_next: bool = False
        self.tamper_count: int = 0
        self.message_count: int = 0

    def send(self, payload: bytes) -> MessageEnvelope:
        msg = MessageEnvelope(
            sender_id=self.sender_id,
            receiver_id=self.receiver_id,
            payload=payload,
        )

        if self._tamper_next:
            # Flip a byte in the payload while keeping the original seal → mismatch
            mutated = bytearray(msg.payload) if msg.payload else bytearray(b"\x00")
            mutated[0] ^= 0xAB
            tampered_msg = MessageEnvelope(
                sender_id=self.sender_id,
                receiver_id=self.receiver_id,
                payload=bytes(mutated),
                timestamp=msg.timestamp,
                seal=msg.seal,      # original seal — will not match mutated payload
                tampered=True,
            )
            self._queue.append(tampered_msg)
            self.tamper_count += 1
            self._tamper_next = False
            self.message_count += 1
            return tampered_msg

        self._queue.append(msg)
        self.message_count += 1
        return msg

    def receive(self) -> Optional[MessageEnvelope]:
        if not self._queue:
            return None
        if self._delay_ms > 0:
            time.sleep(self._delay_ms / 1000.0)
        return self._queue.popleft()

    def inject_tamper(self) -> None:
        """Mark next send() to deliver a tampered payload."""
        self._tamper_next = True

    def set_delay(self, delay_ms: float) -> None:
        self._delay_ms = max(0.0, delay_ms)

    def clear_fault(self) -> None:
        self._delay_ms = 0.0
        self._tamper_next = False

    def pending(self) -> int:
        return len(self._queue)

    def __repr__(self) -> str:
        return (
            f"StrandChannel({self.sender_id!r} → {self.receiver_id!r}, "
            f"pending={self.pending()}, tampers={self.tamper_count})"
        )
